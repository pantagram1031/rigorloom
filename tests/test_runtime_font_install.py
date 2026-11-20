"""Font detection reads platform inventory and derives guidance from substitution pairs."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import shutil
import sys

import pytest

from runtime.scripts import rt_font_install as fonts
from runtime.scripts import rt_own


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_fontconfig_aliases_and_unavailable(monkeypatch, platform):
    monkeypatch.setattr(fonts.sys, "platform", platform)
    monkeypatch.setattr(fonts, "_fontconfig_names", lambda: ({"HCR Batang", "Nanum Gothic"}, True))
    names = ["함초롬바탕", "함초롬돋움", "한컴 바탕"]
    assert fonts.installed_states(names) == dict(zip(names, ["installed", "missing", "missing"]))

    def unavailable():
        raise FileNotFoundError("fc-list")

    monkeypatch.setattr(fonts, "_fontconfig_names", unavailable)
    assert fonts.installed_states(names) == dict.fromkeys(names, "unknown")


@pytest.mark.skipif(sys.platform == "win32", reason="fontconfig runs on POSIX")
@pytest.mark.parametrize("kind", ["available", "too_large", "timeout", "failure"])
def test_fontconfig_process_is_bounded(tmp_path, monkeypatch, kind):
    # Stand in for fc-list without querying or modifying any system fonts.
    script = {
        "available": 'print("HCR Batang,함초롬바탕\\nNanum Gothic")',
        "too_large": 'print("A" * 1000)',
        "timeout": 'import time\ntime.sleep(30)',
        "failure": 'raise SystemExit(4)',
    }[kind]
    command = tmp_path / "fc-list"
    command.write_text(f"#!{Path(sys.executable).as_posix()}\n{script}\n", encoding="utf-8")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(fonts, "MAX_OUTPUT", 100)
    monkeypatch.setattr(fonts, "SCAN_SECONDS", 0.25)
    names, complete = fonts._fontconfig_names()
    assert complete == (kind == "available")
    assert {"HCR Batang", "함초롬바탕", "Nanum Gothic"} <= names if complete else not names


def registry_fake(machine, user):
    values = {"machine": machine, "user": user}

    def open_key(hive, key, reserved, access):
        assert key == fonts._REGISTRY_FONTS and reserved == 0 and access == 1
        if isinstance(values[hive], Exception):
            raise values[hive]
        return nullcontext(values[hive])

    return SimpleNamespace(
        HKEY_LOCAL_MACHINE="machine", HKEY_CURRENT_USER="user", KEY_READ=1, OpenKey=open_key,
        QueryInfoKey=lambda entries: (0, len(entries), 0),
        EnumValue=lambda entries, index: entries[index],
    )


def test_windows_detection_reads_both_registry_hives(monkeypatch):
    registry = registry_fake(
        [("HCR Batang (TrueType)", "HANBatang.ttf", 1)],
        [("HCR Dotum (TrueType)", r"C:\User\Fonts\HANDotum.ttf", 1),
         ("한컴 바탕 (OpenType)", "HBATANG.ttf", 1)],
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(fonts.sys, "platform", "win32")
    names = ["함초롬바탕", "함초롬돋움", "Haansoft Batang", "한컴돋움"]
    assert fonts.installed_states(names) == dict(zip(names, ["installed", "installed", "installed", "missing"]))


@pytest.mark.parametrize("user,limit,expected", [
    (FileNotFoundError(), 4, "missing"),
    (PermissionError(), 4, "unknown"),
    ([("HCR Dotum (TrueType)", "HANDotum.ttf", 1)], 1, "unknown"),
])
def test_windows_partial_inventory_preserves_positive_matches(monkeypatch, user, limit, expected):
    monkeypatch.setitem(sys.modules, "winreg", registry_fake([("HCR Batang (TrueType)", "HANBatang.ttf", 1)], user))
    monkeypatch.setattr(fonts.sys, "platform", "win32")
    monkeypatch.setattr(fonts, "MAX_REGISTRY_VALUES", limit)
    assert fonts.installed_states(["함초롬바탕", "함초롬돋움"]) == {"함초롬바탕": "installed", "함초롬돋움": expected}


def test_unsupported_platform_and_substitution_derivation(monkeypatch):
    monkeypatch.setattr(fonts.sys, "platform", "other")
    assert fonts.installed_states(["함초롬바탕"]) == {"함초롬바탕": "unknown"}
    monkeypatch.setattr(fonts, "installed_states", lambda names: dict.fromkeys(names, "missing"))
    assert fonts.substitution_states([
        {"want": "함초롬바탕", "got": None},
        {"want": "함초롬바탕", "got": "Nanum Myeongjo"},
        {"want": "Arial", "got": "Liberation Sans"},
        {"want": "한컴 돋움", "got": "Haansoft Dotum"},
        {"want": "함초롬바탕", "got": "Another fallback"},
    ]) == [
        {"declared": "함초롬바탕", "drawnWith": "Nanum Myeongjo", "state": "missing"},
        {"declared": "Arial", "drawnWith": "Liberation Sans", "state": "other"},
    ]


def test_builtin_renderer_reports_the_bundled_substitute_for_font_guidance(monkeypatch):
    sidecar = {"fonts": {"faces": [
        {"declared": "함초롬바탕", "source": "bundled", "resolved": True,
         "installed_family": "Nanum Myeongjo"},
        {"declared": "함초롬돋움", "source": "installed", "resolved": True,
         "installed_family": "HCR Dotum"},
    ]}}
    assert rt_own.font_summary(sidecar)["substituted"] == []
    report = rt_own.font_summary(sidecar, include_bundled=True)
    monkeypatch.setattr(fonts, "installed_states", lambda names: dict.fromkeys(names, "missing"))
    assert fonts.substitution_states([
        {"want": row["declared"], "got": row["drawnWith"]} for row in report["substituted"]
    ]) == [{"declared": "함초롬바탕", "drawnWith": "Nanum Myeongjo", "state": "missing"}]


_MADE_UP_FACE = "Rigorloom Absent Face 7f3c"


@pytest.mark.skipif(sys.platform != "win32", reason="reads the real Windows font registry")
def test_real_windows_registry_detects_installed_and_missing_faces():
    states = fonts.installed_states(["Segoe UI", _MADE_UP_FACE])
    assert states == {"Segoe UI": "installed", _MADE_UP_FACE: "missing"}


@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("fc-list") is None,
                    reason="reads the real fontconfig inventory")
def test_real_fontconfig_detects_installed_and_missing_faces():
    states = fonts.installed_states(["DejaVu Sans", _MADE_UP_FACE])
    assert states == {"DejaVu Sans": "installed", _MADE_UP_FACE: "missing"}
