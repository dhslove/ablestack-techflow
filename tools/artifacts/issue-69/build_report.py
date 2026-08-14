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
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/reports/issue-69-community-auto-publish-kb-validation.md"
OUTPUT = ROOT / "output/pdf/techflow-community-auto-publish-kb-report.pdf"
FONT = Path("C:/Windows/Fonts/malgun.ttf")
BOLD_FONT = Path("C:/Windows/Fonts/malgunbd.ttf")


def register_fonts() -> tuple[str, str]:
    regular, bold = "Helvetica", "Helvetica-Bold"
    if FONT.exists():
        pdfmetrics.registerFont(TTFont("Malgun69", str(FONT))); regular = "Malgun69"
    if BOLD_FONT.exists():
        pdfmetrics.registerFont(TTFont("Malgun69-Bold", str(BOLD_FONT))); bold = "Malgun69-Bold"
    return regular, bold


REGULAR, BOLD = register_fonts()


def inline(value: str) -> str:
    value = escape(value)
    value = re.sub(r"`([^`]+)`", rf"<font name='{BOLD}'>\1</font>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<link href='\2' color='#2563EB'>\1</link>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", rf"<font name='{BOLD}'>\1</font>", value)
    return value


def page(canvas, doc) -> None:
    canvas.saveState(); canvas.setFont(REGULAR, 8); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18 * mm, 10 * mm, "ABLESTACK TechFlow - Issue #69")
    canvas.drawRightString(192 * mm, 10 * mm, str(doc.page)); canvas.restoreState()


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("I69Title", parent=base["Title"], fontName=BOLD, fontSize=22, leading=30, textColor=colors.HexColor("#0F172A"), spaceAfter=8 * mm),
        "h1": ParagraphStyle("I69H1", parent=base["Heading1"], fontName=BOLD, fontSize=16, leading=22, textColor=colors.HexColor("#1D4ED8"), spaceBefore=6 * mm, spaceAfter=3 * mm),
        "h2": ParagraphStyle("I69H2", parent=base["Heading2"], fontName=BOLD, fontSize=12.5, leading=18, textColor=colors.HexColor("#0F172A"), spaceBefore=4 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("I69Body", parent=base["BodyText"], fontName=REGULAR, fontSize=9.2, leading=14.8, textColor=colors.HexColor("#1E293B"), spaceAfter=2 * mm),
        "bullet": ParagraphStyle("I69Bullet", parent=base["BodyText"], fontName=REGULAR, fontSize=9, leading=14.2, leftIndent=6 * mm, firstLineIndent=-3.5 * mm, textColor=colors.HexColor("#1E293B"), spaceAfter=1.2 * mm),
        "code": ParagraphStyle("I69Code", parent=base["Code"], fontName=REGULAR, fontSize=7.6, leading=11, backColor=colors.HexColor("#F1F5F9"), borderPadding=5, spaceAfter=2 * mm),
    }


def make_table(lines: list[str], body: ParagraphStyle) -> Table:
    header = ParagraphStyle("I69Header", parent=body, fontName=BOLD, textColor=colors.white)
    raw = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [[Paragraph(inline(cell), header if index == 0 else body) for cell in row] for index, row in enumerate(raw)]
    if len(rows) > 1: rows.pop(1)
    width = 174 * mm
    table = Table(rows, colWidths=[width / len(rows[0])] * len(rows[0]), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    return table


def story() -> list:
    style = styles(); output: list = []; paragraph: list[str] = []; table_lines: list[str] = []; code_lines: list[str] = []; in_code = False
    def flush_paragraph() -> None:
        if paragraph: output.append(Paragraph(inline(" ".join(paragraph)), style["body"])); paragraph.clear()
    def flush_table() -> None:
        if table_lines: output.append(make_table(table_lines, style["body"])); output.append(Spacer(1, 2 * mm)); table_lines.clear()
    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush_paragraph(); flush_table()
            if in_code: output.append(Paragraph(escape("\n".join(code_lines)).replace("\n", "<br/>"), style["code"])); code_lines.clear()
            in_code = not in_code; continue
        if in_code: code_lines.append(line); continue
        if line.startswith("|"): flush_paragraph(); table_lines.append(line); continue
        flush_table()
        if not line: flush_paragraph(); continue
        if line.startswith("# "): flush_paragraph(); output.append(Paragraph(inline(line[2:]), style["title"])); continue
        if line.startswith("## "):
            flush_paragraph()
            if line.startswith("## 8."):
                output.append(PageBreak())
            output.append(Paragraph(inline(line[3:]), style["h1"])); continue
        if line.startswith("### "): flush_paragraph(); output.append(Paragraph(inline(line[4:]), style["h2"])); continue
        if re.match(r"^[-*] ", line): flush_paragraph(); output.append(Paragraph("- " + inline(line[2:]), style["bullet"])); continue
        if re.match(r"^\d+\. ", line): flush_paragraph(); output.append(Paragraph(inline(line), style["bullet"])); continue
        paragraph.append(line)
    flush_paragraph(); flush_table(); return output


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm, title="TechFlow Community 자동 답변 Knowledge Base 보고서")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page)])
    doc.build(story()); print(f"report={OUTPUT}")


if __name__ == "__main__": main()
