from __future__ import annotations

from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, CondPageBreak, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/guides/community-automation-user-guide.md"
OUTPUT = ROOT / "output/pdf/techflow-community-automation-user-guide.pdf"
FONT_PATH = Path("C:/Windows/Fonts/malgun.ttf")
BOLD_PATH = Path("C:/Windows/Fonts/malgunbd.ttf")


def register_fonts() -> tuple[str, str]:
    regular, bold = "Helvetica", "Helvetica-Bold"
    if FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("Malgun", str(FONT_PATH)))
        regular = "Malgun"
    if BOLD_PATH.exists():
        pdfmetrics.registerFont(TTFont("Malgun-Bold", str(BOLD_PATH)))
        bold = "Malgun-Bold"
    return regular, bold


REGULAR, BOLD = register_fonts()


def inline(text: str) -> str:
    value = escape(text)
    value = re.sub(r"`([^`]+)`", r"<font name='Malgun-Bold' color='#1D4ED8'>\1</font>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<link href='\2' color='#2563EB'>\1</link>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    return value


def page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D1D5DB"))
    canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont(REGULAR, 8)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.drawString(18 * mm, 9 * mm, "ABLESTACK TechFlow | Community 자동화 사용자 가이드")
    canvas.drawRightString(192 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleKR", parent=base["Title"], fontName=BOLD, fontSize=22, leading=31,
            alignment=TA_CENTER, textColor=colors.HexColor("#0F172A"), spaceAfter=9 * mm,
        ),
        "h1": ParagraphStyle(
            "H1KR", parent=base["Heading1"], fontName=BOLD, fontSize=15, leading=22,
            textColor=colors.HexColor("#1D4ED8"), spaceBefore=7 * mm, spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2KR", parent=base["Heading2"], fontName=BOLD, fontSize=11.5, leading=17,
            textColor=colors.HexColor("#0F172A"), spaceBefore=5 * mm, spaceAfter=3 * mm,
        ),
        "body": ParagraphStyle(
            "BodyKR", parent=base["BodyText"], fontName=REGULAR, fontSize=9.2, leading=15,
            textColor=colors.HexColor("#1F2937"), spaceAfter=2.2 * mm, wordWrap="CJK",
            allowWidows=0, allowOrphans=0,
        ),
        "bullet": ParagraphStyle(
            "BulletKR", parent=base["BodyText"], fontName=REGULAR, fontSize=9.1, leading=14.5,
            leftIndent=6 * mm, firstLineIndent=-3.5 * mm, spaceAfter=1.4 * mm, wordWrap="CJK",
        ),
        "quote": ParagraphStyle(
            "QuoteKR", parent=base["BodyText"], fontName=REGULAR, fontSize=9, leading=15,
            leftIndent=5 * mm, rightIndent=3 * mm, borderColor=colors.HexColor("#60A5FA"),
            borderWidth=1, borderPadding=7, backColor=colors.HexColor("#EFF6FF"),
            textColor=colors.HexColor("#1E3A8A"), spaceAfter=3 * mm, wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "CodeKR", parent=base["Code"], fontName=REGULAR, fontSize=8.2, leading=12,
            leftIndent=3 * mm, rightIndent=3 * mm, borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.5, borderPadding=7, backColor=colors.HexColor("#F8FAFC"),
            textColor=colors.HexColor("#0F172A"), spaceAfter=3 * mm, wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "TableKR", parent=base["BodyText"], fontName=REGULAR, fontSize=8.1, leading=12,
            textColor=colors.HexColor("#1F2937"), wordWrap="CJK",
        ),
    }


def table_from(lines: list[str], style: ParagraphStyle) -> Table:
    rows = [[Paragraph(inline(cell.strip()), style) for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(rows) > 1:
        rows.pop(1)
    width = 174 * mm
    columns = len(rows[0])
    if columns == 2:
        widths = [54 * mm, 120 * mm]
    elif columns == 3:
        widths = [40 * mm, 76 * mm, 58 * mm]
    else:
        widths = [width / columns] * columns
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), REGULAR),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
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
    s = styles()
    story: list = []
    paragraph: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False
    code_language = ""

    def flush_paragraph() -> None:
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), s["body"]))
            paragraph.clear()

    def flush_table() -> None:
        if table_lines:
            story.append(table_from(table_lines, s["table"]))
            story.append(Spacer(1, 2 * mm))
            table_lines.clear()

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush_paragraph()
            flush_table()
            if in_code:
                if code_language == "mermaid":
                    story.append(Paragraph(
                        "질문 등록 → 자동 분석·답변 → 같은 글에서 후속 대화 → 해결 답변 선택 → Knowledge Base 생성 → Chat 완료 알림",
                        s["quote"],
                    ))
                elif code_lines:
                    story.append(Paragraph(escape("\n".join(code_lines)).replace("\n", "<br/>"), s["code"]))
                code_lines.clear()
                code_language = ""
            else:
                code_language = line[3:].strip().lower()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|"):
            flush_paragraph()
            table_lines.append(line)
            continue
        flush_table()
        if not line:
            flush_paragraph()
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), s["title"]))
            story.append(Paragraph("기술지원 담당자와 Community 사용자를 위한 운영 절차", s["quote"]))
            continue
        if line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline(line[3:]), s["h1"]))
            continue
        if line.startswith("### "):
            flush_paragraph()
            story.append(CondPageBreak(28 * mm))
            story.append(Paragraph(inline(line[4:]), s["h2"]))
            story.append(Spacer(1, 1.5 * mm))
            continue
        if re.match(r"^\s*[-*] ", line):
            flush_paragraph()
            item = re.sub(r"^\s*[-*] ", "", line)
            story.append(Paragraph("• " + inline(item), s["bullet"]))
            story.append(Spacer(1, 0.8 * mm))
            continue
        if re.match(r"^\s*\d+\. ", line):
            flush_paragraph()
            story.append(Paragraph(inline(line.strip()), s["bullet"]))
            story.append(Spacer(1, 0.8 * mm))
            continue
        if line.startswith(">"):
            flush_paragraph()
            story.append(Paragraph(inline(line.lstrip("> ")), s["quote"]))
            continue
        paragraph.append(line)
    flush_paragraph()
    flush_table()
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = BaseDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=17 * mm, bottomMargin=18 * mm,
        title="TechFlow Community 자동화 사용자 가이드",
        author="ABLESTACK TechFlow",
        subject="Chat 연결, Community 대화, 해결 승인, Knowledge Base 생성 사용자 절차",
    )
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="body")
    document.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page)])
    document.build(build_story())
    print(f"pdf={OUTPUT}")


if __name__ == "__main__":
    main()
