"""Safe, deterministic normalization of D0 log files and compressed log bundles."""

from __future__ import annotations

import codecs
from collections import deque
from dataclasses import dataclass
import gzip
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
from typing import BinaryIO
import zipfile

from .store import InvalidBoundaryError


PLAIN_MEDIA_TYPES = {
    "text/plain", "application/json", "application/x-ndjson", "text/csv", "text/tab-separated-values",
}
ARCHIVE_MEDIA_TYPES = {"application/zip", "application/gzip", "application/x-gzip"}
ALLOWED_LOG_SUFFIXES = {".log", ".txt", ".out", ".err", ".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".conf"}
KNOWN_EXTENSIONLESS_LOGS = {"messages", "secure", "syslog", "dmesg", "journal"}
ARCHIVE_SUFFIXES = (".zip", ".gz", ".tgz", ".tar.gz", ".7z", ".rar", ".bz2", ".xz")
INTERESTING = re.compile(
    r"(?i)(fatal|panic|exception|traceback|error|failed|failure|timeout|timed out|out of memory|oom|warn|denied|refused)"
)
INTERESTING_TOKENS = (
    b"fatal", b"panic", b"exception", b"traceback", b"error", b"failed", b"failure", b"timeout",
    b"timed out", b"out of memory", b"oom", b"warn", b"denied", b"refused",
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*:\s*(?:bearer|basic))\s+\S+"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
)


@dataclass(frozen=True)
class LogAnalysis:
    evidence_text: str
    entry_count: int
    extracted_bytes: int
    truncated: bool
    redaction_count: int


def is_log_media_type(media_type: str) -> bool:
    return media_type in PLAIN_MEDIA_TYPES or media_type in ARCHIVE_MEDIA_TYPES


def _is_log_name(name: str) -> bool:
    path = Path(name)
    lowered = path.name.casefold()
    return (
        path.suffix.casefold() in ALLOWED_LOG_SUFFIXES
        or bool(re.search(r"\.(?:log|out|err)\.\d+$", lowered))
        or lowered in KNOWN_EXTENSIONLESS_LOGS
    )


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized or not path.parts or len(normalized) > 255 or normalized.startswith("/") or any(":" in part for part in path.parts)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise InvalidBoundaryError("archive member path is unsafe")
    lowered = normalized.casefold()
    if lowered.endswith(ARCHIVE_SUFFIXES):
        raise InvalidBoundaryError("nested archives are not permitted")
    if not _is_log_name(path.name):
        raise InvalidBoundaryError("archive contains a non-log member")
    return normalized


def _redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern in SECRET_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if match.lastindex and match.lastindex >= 2:
                return f"{match.group(1)}{match.group(2)}[REDACTED]"
            if match.lastindex:
                return f"{match.group(1)} [REDACTED]"
            return "[REDACTED]"
        text = pattern.sub(replace, text)
    return text, count


def parse_log_artifact(
    filename: str, media_type: str, data: bytes, *, max_entries: int, max_extracted_bytes: int,
    max_ratio: int, max_evidence_chars: int,
) -> LogAnalysis:
    with tempfile.NamedTemporaryFile(prefix="techflow-log-", suffix=".bin") as temporary:
        temporary.write(data)
        temporary.flush()
        return parse_log_artifact_path(
            filename, media_type, Path(temporary.name), max_entries=max_entries,
            max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio,
            max_evidence_chars=max_evidence_chars,
        )


