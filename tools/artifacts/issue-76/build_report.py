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
SOURCE = ROOT / "docs/reports/issue-76-guest-os-official-platform-evidence-validation.md"
OUTPUT = ROOT / "output/pdf/techflow-guest-os-official-platform-evidence-report.pdf"


def fonts() -> tuple[str, str]:
    regular, bold = "Helvetica", "Helvetica-Bold"
    normal_path, bold_path = Path("C:/Windows/Fonts/malgun.ttf"), Path("C:/Windows/Fonts/malgunbd.ttf")
    if normal_path.exists():
        pdfmetrics.registerFont(TTFont("Malgun76", str(normal_path))); regular = "Malgun76"
    if bold_path.exists():
        pdfmetrics.registerFont(TTFont("Malgun76-Bold", str(bold_path))); bold = "Malgun76-Bold"
    return regular, bold


REGULAR, BOLD = fonts()


def inline(value: str) -> str:
    value = escape(value)
    value = re.sub(r"`([^`]+)`", rf"<font name='{BOLD}'>\1</font>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<link href='\2' color='#2563EB'>\1</link>", value)
    return value


def footer(canvas, doc) -> None:
    canvas.saveState(); canvas.setFont(REGULAR, 8); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18 * mm, 10 * mm, "ABLESTACK TechFlow - Issue #76")
    canvas.drawRightString(192 * mm, 10 * mm, str(doc.page)); canvas.restoreState()


def make_table(lines: list[str], body: ParagraphStyle) -> Table:
    raw = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(raw) > 1 and all(set(cell) <= {"-", ":", " "} for cell in raw[1]): raw.pop(1)
    header = ParagraphStyle("I76TableHeader", parent=body, textColor=colors.white, fontName=BOLD)
    rows = [
        [Paragraph(inline(cell), header if row_index == 0 else body) for cell in row]
        for row_index, row in enumerate(raw)
    ]
    width = 174 * mm
    table = Table(rows, colWidths=[width / len(rows[0])] * len(rows[0]), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_story() -> list:
    base = getSampleStyleSheet()
    style = {
        "title": ParagraphStyle("I76Title", parent=base["Title"], fontName=BOLD, fontSize=21, leading=29, textColor=colors.HexColor("#0F172A"), spaceAfter=8 * mm),
        "h1": ParagraphStyle("I76H1", parent=base["Heading1"], fontName=BOLD, fontSize=15, leading=21, textColor=colors.HexColor("#1D4ED8"), spaceBefore=5 * mm, spaceAfter=3 * mm),
        "h2": ParagraphStyle("I76H2", parent=base["Heading2"], fontName=BOLD, fontSize=12, leading=17, spaceBefore=3 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("I76Body", parent=base["BodyText"], fontName=REGULAR, fontSize=9.1, leading=14.5, textColor=colors.HexColor("#1E293B"), spaceAfter=2 * mm),
        "bullet": ParagraphStyle("I76Bullet", parent=base["BodyText"], fontName=REGULAR, fontSize=9, leading=14, leftIndent=6 * mm, firstLineIndent=-3.5 * mm, spaceAfter=1.2 * mm),
        "code": ParagraphStyle("I76Code", parent=base["Code"], fontName=REGULAR, fontSize=7.6, leading=11, backColor=colors.HexColor("#F1F5F9"), borderPadding=5, spaceAfter=2 * mm),
    }
    output: list = []; paragraph: list[str] = []; table_lines: list[str] = []; code_lines: list[str] = []; in_code = False
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
        if line.startswith("## "): flush_paragraph(); output.append(Paragraph(inline(line[3:]), style["h1"])); continue
        if line.startswith("### "): flush_paragraph(); output.append(Paragraph(inline(line[4:]), style["h2"])); continue
        if re.match(r"^[-*] ", line): flush_paragraph(); output.append(Paragraph("- " + inline(line[2:]), style["bullet"])); continue
        if re.match(r"^\d+\. ", line): flush_paragraph(); output.append(Paragraph(inline(line), style["bullet"])); continue
        if line.startswith("> "): flush_paragraph(); output.append(Paragraph(inline(line[2:]), style["body"])); continue
        paragraph.append(line)
    flush_paragraph(); flush_table(); return output


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm, title="TechFlow 공식 플랫폼 근거 검증 보고서")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
    doc.build(build_story()); print(f"report={OUTPUT}")


if __name__ == "__main__": main()
