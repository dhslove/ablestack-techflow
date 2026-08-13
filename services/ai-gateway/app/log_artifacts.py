"""Safe, deterministic normalization of D0 log files and compressed log bundles."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
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


def _decode_log(data: bytes) -> str:
    if not data:
        raise InvalidBoundaryError("empty log entries are not permitted")
    if b"\x00" in data:
        raise InvalidBoundaryError("binary log content is not permitted")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidBoundaryError("log content must be UTF-8") from exc
    controls = sum(ord(char) < 32 and char not in "\r\n\t" for char in text)
    if controls > max(2, len(text) // 100):
        raise InvalidBoundaryError("binary-like log content is not permitted")
    return text.replace("\r\n", "\n").replace("\r", "\n")


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


def _selected_ranges(lines: list[str]) -> list[tuple[int, int]]:
    interesting = {index for index, line in enumerate(lines) if INTERESTING.search(line)}
    selected: set[int] = set()
    if interesting:
        for index in interesting:
            selected.update(range(max(0, index - 2), min(len(lines), index + 3)))
    else:
        selected.update(range(min(20, len(lines))))
        selected.update(range(max(0, len(lines) - 20), len(lines)))
    ranges: list[tuple[int, int]] = []
    for index in sorted(selected):
        if not ranges or index > ranges[-1][1] + 1:
            ranges.append((index, index))
        else:
            ranges[-1] = (ranges[-1][0], index)
    return ranges


def _evidence(entries: list[tuple[str, str]], max_chars: int) -> tuple[str, bool, int]:
    blocks: list[str] = []
    redactions = 0
    truncated = False
    for name, raw_text in entries:
        text, count = _redact(raw_text)
        redactions += count
        lines = text.splitlines()
        for start, end in _selected_ranges(lines):
            rendered = [f"@@ {name}:{start + 1}-{end + 1}"]
            rendered.extend(f"{number + 1}: {lines[number][:4000]}" for number in range(start, end + 1))
            block = "\n".join(rendered) + "\n"
            if sum(len(item) for item in blocks) + len(block) > max_chars:
                truncated = True
                remaining = max_chars - sum(len(item) for item in blocks)
                if remaining > 128:
                    blocks.append(block[:remaining] + "\n[TRUNCATED]\n")
                return "".join(blocks), truncated, redactions
            blocks.append(block)
    return "".join(blocks), truncated, redactions


def _validate_limits(
    entries: list[tuple[str, bytes]], compressed_bytes: int, *, max_entries: int,
    max_extracted_bytes: int, max_ratio: int,
) -> int:
    if not entries or len(entries) > max_entries:
        raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
    total = sum(len(data) for _, data in entries)
    if total > max_extracted_bytes:
        raise InvalidBoundaryError("extracted log size exceeds the permitted boundary")
    if total > max(compressed_bytes, 1) * max_ratio:
        raise InvalidBoundaryError("archive compression ratio exceeds the permitted boundary")
    return total


def _is_ignored_archive_metadata(name: str) -> bool:
    """Ignore platform metadata that is never useful as technical-support evidence."""
    parts = [part for part in name.replace("\\", "/").split("/") if part]
    if not parts:
        return False
    basename = parts[-1]
    return "__MACOSX" in parts or basename == ".DS_Store" or basename.startswith("._")


def _read_zip(data: bytes, *, max_entries: int, max_extracted_bytes: int, max_ratio: int) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = [
                item for item in archive.infolist()
                if not item.is_dir() and not _is_ignored_archive_metadata(item.filename)
            ]
            if not infos or len(infos) > max_entries:
                raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
            entries: list[tuple[str, bytes]] = []
            declared_total = 0
            for info in infos:
                name = _safe_member_name(info.filename)
                if info.flag_bits & 0x1:
                    raise InvalidBoundaryError("encrypted archives are not permitted")
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type not in {0, stat.S_IFREG}:
                    raise InvalidBoundaryError("archive links and special files are not permitted")
                declared_total += info.file_size
                if declared_total > max_extracted_bytes or declared_total > max(len(data), 1) * max_ratio:
                    raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
                member = archive.read(info)
                if len(member) != info.file_size:
                    raise InvalidBoundaryError("archive member size is inconsistent")
                entries.append((name, member))
            _validate_limits(entries, len(data), max_entries=max_entries, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio)
            return entries
    except InvalidBoundaryError:
        raise
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise InvalidBoundaryError("invalid ZIP log archive") from exc


def _read_gzip(data: bytes, filename: str, *, max_extracted_bytes: int, max_ratio: int) -> list[tuple[str, bytes]]:
    try:
        with gzip.GzipFile(fileobj=BytesIO(data)) as stream:
            content = stream.read(max_extracted_bytes + 1)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise InvalidBoundaryError("invalid GZIP log archive") from exc
    if len(content) > max_extracted_bytes or len(content) > max(len(data), 1) * max_ratio:
        raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
    name = filename[:-3] if filename.casefold().endswith(".gz") else filename + ".log"
    if not _is_log_name(name):
        raise InvalidBoundaryError("GZIP payload filename is not a supported log")
    return [(Path(name).name, content)]


def _read_tar_gz(
    data: bytes, *, max_entries: int, max_extracted_bytes: int, max_ratio: int,
) -> list[tuple[str, bytes]]:
    try:
        with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
            members = [
                item for item in archive.getmembers()
                if not item.isdir() and not _is_ignored_archive_metadata(item.name)
            ]
            if not members or len(members) > max_entries:
                raise InvalidBoundaryError("archive entry count is outside the permitted boundary")
            entries: list[tuple[str, bytes]] = []
            declared_total = 0
            for member in members:
                if not member.isfile():
                    raise InvalidBoundaryError("archive links and special files are not permitted")
                name = _safe_member_name(member.name)
                declared_total += member.size
                if declared_total > max_extracted_bytes or declared_total > max(len(data), 1) * max_ratio:
                    raise InvalidBoundaryError("archive expansion exceeds the permitted boundary")
                stream = archive.extractfile(member)
                if stream is None:
                    raise InvalidBoundaryError("archive member cannot be read")
                content = stream.read(member.size + 1)
                if len(content) != member.size:
                    raise InvalidBoundaryError("archive member size is inconsistent")
                entries.append((name, content))
            _validate_limits(entries, len(data), max_entries=max_entries, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio)
            return entries
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise InvalidBoundaryError("invalid TAR.GZ log archive") from exc


def parse_log_artifact(
    filename: str, media_type: str, data: bytes, *, max_entries: int, max_extracted_bytes: int,
    max_ratio: int, max_evidence_chars: int,
) -> LogAnalysis:
    lowered = filename.casefold()
    if media_type in PLAIN_MEDIA_TYPES:
        if not _is_log_name(filename):
            raise InvalidBoundaryError("filename is not a supported log")
        entries = [(filename, data)]
    elif media_type == "application/zip":
        if not lowered.endswith(".zip") or data[:4] not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
            raise InvalidBoundaryError("artifact bytes do not match ZIP")
        entries = _read_zip(data, max_entries=max_entries, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio)
    elif media_type in {"application/gzip", "application/x-gzip"}:
        if not lowered.endswith((".gz", ".tgz")) or data[:2] != b"\x1f\x8b":
            raise InvalidBoundaryError("artifact bytes do not match GZIP")
        if lowered.endswith((".tar.gz", ".tgz")):
            entries = _read_tar_gz(data, max_entries=max_entries, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio)
        else:
            entries = _read_gzip(data, filename, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio)
    else:
        raise InvalidBoundaryError("unsupported log artifact media type")

    extracted = _validate_limits(
        entries, len(data), max_entries=max_entries, max_extracted_bytes=max_extracted_bytes, max_ratio=max_ratio,
    )
    decoded = [(name, _decode_log(content)) for name, content in entries]
    evidence, truncated, redactions = _evidence(decoded, max_evidence_chars)
    if not evidence:
        raise InvalidBoundaryError("log artifact produced no usable evidence")
    return LogAnalysis(evidence, len(entries), extracted, truncated, redactions)