STREAM_CHUNK_BYTES = 1024 * 1024
MAX_LOG_LINE_CHARS = 1024 * 1024
CONTROL_BYTES = re.compile(rb"[\x01-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class _EntryScan:
    name: str
    selected: tuple[tuple[int, str], ...]
    bytes_read: int
    truncated: bool
    redaction_count: int


class _EvidenceSelector:
    def __init__(self, name: str, max_chars: int) -> None:
        self.name = name
        self.max_chars = max_chars
        self.first: list[tuple[int, str]] = []
        self.last: deque[tuple[int, str]] = deque(maxlen=20)
        self.previous: deque[tuple[int, str]] = deque(maxlen=2)
        self.selected: dict[int, str] = {}
        self.selected_chars = 0
        self.interesting = False
        self.after = 0
        self.line_number = 0
        self.redactions = 0
        self.truncated = False

    def _keep(self, number: int, line: str) -> None:
        if number in self.selected:
            return
        rendered, count = _redact(line[:4000])
        if self.selected_chars + len(rendered) > self.max_chars * 2:
            self.truncated = True
            return
        self.selected[number] = rendered
        self.selected_chars += len(rendered)
        self.redactions += count

    def line(self, raw: str) -> None:
        self.line_number += 1
        line = raw.rstrip("\r\n")
        item = (self.line_number, line)
        if len(self.first) < 20:
            self.first.append(item)
        self.last.append(item)
        if INTERESTING.search(line):
            self.interesting = True
            for number, previous in self.previous:
                self._keep(number, previous)
            self._keep(*item)
            self.after = 2
        elif self.after:
            self._keep(*item)
            self.after -= 1
        self.previous.append(item)

    def plain_chunk(self, text: str) -> None:
        """Advance a complete, non-interesting block without per-line regex calls."""
        line_count = text.count("\n")
        if not line_count:
            return
        first_number = self.line_number + 1
        needed = max(0, 20 - len(self.first))
        if needed:
            take = min(needed, line_count)
            for offset, line in enumerate(text.split("\n", take)[:take]):
                self.first.append((first_number + offset, line.rstrip("\r")))
        trailing = text[:-1].rsplit("\n", 20)[-20:]
        trailing_start = first_number + line_count - len(trailing)
        for offset, line in enumerate(trailing):
            self.last.append((trailing_start + offset, line.rstrip("\r")))
        self.previous.clear()
        self.previous.extend(self.last)
        while len(self.previous) > 2:
            self.previous.popleft()
        self.line_number += line_count

    def result(self, bytes_read: int) -> _EntryScan:
        if not self.line_number:
            raise InvalidBoundaryError("empty log entries are not permitted")
        if self.interesting:
            selected = self.selected
        else:
            selected = {}
            for number, line in self.first + list(self.last):
                if number not in selected:
                    redacted, count = _redact(line[:4000])
                    selected[number] = redacted
                    self.redactions += count
        return _EntryScan(
            self.name, tuple(sorted(selected.items())), bytes_read,
            self.truncated, self.redactions,
        )


def _scan_log_stream(name: str, stream: BinaryIO, *, max_bytes: int, max_evidence_chars: int) -> _EntryScan:
    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    selector = _EvidenceSelector(name, max_evidence_chars)
    buffered = ""
    total = controls = characters = 0
    try:
        while True:
            chunk = stream.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
            if b"\x00" in chunk:
                raise InvalidBoundaryError("binary log content is not permitted")
            text = decoder.decode(chunk)
            controls += len(CONTROL_BYTES.findall(chunk))
            characters += len(text)
            combined = buffered + text
            last_newline = combined.rfind("\n")
            if last_newline < 0:
                buffered = combined
            else:
                complete = combined[:last_newline + 1]
                buffered = combined[last_newline + 1:]
                lowered = complete.encode("utf-8").lower()
                if selector.after or any(token in lowered for token in INTERESTING_TOKENS):
                    for line in complete[:-1].split("\n"):
                        selector.line(line)
                else:
                    selector.plain_chunk(complete)
            if len(buffered) > MAX_LOG_LINE_CHARS:
                raise InvalidBoundaryError("log line exceeds the permitted boundary")
        buffered += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise InvalidBoundaryError("log content must be UTF-8") from exc
    if buffered:
        selector.line(buffered)
    if controls > max(2, characters // 100):
        raise InvalidBoundaryError("binary-like log content is not permitted")
    return selector.result(total)


def _render_streamed_evidence(entries: list[_EntryScan], max_chars: int) -> tuple[str, bool, int]:
    blocks: list[str] = []
    used = 0
    truncated = any(entry.truncated for entry in entries)
    redactions = sum(entry.redaction_count for entry in entries)
    for entry in entries:
        selected = list(entry.selected)
        index = 0
        while index < len(selected):
            start = index
            while index + 1 < len(selected) and selected[index + 1][0] == selected[index][0] + 1:
                index += 1
            end = index
            lines = selected[start:end + 1]
            block = [f"@@ {entry.name}:{lines[0][0]}-{lines[-1][0]}"]
            block.extend(f"{number}: {line}" for number, line in lines)
            rendered = "\n".join(block) + "\n"
            if used + len(rendered) > max_chars:
                truncated = True
                remaining = max_chars - used
                if remaining > 128:
                    blocks.append(rendered[:remaining] + "\n[TRUNCATED]\n")
                return "".join(blocks), truncated, redactions
            blocks.append(rendered)
            used += len(rendered)
            index += 1
    return "".join(blocks), truncated, redactions


def _archive_total_allowed(compressed_bytes: int, max_extracted_bytes: int, max_ratio: int) -> int:
    return min(max_extracted_bytes, max(compressed_bytes, 1) * max_ratio)


def _is_ignored_archive_metadata(name: str) -> bool:
    """Ignore platform metadata that is never useful as technical-support evidence."""
    parts = [part for part in name.replace("\\", "/").split("/") if part]
    if not parts:
        return False
    basename = parts[-1]
    return "__MACOSX" in parts or basename == ".DS_Store" or basename.startswith("._")


def _scan_zip_path(
    path: Path, *, max_entries: int, max_extracted_bytes: int, max_ratio: int, max_evidence_chars: int,
) -> tuple[list[_EntryScan], int]:
    compressed_bytes = path.stat().st_size
    allowed = _archive_total_allowed(compressed_bytes, max_extracted_bytes, max_ratio)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [
                item for item in archive.infolist()
                if not item.is_dir() and not _is_ignored_archive_metadata(item.filename)
            ]
            if not infos or len(infos) > max_entries:
                raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
            declared_total = 0
            scans: list[_EntryScan] = []
            for info in infos:
                name = _safe_member_name(info.filename)
                if info.flag_bits & 0x1:
                    raise InvalidBoundaryError("encrypted archives are not permitted")
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type not in {0, stat.S_IFREG}:
                    raise InvalidBoundaryError("archive links and special files are not permitted")
                declared_total += info.file_size
                if declared_total > allowed:
                    raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
                with archive.open(info) as stream:
                    scan = _scan_log_stream(
                        name, stream, max_bytes=info.file_size, max_evidence_chars=max_evidence_chars,
                    )
                if scan.bytes_read != info.file_size:
                    raise InvalidBoundaryError("archive member size is inconsistent")
                scans.append(scan)
            return scans, declared_total
    except InvalidBoundaryError:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
        raise InvalidBoundaryError("invalid ZIP log archive") from exc


def _scan_gzip_path(
    filename: str, path: Path, *, max_extracted_bytes: int, max_ratio: int, max_evidence_chars: int,
) -> tuple[list[_EntryScan], int]:
    name = filename[:-3] if filename.casefold().endswith(".gz") else filename + ".log"
    if not _is_log_name(name):
        raise InvalidBoundaryError("GZIP payload filename is not a supported log")
    allowed = _archive_total_allowed(path.stat().st_size, max_extracted_bytes, max_ratio)
    try:
        with gzip.open(path, "rb") as stream:
            scan = _scan_log_stream(
                Path(name).name, stream, max_bytes=allowed, max_evidence_chars=max_evidence_chars,
            )
        return [scan], scan.bytes_read
    except InvalidBoundaryError:
        raise
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise InvalidBoundaryError("invalid GZIP log archive") from exc


def _scan_tar_gz_path(
    path: Path, *, max_entries: int, max_extracted_bytes: int, max_ratio: int, max_evidence_chars: int,
) -> tuple[list[_EntryScan], int]:
    allowed = _archive_total_allowed(path.stat().st_size, max_extracted_bytes, max_ratio)
    scans: list[_EntryScan] = []
    total = 0
    try:
        with tarfile.open(path, mode="r|gz") as archive:
            for member in archive:
                if member.isdir():
                    continue
                if _is_ignored_archive_metadata(member.name):
                    continue
                if not member.isfile():
                    raise InvalidBoundaryError("archive links and special files are not permitted")
                if len(scans) >= max_entries:
                    raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
                name = _safe_member_name(member.name)
                total += member.size
                if total > allowed:
                    raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
                stream = archive.extractfile(member)
                if stream is None:
                    raise InvalidBoundaryError("archive member cannot be read")
                scan = _scan_log_stream(
                    name, stream, max_bytes=member.size, max_evidence_chars=max_evidence_chars,
                )
                if scan.bytes_read != member.size:
                    raise InvalidBoundaryError("archive member size is inconsistent")
                scans.append(scan)
        if not scans:
            raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
        return scans, total
    except InvalidBoundaryError:
        raise
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise InvalidBoundaryError("invalid TAR.GZ log archive") from exc


def parse_log_artifact_path(
    filename: str, media_type: str, path: Path, *, max_entries: int, max_extracted_bytes: int,
    max_ratio: int, max_evidence_chars: int,
) -> LogAnalysis:
    lowered = filename.casefold()
    with path.open("rb") as source:
        header = source.read(4)
    if media_type in PLAIN_MEDIA_TYPES:
        if not _is_log_name(filename):
            raise InvalidBoundaryError("filename is not a supported log")
        with path.open("rb") as source:
            scans = [_scan_log_stream(
                filename, source, max_bytes=path.stat().st_size,
                max_evidence_chars=max_evidence_chars,
            )]
        extracted = scans[0].bytes_read
    elif media_type == "application/zip":
        if not lowered.endswith(".zip") or header not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
            raise InvalidBoundaryError("artifact bytes do not match ZIP")
        scans, extracted = _scan_zip_path(
            path, max_entries=max_entries, max_extracted_bytes=max_extracted_bytes,
            max_ratio=max_ratio, max_evidence_chars=max_evidence_chars,
        )
    elif media_type in {"application/gzip", "application/x-gzip"}:
        if not lowered.endswith((".gz", ".tgz")) or header[:2] != b"\x1f\x8b":
            raise InvalidBoundaryError("artifact bytes do not match GZIP")
        if lowered.endswith((".tar.gz", ".tgz")):
            scans, extracted = _scan_tar_gz_path(
                path, max_entries=max_entries, max_extracted_bytes=max_extracted_bytes,
                max_ratio=max_ratio, max_evidence_chars=max_evidence_chars,
            )
        else:
            scans, extracted = _scan_gzip_path(
                filename, path, max_extracted_bytes=max_extracted_bytes,
                max_ratio=max_ratio, max_evidence_chars=max_evidence_chars,
            )
    else:
        raise InvalidBoundaryError("unsupported log artifact media type")
    evidence, truncated, redactions = _render_streamed_evidence(scans, max_evidence_chars)
    if not evidence:
        raise InvalidBoundaryError("log artifact produced no usable evidence")
    return LogAnalysis(evidence, len(scans), extracted, truncated, redactions)
