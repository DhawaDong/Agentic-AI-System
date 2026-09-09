"""
Publish stage: renders the final markdown report to a PDF file on disk.
Uses fpdf2 (pure-python, no system dependencies) so it works out of the box
on Render's standard Python runtime.
"""
import logging
import os
import re
from datetime import datetime

from fpdf import FPDF

from core import config

logger = logging.getLogger("agent.report")


class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "AI Breakthrough Discovery — Daily Report", align="R")
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _strip_markdown_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", text)
    return text


def render_pdf(title: str, markdown_text: str, run_id: int) -> str:
    """Very small markdown -> PDF renderer (headings, bullets, paragraphs).
    Good enough for an automatically generated daily report; swap in
    'markdown2' + 'weasyprint' later if you want full HTML/CSS fidelity."""
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 10, title)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, datetime.utcnow().strftime("Generated %Y-%m-%d %H:%M UTC"))
    pdf.ln(14)

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            pdf.ln(3)
            continue

        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 7, _strip_markdown_inline(line[4:]))
            pdf.ln(1)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(15, 15, 15)
            pdf.ln(2)
            pdf.multi_cell(0, 8, _strip_markdown_inline(line[3:]))
            pdf.ln(1)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(10, 10, 10)
            pdf.ln(3)
            pdf.multi_cell(0, 9, _strip_markdown_inline(line[2:]))
            pdf.ln(2)
        elif line.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 6, "  •  " + _strip_markdown_inline(line[2:]))
        else:
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 6, _strip_markdown_inline(line))

    filename = f"run_{run_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(config.REPORTS_DIR, filename)
    pdf.output(path)
    logger.info("Rendered PDF report to %s", path)
    return path
