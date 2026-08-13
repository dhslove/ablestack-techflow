from __future__ import annotations
import json, zipfile
from pathlib import Path
import pdfplumber

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "output/pdf/techflow-community-auto-publish-kb-report.pdf"
DECK = ROOT / "output/presentation/techflow-community-auto-publish-kb.pptx"
DECK_PDF = ROOT / "output/pdf/techflow-community-auto-publish-kb-presentation.pdf"
MANIFEST = ROOT / "output/issue-69-community-auto-publish-kb-artifact-manifest.json"


def pdf(path: Path) -> tuple[int, str]:
    with pdfplumber.open(path) as opened: return len(opened.pages), "\n".join((page.extract_text() or "") for page in opened.pages)


def main() -> None:
    report_pages, report_text = pdf(REPORT); deck_pages, _ = pdf(DECK_PDF)
    if report_pages < 4 or "Issue #69" not in report_text or "Post #368" not in report_text: raise RuntimeError("report PDF contract failed")
    with zipfile.ZipFile(DECK) as archive:
        slides = len([n for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")])
        notes = len([n for n in archive.namelist() if n.startswith("ppt/notesSlides/notesSlide") and n.endswith(".xml")])
        deck_text = "\n".join(archive.read(n).decode("utf-8", errors="replace") for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
    if deck_pages != 5 or slides != 5 or notes != 5 or "Post #368" not in deck_text or "0.14.1" not in deck_text: raise RuntimeError(f"presentation contract failed pages={deck_pages} slides={slides} notes={notes}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("issue") != 69 or len(manifest.get("artifacts") or []) != 4: raise RuntimeError("manifest contract failed")
    print(f"artifacts=valid reportPages={report_pages} slides={slides} notes={notes}")


if __name__ == "__main__": main()
