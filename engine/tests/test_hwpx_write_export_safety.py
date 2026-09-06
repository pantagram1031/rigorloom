# -*- coding: utf-8 -*-
"""Card 1 writer half: a failed write must not destroy pre-existing dest bytes.

These cases fail on the #333 tip (`HwpxPackage.write` used shutil.move onto
dest) and pass after os.replace of a fsynced temp. Windows path aliases are
covered by the desktop export.rs matrix; this file owns the writer dest.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hwpx_write  # noqa: E402


def test_failed_temp_write_leaves_existing_dest(tmp_path, monkeypatch):
    dest = tmp_path / "out.hwpx"
    dest.write_bytes(b"OLD-DESTINATION-BYTES")
    package = hwpx_write.blank_package()

    def boom(_self):
        raise OSError("disk full while assembling")

    monkeypatch.setattr(hwpx_write.HwpxPackage, "tobytes", boom)
    with pytest.raises(OSError):
        package.write(dest)
    assert dest.read_bytes() == b"OLD-DESTINATION-BYTES"


def test_failed_replace_leaves_existing_dest(tmp_path, monkeypatch):
    dest = tmp_path / "out.hwpx"
    dest.write_bytes(b"OLD-DESTINATION-BYTES")
    package = hwpx_write.blank_package()

    def boom(*_args, **_kwargs):
        raise OSError("replace refused")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        package.write(dest)
    assert dest.read_bytes() == b"OLD-DESTINATION-BYTES"


def test_successful_write_replaces_existing_dest(tmp_path):
    dest = tmp_path / "out.hwpx"
    dest.write_bytes(b"OLD-DESTINATION-BYTES")
    package = hwpx_write.blank_package()
    package.write(dest)
    data = dest.read_bytes()
    assert data != b"OLD-DESTINATION-BYTES"
    assert data.startswith(b"PK")


def test_write_refuses_a_directory_destination(tmp_path):
    dest = tmp_path / "outdir"
    dest.mkdir()
    with pytest.raises(hwpx_write.HwpxWriteError):
        hwpx_write.blank_package().write(dest)
    assert dest.is_dir()


def test_writer_module_does_not_import_shutil():
    source = Path(hwpx_write.__file__).read_text(encoding="utf-8")
    assert "import shutil" not in source
    assert not hasattr(hwpx_write, "shutil")
