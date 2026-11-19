# -*- coding: utf-8 -*-
"""TEST-ONLY document layer for subprocess tests of ``rigorloom mcp``.

Loaded by ``rt_tools.load_doc`` when ``RIGORLOOM_TEST_DOC_MODULE`` names this
file. It is the fake in ``_fake_rt_doc.py`` (``.fdoc`` documents) plus the two
things the in-process tests set with monkeypatch: ``.fdoc`` as an accepted
input/output format, and ``.fdoc`` as the native suffix for ``new``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _fake_rt_doc as _fake  # noqa: E402

NATIVE_SUFFIX = ".fdoc"

for _name in ("rigorloom_runtime.rt_toolset", "rt_toolset"):
    _toolset = sys.modules.get(_name)
    if _toolset is None:
        continue
    if "fdoc" not in _toolset.FORMATS_IN:
        _toolset.FORMATS_IN = _toolset.FORMATS_IN + ("fdoc",)
    if "fdoc" not in _toolset.FORMATS_OUT:
        _toolset.FORMATS_OUT = _toolset.FORMATS_OUT + ("fdoc",)


def __getattr__(name: str):
    return getattr(_fake, name)
