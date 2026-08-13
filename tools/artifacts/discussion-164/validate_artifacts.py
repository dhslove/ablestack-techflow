from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "output/pdf/techflow-community-discussion-164-recovery-report.pdf"
DECK = ROOT / "output/presentation/techflow-community-discussion-164-recovery.pptx"
DECK_PDF = ROOT / "output/pdf/techflow-community-discussion-164-recovery-presentation.pdf"
MANIFEST = ROOT / "output/discussion-164-recovery-artifact-manifest.json"


def pdf(path: Path) -> tuple[int, str]:
    with pdfplumber.open(path) as opened:
        return len(opened.pages), "\n".join((page.extract_text() or "") for page in opened.pages)


def main() -> None:
    report_pages, report_text = pdf(REPORT)
    deck_pages, _ = pdf(DECK_PDF)
    if report_pages < 4 or "Discussion #164" not in report_text or "Post #362" not in report_text:
        raise RuntimeError("report PDF contract failed")
    with zipfile.ZipFile(DECK) as archive:
        slides = len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")])
        notes = len([name for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")])
        deck_text = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
    if deck_pages != 5 or slides != 5 or notes != 5 or "Post #362" not in deck_text or "0.13.2" not in deck_text:
        raise RuntimeError(f"presentation contract failed pages={deck_pages} slides={slides} notes={notes}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("discussion") != 164 or manifest.get("issue") != 67 or len(manifest.get("artifacts") or []) != 5:
        raise RuntimeError("manifest contract failed")
    print(f"artifacts=valid reportPages={report_pages} slides={slides} notes={notes}")


if __name__ == "__main__":
    main()
