from __future__ import annotations

from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/reports/issue-64-answer-clarity-validation.md"
OUTPUT = ROOT / "output/pdf/techflow-issue-64-answer-clarity-report.pdf"
FONT = Path("C:/Windows/Fonts/malgun.ttf")
BOLD_FONT = Path("C:/Windows/Fonts/malgunbd.ttf")


def register_fonts() -> tuple[str, str]:
    regular, bold = "Helvetica", "Helvetica-Bold"
    if FONT.exists():
        pdfmetrics.registerFont(TTFont("Malgun64", str(FONT)))
        regular = "Malgun64"
    if BOLD_FONT.exists():
        pdfmetrics.registerFont(TTFont("Malgun64-Bold", str(BOLD_FONT)))
        bold = "Malgun64-Bold"
    return regular, bold


REGULAR, BOLD = register_fonts()


def inline(value: str) -> str:
    value = escape(value)
    value = re.sub(r"`([^`]+)`", r"<font name='Malgun64-Bold'>\1</font>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<link href='\2' color='#2563EB'>\1</link>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<font name='Malgun64-Bold'>\1</font>", value)
    return value


def page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(REGULAR, 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18 * mm, 10 * mm, "ABLESTACK TechFlow · Issue #64")
    canvas.drawRightString(192 * mm, 10 * mm, str(doc.page))
    canvas.restoreState()


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title64", parent=base["Title"], fontName=BOLD, fontSize=22, leading=30, textColor=colors.HexColor("#0F172A"), spaceAfter=9 * mm),
        "h1": ParagraphStyle("H164", parent=base["Heading1"], fontName=BOLD, fontSize=16, leading=22, textColor=colors.HexColor("#1D4ED8"), spaceBefore=6 * mm, spaceAfter=3 * mm),
        "h2": ParagraphStyle("H264", parent=base["Heading2"], fontName=BOLD, fontSize=12.5, leading=18, textColor=colors.HexColor("#0F172A"), spaceBefore=4 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("Body64", parent=base["BodyText"], fontName=REGULAR, fontSize=9.1, leading=14.6, textColor=colors.HexColor("#1E293B"), spaceAfter=2 * mm),
        "bullet": ParagraphStyle("Bullet64", parent=base["BodyText"], fontName=REGULAR, fontSize=8.9, leading=14, leftIndent=6 * mm, firstLineIndent=-3.5 * mm, textColor=colors.HexColor("#1E293B"), spaceAfter=1.2 * mm),
        "quote": ParagraphStyle("Quote64", parent=base["BodyText"], fontName=REGULAR, fontSize=8.8, leading=14, leftIndent=5 * mm, rightIndent=4 * mm, borderColor=colors.HexColor("#60A5FA"), borderWidth=1, borderPadding=5, backColor=colors.HexColor("#EFF6FF"), spaceAfter=2 * mm),
        "code": ParagraphStyle("Code64", parent=base["Code"], fontName=REGULAR, fontSize=7.6, leading=11, backColor=colors.HexColor("#F1F5F9"), borderPadding=5, spaceAfter=2 * mm),
    }


def make_table(lines: list[str], body_style: ParagraphStyle) -> Table:
    header_style = ParagraphStyle("TableHeader64", parent=body_style, fontName=BOLD, textColor=colors.white)
    raw_rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [[Paragraph(inline(cell), header_style if index == 0 else body_style) for cell in row] for index, row in enumerate(raw_rows)]
    if len(rows) > 1:
        rows.pop(1)
    width = 174 * mm
    table = Table(rows, colWidths=[width / len(rows[0])] * len(rows[0]), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    return table


def build_story() -> list:
    styles = make_styles()
    story: list = []
    paragraph: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), styles["body"]))
            paragraph.clear()

    def flush_table() -> None:
        if table_lines:
            story.append(make_table(table_lines, styles["body"]))
            story.append(Spacer(1, 2 * mm))
            table_lines.clear()

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush_paragraph(); flush_table()
            if in_code:
                story.append(Paragraph(escape("\n".join(code_lines)).replace("\n", "<br/>"), styles["code"]))
                code_lines.clear()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|"):
            flush_paragraph(); table_lines.append(line); continue
        flush_table()
        if not line:
            flush_paragraph(); continue
        if line.startswith("# "):
            flush_paragraph(); story.append(Paragraph(inline(line[2:]), styles["title"])); continue
        if line.startswith("## "):
            flush_paragraph(); story.append(Paragraph(inline(line[3:]), styles["h1"])); continue
        if line.startswith("### "):
            flush_paragraph(); story.append(Paragraph(inline(line[4:]), styles["h2"])); continue
        if re.match(r"^[-*] ", line):
            flush_paragraph(); story.append(Paragraph("• " + inline(line[2:]), styles["bullet"])); continue
        if re.match(r"^\d+\. ", line):
            flush_paragraph(); story.append(Paragraph(inline(line), styles["bullet"])); continue
        if line.startswith(">"):
            flush_paragraph(); story.append(Paragraph(inline(line.lstrip("> ")), styles["quote"])); continue
        paragraph.append(line)
    flush_paragraph(); flush_table()
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title="TechFlow Issue #64 Community 원문 승인형 AI 답변 완료 보고서",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page)])
    doc.build(build_story())
    print(f"report={OUTPUT}")


if __name__ == "__main__":
    main()
