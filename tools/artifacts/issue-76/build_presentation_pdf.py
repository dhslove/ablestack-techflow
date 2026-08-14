from pathlib import Path
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[3]
RENDERS = ROOT / "tmp/artifacts/issue-76/qa/renders"
OUTPUT = ROOT / "output/pdf/techflow-guest-os-official-platform-evidence-presentation.pdf"


def main() -> None:
    images = sorted(RENDERS.glob("slide-*.png"))
    if not images: raise RuntimeError("presentation renders are missing")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=(1280, 720))
    for item in images:
        pdf.drawImage(ImageReader(str(item)), 0, 0, width=1280, height=720); pdf.showPage()
    pdf.save(); print(f"presentation_pdf={OUTPUT} pages={len(images)}")


if __name__ == "__main__": main()
