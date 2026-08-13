from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "output/pdf/techflow-community-conversation-report.pdf"
DECK = ROOT / "output/presentation/techflow-community-conversation.pptx"
DECK_PDF = ROOT / "output/pdf/techflow-community-conversation-presentation.pdf"
MANIFEST = ROOT / "output/issues-66-68-artifact-manifest.json"


def pdf(path: Path) -> tuple[int, str]:
    with pdfplumber.open(path) as opened:
        return len(opened.pages), "\n".join((page.extract_text() or "") for page in opened.pages)


def main() -> None:
    report_pages, report_text = pdf(REPORT)
    deck_pages, _ = pdf(DECK_PDF)
    if report_pages < 4 or "Discussion #163" not in report_text or "ABLESTACK Diplo" not in report_text:
        raise RuntimeError("report PDF contract failed")
    with zipfile.ZipFile(DECK) as archive:
        slides = len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")])
        notes = len([name for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")])
        deck_text = "\n".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    # 발표자료 PDF는 슬라이드 렌더 이미지를 묶은 파일이므로 텍스트 계약은
    # 원본 PPTX XML에서, PDF 계약은 페이지 수로 각각 검증한다.
    if deck_pages != 7 or "RESOLVED" not in deck_text or "196" not in deck_text:
        raise RuntimeError("presentation contract failed")
    if slides != 7 or notes != 7:
        raise RuntimeError(f"PPTX contract failed slides={slides} notes={notes}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("issues") != [66, 67, 68] or len(manifest.get("artifacts") or []) != 6:
        raise RuntimeError("manifest contract failed")
    print(f"artifacts=valid reportPages={report_pages} slides={slides} notes={notes}")


if __name__ == "__main__":
    main()
