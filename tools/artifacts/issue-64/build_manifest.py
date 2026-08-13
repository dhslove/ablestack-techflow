from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "output/issue-64-artifact-manifest.json"
TARGETS = [
    ROOT / "docs/plans/issue-64-answer-clarity-community-review-design.md",
    ROOT / "docs/runbooks/community-ai-review-post.md",
    ROOT / "docs/reports/issue-64-answer-clarity-validation.md",
    ROOT / "output/pdf/techflow-issue-64-answer-clarity-report.pdf",
    ROOT / "output/pdf/techflow-issue-64-answer-clarity-presentation.pdf",
    ROOT / "output/presentation/techflow-issue-64-answer-clarity.pptx",
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
        "issue": 64,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={OUTPUT} artifacts={len(artifacts)}")


if __name__ == "__main__":
    main()
