"""Bounded plotting-route tests; no subject, timing, resampling, or font install."""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plot_inputs/trace_intervals.csv"
SCRIPT = ROOT / "scripts/render_paper_figures.py"
spec = importlib.util.spec_from_file_location("render_paper_figures_under_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SCRIPT.parent))
try:
    spec.loader.exec_module(module)
finally:
    sys.path.pop(0)


class PlotRouteTests(unittest.TestCase):
    def test_retained_values_and_order(self):
        timeline, uipath = module.load_data(SOURCE)
        self.assertEqual((len(timeline), len(uipath)), (4, 4))
        self.assertEqual(float(uipath[0]["start"]), -17.867)
        self.assertEqual(float(uipath[1]["end"]), 201.764)

    def test_invalid_input_is_not_silently_plotted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / SOURCE.name
            source.write_text(SOURCE.read_text(encoding="utf-8").replace("-17.867", "nan"), encoding="utf-8")
            with self.assertRaises(ValueError):
                module.load_data(source)

    def test_missing_font_fails_before_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "uncreated"
            with self.assertRaises(FileNotFoundError):
                module.main(["--source", str(SOURCE), "--output-dir", str(output), "--font-root", str(Path(directory) / "absent")])
            self.assertFalse(output.exists())

    def test_required_paths_have_no_implicit_output(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as raised:
            module.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_output_routing_keeps_drawing_contract_and_source(self):
        before = SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            self.check_drawing(Path(directory) / "vectors")
        self.assertEqual(SOURCE.read_bytes(), before)

    def check_drawing(self, output):
        with mock.patch.object(module.Path, "is_file", return_value=True), mock.patch.object(module, "register_font"), mock.patch.object(module, "draw") as draw:
            module.main(["--source", str(SOURCE), "--output-dir", str(output), "--font-root", str(output / "fonts")])
        self.assertEqual([call.args[1] for call in draw.call_args_list], ["timeline", "uipath-early-close"])
        self.assertEqual(draw.call_args_list[0].args[5], (0, 12.730019 * 1.08))
        self.assertEqual(draw.call_args_list[1].args[5], (-25.867, 209.764))


if __name__ == "__main__":
    unittest.main()
