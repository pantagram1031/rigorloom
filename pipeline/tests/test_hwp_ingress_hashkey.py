# -*- coding: utf-8 -*-
"""Hancom's ``hashkey`` on embedded manifest items must validate; unknown attributes must not."""
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import hwp_ingress  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


def _rewrite_manifest(src: Path, dst: Path, item_extra: str) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/content.hpf":
                data = data.replace(
                    b'<opf:item id="image1" href="BinData/image1.png" media-type="image/png"/>',
                    ('<opf:item id="image1" href="BinData/image1.png" media-type="image/png" '
                     + item_extra + '/>').encode("utf-8"))
            zout.writestr(info, data)
    return dst


def test_hancom_hashkey_on_embedded_item_is_accepted(tmp_path):
    base = write_hwpx(tmp_path / "base.hwpx")
    art = _rewrite_manifest(base, tmp_path / "hashkey.hwpx", 'isEmbeded="1" hashkey="fZ/U7s7usHZIboZ3fR5qSQ=="')
    hwp_ingress._validate_hwpx(art)  # must not raise


def test_unknown_manifest_attribute_is_still_rejected(tmp_path):
    base = write_hwpx(tmp_path / "base.hwpx")
    art = _rewrite_manifest(base, tmp_path / "bad.hwpx", 'isEmbeded="1" onload="x"')
    with pytest.raises(hwp_ingress.IngressError) as exc:
        hwp_ingress._validate_hwpx(art)
    assert "hwpx_manifest_invalid" in str(exc.value)
