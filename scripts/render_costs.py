#!/usr/bin/env python3
"""Render retained cost summaries as Times-font vector PDFs and TeX wrappers.

The whiskers are the observed minimum and maximum, not Tukey fences.  The
quartiles and median are read directly from cost-summary-us.csv; no samples
are collected, excluded, or recomputed by this presentation-only script.
"""
import argparse
import csv
import math
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

from render_traces import COLUMN_PT, PT_PER_CM, register_font

WORKLOADS = ("direct", "to_thread")
MODES = (("none", "None"), ("hook", "Hooks"), ("hook_sdk", "Hooks + SDK"))
STATISTICS = ("minimum", "q1", "median", "q3", "maximum")
FIELDS = ("workload", "mode", "n") + STATISTICS


def load_cost_rows(path):
    """Require exactly one nonnegative, ordered summary for each plotted cell."""
    cells = {}
    expected = {(w, m) for w in WORKLOADS for m, _ in MODES}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if (reader.fieldnames is None or len(reader.fieldnames) != len(FIELDS)
                or set(reader.fieldnames) != set(FIELDS)):
            raise ValueError("Cost CSV must have workload, mode, n and five-number summary columns")
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Cost CSV line {line}: wrong number of fields")
            key = (row["workload"], row["mode"])
            if key not in expected or key in cells:
                raise ValueError(f"Cost CSV line {line}: unknown or duplicate workload/mode {key}")
            try:
                n = int(row["n"])
                values = [float(row[name]) for name in STATISTICS]
            except ValueError as error:
                raise ValueError(f"Cost CSV line {line}: invalid count or summary value") from error
            if n <= 0 or any(not math.isfinite(v) or v < 0 for v in values):
                raise ValueError(f"Cost CSV line {line}: count must be positive and costs finite/nonnegative")
            if values != sorted(values):
                raise ValueError(f"Cost CSV line {line}: five-number summary is not ordered")
            cells[key] = {"n": n, **dict(zip(STATISTICS, values))}
    if set(cells) != expected:
        raise ValueError(f"Cost CSV is missing workload/mode cells: {sorted(expected - set(cells))}")
    return cells


def axis_for(maximum):
    """A linear zero-based axis with readable ticks and room above the whisker."""
    target = maximum * 1.05 if maximum > 0 else 1.0
    raw = target / 4
    scale = 10 ** math.floor(math.log10(raw))
    step = next(v * scale for v in (1, 2, 5, 10) if v * scale >= raw)
    count = math.ceil(target / step)
    return count * step, [i * step for i in range(count + 1)]


def draw_cost(directory, workload, cells):
    width, height = COLUMN_PT, 4.5 * PT_PER_CM
    left, right, bottom, top = 38, width - 8, 25, height - 8
    ymax, ticks = axis_for(max(cells[workload, m]["maximum"] for m, _ in MODES))
    y = lambda value: bottom + value / ymax * (top - bottom)
    pdf = canvas.Canvas(str(directory / f"cost-{workload}.pdf"),
                        pagesize=(width, height), invariant=1,
                        initialFontName="ManuscriptRoman")
    pdf.setTitle("")
    pdf.setStrokeColor(HexColor("#444444"))
    pdf.setFillColor(HexColor("#222222"))
    pdf.setLineWidth(.5)
    pdf.line(left, top, left, bottom)
    pdf.line(left, bottom, right, bottom)
    pdf.setFont("ManuscriptRoman", 7)
    for tick in ticks:
        yp = y(tick)
        pdf.line(left - 3, yp, left, yp)
        pdf.drawRightString(left - 5, yp - 2.2, f"{tick:g}")
    pdf.saveState()
    pdf.translate(10, (bottom + top) / 2)
    pdf.rotate(90)
    pdf.setFont("ManuscriptRoman", 8)
    pdf.drawCentredString(0, 0, "Microseconds / operation")
    pdf.restoreState()
    for index, (mode, label) in enumerate(MODES):
        row = cells[workload, mode]
        xp = left + (index + .5) * (right - left) / len(MODES)
        low, q1, median, q3, high = (y(row[name]) for name in STATISTICS)
        pdf.setLineWidth(.65)
        pdf.line(xp, low, xp, high)
        pdf.line(xp - 5, low, xp + 5, low)
        pdf.line(xp - 5, high, xp + 5, high)
        pdf.setFillColor(HexColor("#eeeeee"))
        pdf.rect(xp - 12, q1, 24, q3 - q1, stroke=1, fill=1)
        pdf.setLineWidth(1)
        pdf.line(xp - 12, median, xp + 12, median)
        pdf.setFillColor(HexColor("#222222"))
        pdf.setFont("ManuscriptRoman", 7)
        pdf.drawCentredString(xp, 12, label)
    pdf.showPage()
    pdf.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-csv", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    parser.add_argument("--font-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        cells = load_cost_rows(args.cost_csv)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    register_font(args.font_root)
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    for workload in WORKLOADS:
        draw_cost(args.figure_dir, workload, cells)
        wrapper = ("% Five-number cost summaries; microseconds per operation.\n"
                   "\\includegraphics[width=\\columnwidth]"
                   f"{{figures/cost-{workload}.pdf}}\n")
        (args.figure_dir / f"cost-{workload}.tex").write_text(wrapper, encoding="utf-8")


if __name__ == "__main__":
    main()
