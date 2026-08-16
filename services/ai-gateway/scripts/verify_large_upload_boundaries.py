#!/usr/bin/env python3
"""Generate and upload exact Issue #72 boundary artifacts without loading them into memory."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid
import zipfile


MIB = 1024 * 1024
GIB = 1024 * MIB
REGULAR_LIMIT = 1 * GIB
ARCHIVE_LIMIT = 10 * GIB
CHUNK_BYTES = 4 * MIB
LOG_PREFIX = b"2026-08-16T00:00:00Z INFO TechFlow boundary validation completed normally "
LOG_LINE = LOG_PREFIX + (b"x" * (4095 - len(LOG_PREFIX))) + b"\n"


def _write_log_bytes(target, size: int, digest=None) -> None:
    block = (LOG_LINE * ((CHUNK_BYTES // len(LOG_LINE)) + 1))[:CHUNK_BYTES]
    remaining = size
    while remaining:
        chunk = block[: min(len(block), remaining)]
        target.write(chunk)
        if digest is not None:
            digest.update(chunk)
        remaining -= len(chunk)


def create_exact_log(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("wb") as target:
        _write_log_bytes(target, REGULAR_LIMIT, digest)
    return {"path": str(path), "sizeBytes": path.stat().st_size, "sha256": digest.hexdigest()}


def create_exact_zip(path: Path) -> dict[str, object]:
    # Leave room for the central directory and then pad the EOCD comment to the exact 10 GiB boundary.
    member_size = ARCHIVE_LIMIT - 65_023
    info = zipfile.ZipInfo("support.log")
    info.compress_type = zipfile.ZIP_STORED
    info.file_size = member_size
    with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
        with archive.open(info, "w", force_zip64=True) as target:
            _write_log_bytes(target, member_size)
    base_size = path.stat().st_size
    padding = ARCHIVE_LIMIT - base_size
    if not 0 <= padding <= 65_535:
        raise RuntimeError(f"ZIP boundary padding is invalid: base={base_size}, padding={padding}")
    with zipfile.ZipFile(path, "a", allowZip64=True) as archive:
        archive.comment = b"T" * padding
    if path.stat().st_size != ARCHIVE_LIMIT:
        raise RuntimeError(f"ZIP boundary size mismatch: {path.stat().st_size}")
    with zipfile.ZipFile(path, "r", allowZip64=True) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
        extracted = archive.getinfo("support.log").file_size
    return {"path": str(path), "sizeBytes": path.stat().st_size, "entryBytes": extracted}


def _connection(base_url: str, timeout: int):
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be http(s)")
    klass = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return klass(parsed.hostname, port, timeout=timeout), parsed.path.rstrip("/")


def upload(base_url: str, path: Path, filename: str, media_type: str, timeout: int) -> dict[str, object]:
    connection, prefix = _connection(base_url, timeout)
    started = time.monotonic()
    connection.putrequest("POST", f"{prefix}/v1/artifacts")
    connection.putheader("Content-Type", media_type)
    connection.putheader("Content-Length", str(path.stat().st_size))
    connection.putheader("X-Artifact-Filename", filename)
    connection.putheader("X-Artifact-Classification", "D0")
    connection.putheader("X-Correlation-Id", f"issue72-upload-{uuid.uuid4().hex}")
    connection.endheaders()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            connection.send(chunk)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    elapsed = round(time.monotonic() - started, 3)
    if response.status != 201:
        raise RuntimeError(f"upload failed: status={response.status}, payload={payload[:500]}")
    artifact_id = json.loads(payload)["data"]["artifactId"]
    connection.close()
    return {"status": response.status, "artifactId": artifact_id, "elapsedSeconds": elapsed}


def preflight_rejection(base_url: str, filename: str, media_type: str, size: int, timeout: int) -> dict[str, object]:
    connection, prefix = _connection(base_url, timeout)
    connection.putrequest("POST", f"{prefix}/v1/artifacts")
    connection.putheader("Content-Type", media_type)
    connection.putheader("Content-Length", str(size))
    connection.putheader("X-Artifact-Filename", filename)
    connection.putheader("X-Artifact-Classification", "D0")
    connection.putheader("X-Correlation-Id", f"issue72-preflight-{uuid.uuid4().hex}")
    connection.endheaders()
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    connection.close()
    if response.status != 400:
        raise RuntimeError(f"oversize preflight was not rejected: status={response.status}, payload={payload[:500]}")
    return {"status": response.status, "declaredBytes": size}


def delete(base_url: str, artifact_id: str, timeout: int) -> dict[str, object]:
    connection, prefix = _connection(base_url, timeout)
    headers = {
        "Idempotency-Key": f"issue72-delete-{uuid.uuid4().hex}",
        "X-Correlation-Id": f"issue72-delete-{uuid.uuid4().hex}",
    }
    connection.request("DELETE", f"{prefix}/v1/artifacts/{artifact_id}", headers=headers)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    connection.close()
    if response.status != 200:
        raise RuntimeError(f"delete failed: status={response.status}, payload={payload[:500]}")
    return {"status": response.status, "artifactId": artifact_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--keep-files", action="store_true")
    parser.add_argument("--reuse-files", action="store_true")
    args = parser.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    log_path = args.workdir / "issue72-exact-1g.log"
    zip_path = args.workdir / "issue72-exact-10g.zip"
    results: dict[str, object] = {"limits": {"regularBytes": REGULAR_LIMIT, "archiveBytes": ARCHIVE_LIMIT}}
    artifact_ids: list[str] = []
    try:
        if args.reuse_files:
            if log_path.stat().st_size != REGULAR_LIMIT or zip_path.stat().st_size != ARCHIVE_LIMIT:
                raise RuntimeError("reused boundary files do not have the exact required sizes")
            with zipfile.ZipFile(zip_path, "r", allowZip64=True) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError("reused ZIP boundary file failed integrity validation")
            results["generatedRegular"] = {"path": str(log_path), "sizeBytes": log_path.stat().st_size}
            results["generatedArchive"] = {"path": str(zip_path), "sizeBytes": zip_path.stat().st_size}
        else:
            results["generatedRegular"] = create_exact_log(log_path)
            results["generatedArchive"] = create_exact_zip(zip_path)
        regular = upload(args.base_url, log_path, log_path.name, "text/plain", args.timeout)
        artifact_ids.append(str(regular["artifactId"]))
        results["regularBoundary"] = regular
        archive = upload(args.base_url, zip_path, zip_path.name, "application/zip", args.timeout)
        artifact_ids.append(str(archive["artifactId"]))
        results["archiveBoundary"] = archive
        results["regularOverBoundary"] = preflight_rejection(
            args.base_url, "issue72-over-1g.log", "text/plain", REGULAR_LIMIT + 1, args.timeout
        )
        results["archiveOverBoundary"] = preflight_rejection(
            args.base_url, "issue72-over-10g.zip", "application/zip", ARCHIVE_LIMIT + 1, args.timeout
        )
    finally:
        results["cleanup"] = [delete(args.base_url, artifact_id, args.timeout) for artifact_id in artifact_ids]
        if not args.keep_files:
            log_path.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)
    results["result"] = "PASS"
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
