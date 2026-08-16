#!/usr/bin/env python3
"""Idempotently align an existing runtime .env with the Issue #72 upload limits."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


VALUES = {
    "TECHFLOW_RAG_RELEASE": "issue-72-large-uploads-1g10g",
    "TECHFLOW_ARTIFACT_MAX_BYTES": "1073741824",
    "TECHFLOW_ARTIFACT_MAX_ARCHIVE_BYTES": "10737418240",
    "TECHFLOW_ARTIFACT_MAX_EXTRACTED_BYTES": "107374182400",
    "TECHFLOW_COMMUNITY_ATTACHMENT_MAX_BYTES": "1073741824",
    "TECHFLOW_COMMUNITY_ARCHIVE_MAX_BYTES": "10737418240",
    "TECHFLOW_COMMUNITY_ATTACHMENT_TIMEOUT_SECONDS": "7200",
    "TECHFLOW_COMMUNITY_ATTACHMENT_RETRIES": "2",
}


def update(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in VALUES:
            output.append(f"{key}={VALUES[key]}")
            seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in VALUES.items() if key not in seen)
    temporary = path.with_name(path.name + ".issue72.tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise SystemExit("runtime env file does not exist")
    update(args.env_file)
    print("issue72_large_upload_limits=updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
