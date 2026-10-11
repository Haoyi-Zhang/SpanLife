"""Draw the paper's retained timing intervals as embedded-font vector PDFs."""
import argparse
import csv
import math
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

PT_PER_CM = 72 / 2.54
COLUMN_PT = 252


def register_font(root):
    face = pdfmetrics.EmbeddedType1Face(
        str(root / "afm/urw/times/utmr8a.afm"),
        str(root / "type1/urw/times/utmr8a.pfb"))
    pdfmetrics.registerTypeFace(face)
    pdfmetrics.registerFont(pdfmetrics.Font("ManuscriptRoman", face.name, "WinAnsiEncoding"))


def ticks_for(xmax):
    raw = xmax / 3
    scale = 10 ** math.floor(math.log10(raw))
    step = next(v * scale for v in (1, 2, 5, 10) if v * scale >= raw)
    return [i * step for i in range(int(xmax // step) + 1)]


def draw(directory, name, rows, width, height, limits, xlabel):
    c = canvas.Canvas(str(directory / (name + ".pdf")), pagesize=(width, height),
                      invariant=1, initialFontName="ManuscriptRoman")
    c.setTitle("")
    c.setFont("ManuscriptRoman", 7)
    left, right, bottom, top = 66, width - 6, 31, height - 8
    xmin, xmax = limits
    x = lambda value: left + (value - xmin) / (xmax - xmin) * (right - left)
    y = lambda row: bottom + (row - .4) / 4.2 * (top - bottom)
    c.setStrokeColor(HexColor("#444444"))
    c.setLineWidth(.5)
    c.line(left, bottom, right, bottom)
    for tick in ticks_for(xmax):
        xp = x(tick)
        c.line(xp, bottom, xp, bottom - 3)
        c.drawCentredString(xp, bottom - 12, f"{tick:g}")
    c.setFont("ManuscriptRoman", 8)
    c.drawCentredString((left + right) / 2, 8, xlabel)
    for row in rows:
        yp = y(int(row["row"]))
        c.setFont("ManuscriptRoman", 7)
        c.setFillColor(HexColor("#222222"))
        c.drawRightString(left - 5, yp - 2.2, row["label"])
        is_span = row["label"].endswith("span")
        c.setStrokeColor(HexColor("#24629b" if is_span else "#a23e36"))
        c.setLineWidth(1.3 if is_span else 2.8)
        c.setDash([] if is_span else [3, 2])
        x0, x1 = x(float(row["start"])), x(float(row["end"]))
        c.line(x0, yp, x1, yp)
        c.setDash([])
        c.setLineWidth(.65)
        c.line(x0, yp - 3, x0, yp + 3)
        c.line(x1, yp - 3, x1, yp + 3)
    c.showPage()
    c.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-root", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    register_font(args.font_root)
    with (args.figure_dir / "trace_intervals.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    timeline = [r for r in rows if r["figure"] == "timeline"]
    uipath = [r for r in rows if r["figure"] == "uipath"]
    assert len(timeline) == len(uipath) == 4
    assert sorted(int(r["row"]) for r in timeline) == [1, 2, 3, 4]
    assert sorted(int(r["row"]) for r in uipath) == [1, 2, 3, 4]
    timeline_max = max(float(r["end"]) for r in timeline if not r["label"].endswith("span")) * 1.08
    uipath_min = min(float(r["start"]) for r in uipath) - 8
    uipath_max = max(float(r["end"]) for r in uipath) + 8
    draw(args.figure_dir, "timeline", timeline, .92 * COLUMN_PT,
         4.4 * PT_PER_CM, (0, timeline_max), "Milliseconds from invocation entry")
    draw(args.figure_dir, "uipath-early-close", uipath, .98 * COLUMN_PT,
         4.3 * PT_PER_CM, (uipath_min, uipath_max), "Microseconds from operation entry")


if __name__ == "__main__":
    main()
