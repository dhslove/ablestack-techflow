"""Short-lived D0 evidence artifact storage with strict format validation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
from threading import RLock
from typing import AsyncIterable, Iterable
from uuid import UUID, uuid4

from .log_artifacts import ARCHIVE_MEDIA_TYPES, PLAIN_MEDIA_TYPES, parse_log_artifact_path
from .provider import EvidenceArtifact, ImageArtifact, LogArtifact
from .store import InvalidBoundaryError, NotFoundError


IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_MEDIA_TYPES = IMAGE_MEDIA_TYPES | PLAIN_MEDIA_TYPES | ARCHIVE_MEDIA_TYPES
MEDIA_TYPE_ALIASES = {"application/x-zip-compressed", "application/octet-stream"}


def _normalized_media_type(filename: str, media_type: str, header: bytes) -> str:
    if media_type == "application/x-zip-compressed":
        return "application/zip"
    if media_type == "application/octet-stream":
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if header[:2] == b"\xff\xd8":
            return "image/jpeg"
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return "image/webp"
        if header[:4] in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"} and filename.casefold().endswith(".zip"):
            return "application/zip"
        if header[:2] == b"\x1f\x8b" and filename.casefold().endswith((".gz", ".tgz")):
            return "application/gzip"
        return "text/plain"
    return media_type


def _dimensions(data: bytes, media_type: str) -> tuple[int, int]:
    if media_type == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if media_type == "image/jpeg" and data[:2] == b"\xff\xd8":
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return struct.unpack(">HH", data[offset + 5:offset + 9])[::-1]
            if offset + 4 > len(data):
                break
            size = struct.unpack(">H", data[offset + 2:offset + 4])[0]
            offset += max(2, size + 2)
    if media_type == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return (int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF)
    raise InvalidBoundaryError("artifact bytes do not match the declared media type")


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: UUID
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    kind: str
    width: int | None
    height: int | None
    entry_count: int | None
    extracted_bytes: int | None
    evidence_truncated: bool
    redaction_count: int
    created_at: datetime
    expires_at: datetime

    def payload(self) -> dict[str, object]:
        return {
            "artifactId": self.artifact_id, "filename": self.filename, "mediaType": self.media_type,
            "sha256": self.sha256, "sizeBytes": self.size_bytes, "kind": self.kind,
            "width": self.width, "height": self.height, "entryCount": self.entry_count,
            "extractedBytes": self.extracted_bytes, "evidenceTruncated": self.evidence_truncated,
            "redactionCount": self.redaction_count,
            "classification": "D0", "createdAt": self.created_at, "expiresAt": self.expires_at,
        }


class ArtifactStore:
    def __init__(
        self, root: str, *, retention_hours: int, max_bytes: int,
        max_archive_bytes: int = 10 * 1024 * 1024 * 1024,
        max_extracted_bytes: int = 20 * 1024 * 1024, max_archive_entries: int = 100,
        max_compression_ratio: int = 20, max_log_evidence_chars: int = 120_000,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self.retention = timedelta(hours=retention_hours)
        self.max_bytes = max_bytes
        self.max_archive_bytes = max_archive_bytes
        self.max_extracted_bytes = max_extracted_bytes
        self.max_archive_entries = max_archive_entries
        self.max_compression_ratio = max_compression_ratio
        self.max_log_evidence_chars = max_log_evidence_chars
        self._lock = RLock()

    def _paths(self, artifact_id: UUID) -> tuple[Path, Path, Path]:
        base = self.root / str(artifact_id)
        return base.with_suffix(".bin"), base.with_suffix(".json"), base.with_suffix(".evidence")

    def _safe_name(self, filename: str) -> str:
        safe_name = Path(filename).name[:128]
        if not safe_name or safe_name != filename or "/" in filename or "\\" in filename:
            raise InvalidBoundaryError("artifact filename is invalid")
        return safe_name

    def _hint_limit(self, filename: str, media_type: str) -> int:
        if media_type not in ALLOWED_MEDIA_TYPES | MEDIA_TYPE_ALIASES:
            raise InvalidBoundaryError("unsupported evidence artifact media type")
        lowered = filename.casefold()
        if media_type in ARCHIVE_MEDIA_TYPES | {"application/x-zip-compressed"} or lowered.endswith((".zip", ".gz", ".tgz", ".tar.gz")):
            return self.max_archive_bytes
        return self.max_bytes

    @staticmethod
    def _hash_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _finalize(self, temporary: Path, filename: str, media_type: str, size_bytes: int, sha256: str) -> ArtifactRecord:
        if media_type not in ALLOWED_MEDIA_TYPES | MEDIA_TYPE_ALIASES:
            raise InvalidBoundaryError("unsupported evidence artifact media type")
        safe_name = self._safe_name(filename)
        if not size_bytes:
            raise InvalidBoundaryError("artifact size is outside the permitted boundary")
        with temporary.open("rb") as source:
            header = source.read(1024 * 1024)
        media_type = _normalized_media_type(safe_name, media_type, header)
        effective_max = self.max_archive_bytes if media_type in ARCHIVE_MEDIA_TYPES else self.max_bytes
        if size_bytes > effective_max:
            raise InvalidBoundaryError("artifact size is outside the permitted boundary")
        width = height = entry_count = extracted_bytes = None
        evidence_truncated = False
        redaction_count = 0
        evidence_text: str | None = None
        if media_type in IMAGE_MEDIA_TYPES:
            kind = "IMAGE"
            width, height = _dimensions(header, media_type)
            if width < 1 or height < 1 or width > 12000 or height > 12000 or width * height > 40_000_000:
                raise InvalidBoundaryError("artifact dimensions exceed the permitted boundary")
        else:
            kind = "LOG"
            analysis = parse_log_artifact_path(
                safe_name, media_type, temporary, max_entries=self.max_archive_entries,
                max_extracted_bytes=self.max_extracted_bytes, max_ratio=self.max_compression_ratio,
                max_evidence_chars=self.max_log_evidence_chars,
            )
            entry_count, extracted_bytes = analysis.entry_count, analysis.extracted_bytes
            evidence_truncated, redaction_count = analysis.truncated, analysis.redaction_count
            evidence_text = analysis.evidence_text
        now, artifact_id = datetime.now(timezone.utc), uuid4()
        record = ArtifactRecord(
            artifact_id, safe_name, media_type, sha256, size_bytes, kind,
            width, height, entry_count, extracted_bytes, evidence_truncated, redaction_count,
            now, now + self.retention,
        )
        binary, metadata, evidence = self._paths(artifact_id)
        payload = record.payload()
        if evidence_text is not None:
            payload["evidenceSha256"] = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
        with self._lock:
            os.replace(temporary, binary)
            if evidence_text is not None:
                evidence.write_text(evidence_text, encoding="utf-8")
            metadata.write_text(json.dumps(payload, default=str, separators=(",", ":")), encoding="utf-8")
            try:
                os.chmod(binary, 0o600); os.chmod(metadata, 0o600)
                if evidence_text is not None:
                    os.chmod(evidence, 0o600)
            except OSError:
                pass
        return record

    def _put_chunks(self, filename: str, media_type: str, chunks: Iterable[bytes]) -> ArtifactRecord:
        safe_name = self._safe_name(filename)
        hinted_max = self._hint_limit(safe_name, media_type)
        temporary = self.root / f".upload-{uuid4().hex}.part"
        digest, total = hashlib.sha256(), 0
        try:
            with temporary.open("xb") as target:
                for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > hinted_max:
                        raise InvalidBoundaryError("artifact size is outside the permitted boundary")
                    digest.update(chunk)
                    target.write(chunk)
            return self._finalize(temporary, safe_name, media_type, total, digest.hexdigest())
        finally:
            temporary.unlink(missing_ok=True)

    def put(self, filename: str, media_type: str, data: bytes) -> ArtifactRecord:
        return self._put_chunks(filename, media_type, (data,))

    def put_path(self, filename: str, media_type: str, path: Path) -> ArtifactRecord:
        """Consume a previously streamed private file without loading it into memory."""
        safe_name = self._safe_name(filename)
        hinted_max = self._hint_limit(safe_name, media_type)
        size_bytes = path.stat().st_size
        if size_bytes < 1 or size_bytes > hinted_max:
            raise InvalidBoundaryError("artifact size is outside the permitted boundary")
        return self._finalize(path, safe_name, media_type, size_bytes, self._hash_path(path))

    async def put_stream(
        self, filename: str, media_type: str, chunks: AsyncIterable[bytes], *, content_length: int | None = None,
    ) -> ArtifactRecord:
        safe_name = self._safe_name(filename)
        hinted_max = self._hint_limit(safe_name, media_type)
        if content_length is not None and (content_length < 1 or content_length > hinted_max):
            raise InvalidBoundaryError("artifact size is outside the permitted boundary")
        temporary = self.root / f".upload-{uuid4().hex}.part"
        digest, total = hashlib.sha256(), 0
        try:
            with temporary.open("xb") as target:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > hinted_max:
                        raise InvalidBoundaryError("artifact size is outside the permitted boundary")
                    digest.update(chunk)
                    target.write(chunk)
            return await asyncio.to_thread(
                self._finalize, temporary, safe_name, media_type, total, digest.hexdigest()
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self, artifact_id: UUID) -> ArtifactRecord:
        binary, metadata, _ = self._paths(artifact_id)
        if not binary.exists() or not metadata.exists():
            raise NotFoundError("artifact not found")
        raw = json.loads(metadata.read_text(encoding="utf-8"))
        record = ArtifactRecord(
            UUID(raw["artifactId"]), raw["filename"], raw["mediaType"], raw["sha256"], int(raw["sizeBytes"]),
            raw.get("kind", "IMAGE"), int(raw["width"]) if raw.get("width") is not None else None,
            int(raw["height"]) if raw.get("height") is not None else None,
            int(raw["entryCount"]) if raw.get("entryCount") is not None else None,
            int(raw["extractedBytes"]) if raw.get("extractedBytes") is not None else None,
            bool(raw.get("evidenceTruncated", False)), int(raw.get("redactionCount", 0)),
            datetime.fromisoformat(raw["createdAt"]), datetime.fromisoformat(raw["expiresAt"]),
        )
        if record.expires_at <= datetime.now(timezone.utc):
            self.delete(artifact_id)
            raise NotFoundError("artifact expired")
        return record

    def get(self, artifact_id: UUID) -> ArtifactRecord:
        with self._lock:
            return self._load(artifact_id)

    def image(self, artifact_id: UUID) -> ImageArtifact:
        artifact = self.evidence(artifact_id)
        if not isinstance(artifact, ImageArtifact):
            raise InvalidBoundaryError("artifact is not an image")
        return artifact

    def evidence(self, artifact_id: UUID) -> EvidenceArtifact:
        with self._lock:
            record = self._load(artifact_id)
            binary, metadata, evidence = self._paths(artifact_id)
            if record.kind == "IMAGE":
                if self._hash_path(binary) != record.sha256:
                    raise InvalidBoundaryError("artifact integrity validation failed")
                data = binary.read_bytes()
                return ImageArtifact(str(artifact_id), record.media_type, data, record.sha256)
            raw = json.loads(metadata.read_text(encoding="utf-8"))
            if evidence.exists() and raw.get("evidenceSha256"):
                evidence_text = evidence.read_text(encoding="utf-8")
                if hashlib.sha256(evidence_text.encode("utf-8")).hexdigest() != raw["evidenceSha256"]:
                    raise InvalidBoundaryError("artifact normalization integrity validation failed")
            else:
                analysis = parse_log_artifact_path(
                    record.filename, record.media_type, binary, max_entries=self.max_archive_entries,
                    max_extracted_bytes=self.max_extracted_bytes, max_ratio=self.max_compression_ratio,
                    max_evidence_chars=self.max_log_evidence_chars,
                )
                if (
                    analysis.entry_count != record.entry_count or analysis.extracted_bytes != record.extracted_bytes
                    or analysis.redaction_count != record.redaction_count
                ):
                    raise InvalidBoundaryError("artifact normalization integrity validation failed")
                evidence_text = analysis.evidence_text
            return LogArtifact(
                str(artifact_id), record.media_type, record.sha256, evidence_text,
                record.entry_count or 0, record.extracted_bytes or 0, record.evidence_truncated, record.redaction_count,
            )

    def delete(self, artifact_id: UUID) -> bool:
        binary, metadata, evidence = self._paths(artifact_id)
        existed = binary.exists() or metadata.exists() or evidence.exists()
        with self._lock:
            binary.unlink(missing_ok=True); metadata.unlink(missing_ok=True); evidence.unlink(missing_ok=True)
        return existed

    def purge_expired(self) -> int:
        removed = 0
        for metadata in self.root.glob("*.json"):
            try:
                artifact_id = UUID(metadata.stem)
                self._load(artifact_id)
            except NotFoundError:
                removed += 1
            except (ValueError, OSError, json.JSONDecodeError):
                continue
        return removed
