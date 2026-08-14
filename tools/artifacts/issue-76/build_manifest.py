from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "output/issue-76-guest-os-official-platform-evidence-manifest.json"
FILES = [
    ROOT / "docs/reports/issue-76-guest-os-official-platform-evidence-validation.md",
    ROOT / "output/pdf/techflow-guest-os-official-platform-evidence-report.pdf",
    ROOT / "output/presentation/techflow-guest-os-official-platform-evidence.pptx",
    ROOT / "output/pdf/techflow-guest-os-official-platform-evidence-presentation.pdf",
]


def main() -> None:
    artifacts = []
    for item in FILES:
        payload = item.read_bytes()
        artifacts.append({"path": item.relative_to(ROOT).as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    OUTPUT.write_text(json.dumps({"issue": 76, "generatedAt": datetime.now(timezone.utc).isoformat(), "artifacts": artifacts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={OUTPUT} artifacts={len(artifacts)}")


if __name__ == "__main__": main()
