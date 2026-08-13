from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "output/issues-66-68-artifact-manifest.json"
TARGETS = [
    ROOT / "docs/plans/issues-66-68-community-conversation-design.md",
    ROOT / "docs/runbooks/community-conversation.md",
    ROOT / "docs/reports/issues-66-68-community-conversation-validation.md",
    ROOT / "output/pdf/techflow-community-conversation-report.pdf",
    ROOT / "output/pdf/techflow-community-conversation-presentation.pdf",
    ROOT / "output/presentation/techflow-community-conversation.pptx",
]


def main() -> None:
    artifacts = []
    for item in TARGETS:
        data = item.read_bytes()
        artifacts.append({
            "path": item.relative_to(ROOT).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    payload = {
        "issues": [66, 67, 68],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={OUTPUT} artifacts={len(artifacts)}")


if __name__ == "__main__":
    main()
