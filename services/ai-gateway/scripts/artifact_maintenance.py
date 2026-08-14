#!/usr/bin/env python3
"""Purge expired evidence artifacts and emit disk-capacity events."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time

from app.artifacts import ArtifactStore


def _percent_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not 1 <= value <= 99:
        raise RuntimeError(f"{name} must be between 1 and 99")
    return value


def maintain_once(root: Path) -> dict[str, int | str]:
    store = ArtifactStore(
        str(root), retention_hours=int(os.getenv("TECHFLOW_ARTIFACT_RETENTION_HOURS", "24")),
        max_bytes=int(os.getenv("TECHFLOW_ARTIFACT_MAX_BYTES", str(50 * 1024 * 1024))),
        max_extracted_bytes=int(os.getenv("TECHFLOW_ARTIFACT_MAX_EXTRACTED_BYTES", str(100 * 1024 * 1024))),
        max_archive_entries=int(os.getenv("TECHFLOW_ARTIFACT_MAX_ARCHIVE_ENTRIES", "100")),
        max_compression_ratio=int(os.getenv("TECHFLOW_ARTIFACT_MAX_COMPRESSION_RATIO", "20")),
        max_log_evidence_chars=int(os.getenv("TECHFLOW_ARTIFACT_MAX_LOG_EVIDENCE_CHARS", "120000")),
    )
    removed = store.purge_expired()
    usage = shutil.disk_usage(root)
    used_percent = round(usage.used * 100 / usage.total) if usage.total else 100
    warn_percent = _percent_env("TECHFLOW_ARTIFACT_DISK_WARN_PERCENT", 70)
    critical_percent = _percent_env("TECHFLOW_ARTIFACT_DISK_CRITICAL_PERCENT", 85)
    if warn_percent >= critical_percent:
        raise RuntimeError("artifact disk warning threshold must be lower than critical threshold")
    level = "critical" if used_percent >= critical_percent else ("warning" if used_percent >= warn_percent else "ok")
    return {
        "event": "artifact_maintenance_completed", "level": level, "removed": removed,
        "usedPercent": used_percent, "freeBytes": usage.free,
    }


def main() -> int:
    root = Path(os.getenv("TECHFLOW_ARTIFACT_ROOT", "/var/lib/techflow-artifacts"))
    interval = max(60, int(os.getenv("TECHFLOW_ARTIFACT_MAINTENANCE_INTERVAL_SECONDS", "900")))
    once = os.getenv("TECHFLOW_ARTIFACT_MAINTENANCE_ONCE", "false").lower() == "true"
    while True:
        print(json.dumps(maintain_once(root), separators=(",", ":")), flush=True)
        if once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
