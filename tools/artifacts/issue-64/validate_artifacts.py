from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "output/pdf/techflow-issue-64-answer-clarity-report.pdf"
DECK = ROOT / "output/presentation/techflow-issue-64-answer-clarity.pptx"
DECK_PDF = ROOT / "output/pdf/techflow-issue-64-answer-clarity-presentation.pdf"
MANIFEST = ROOT / "output/issue-64-artifact-manifest.json"


def pdf_pages(path: Path) -> tuple[int, str]:
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages), "\n".join((page.extract_text() or "") for page in pdf.pages)


def main() -> None:
    report_pages, report_text = pdf_pages(REPORT)
    deck_pages, _ = pdf_pages(DECK_PDF)
    if report_pages < 4 or "Issue #64" not in report_text or "186 passed" not in report_text:
        raise RuntimeError("report PDF contract failed")
    if deck_pages != 8:
        raise RuntimeError(f"presentation PDF page count is {deck_pages}, expected 8")
    with zipfile.ZipFile(DECK) as archive:
        slide_count = len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")])
        notes_count = len([name for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")])
    if slide_count != 8 or notes_count != 8:
        raise RuntimeError(f"PPTX contract failed slides={slide_count} notes={notes_count}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("issue") != 64 or len(manifest.get("artifacts") or []) != 6:
        raise RuntimeError("manifest contract failed")
    print(f"artifacts=valid reportPages={report_pages} slides={slide_count} notes={notes_count}")


if __name__ == "__main__":
    main()
