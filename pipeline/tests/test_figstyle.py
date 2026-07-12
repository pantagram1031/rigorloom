"""Tests for figstyle.py — figure_style pack -> rcParams resolver + CLI.

The module must import and resolve rcParams (and --dump) WITHOUT matplotlib.
These tests exercise the pure-python paths and simulate matplotlib being
absent by blocking its import.
"""
from __future__ import annotations

import builtins
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "figstyle.py"
_spec = importlib.util.spec_from_file_location("figstyle", SCRIPT)
figstyle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(figstyle)


class TestResolveNoMatplotlib(unittest.TestCase):
    def test_resolve_default_pack(self):
        rc = figstyle.resolve_rcparams()
        self.assertEqual(rc["figure.dpi"], 300)
        self.assertEqual(rc["figure.facecolor"], "#ffffff")
        self.assertTrue(rc["axes.spines.top"])  # box spines
        self.assertEqual(rc["xtick.direction"], "out")
        self.assertEqual(rc["axes.prop_cycle"]["color"][0], "#0072BD")

    def test_pack_merge_overrides(self):
        pack = {"dpi": 150, "background": "#111111", "spines": "open",
                "color_cycle": ["#123456"], "tick_direction": "in"}
        rc = figstyle.resolve_rcparams(pack)
        self.assertEqual(rc["figure.dpi"], 150)
        self.assertEqual(rc["figure.facecolor"], "#111111")
        self.assertFalse(rc["axes.spines.top"])  # open spines
        self.assertEqual(rc["xtick.direction"], "in")
        self.assertEqual(rc["axes.prop_cycle"]["color"], ["#123456"])

    def test_resolve_works_with_matplotlib_import_blocked(self):
        real_import = builtins.__import__

        def blocker(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ImportError("matplotlib blocked for test")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocker
        try:
            rc = figstyle.resolve_rcparams({"dpi": 72})
            self.assertEqual(rc["figure.dpi"], 72)
        finally:
            builtins.__import__ = real_import


class TestDumpCLI(unittest.TestCase):
    def test_dump_prints_valid_json(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--dump"],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["savefig.dpi"], 300)
        self.assertIn("axes.prop_cycle", data)


if __name__ == "__main__":
    unittest.main()
