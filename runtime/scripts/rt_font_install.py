"""Read-only OS font inventory for the editor's existing substitution reports."""
from __future__ import annotations

import os
from pathlib import PureWindowsPath
import re
import selectors
import subprocess
import sys
import time
import unicodedata


SCAN_SECONDS = 2
MAX_OUTPUT = 512 * 1024
MAX_REGISTRY_VALUES = 4096
MAX_FACES = 64
MAX_FACE_LENGTH = 128
_REGISTRY_FONTS = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
_FONT_FORMAT = re.compile(r"\s*\((?:TrueType|OpenType|All res|Raster)\)$", re.I)
_VENDOR_PREFIXES = ("함초롬", "한컴", "hcr", "hancom", "haansoft", "hci")


def _key(name):
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", name).casefold())


def _alias(name):
    # Localized family names, English family names and Windows file stems
    # use different prefixes. Keep the family and variant in the match.
    key = _key(name)
    key = re.sub(r"^(?:함초롬|han(?=batang|dotum))", "hcr", key)
    key = re.sub(r"^(?:한컴|haansoft|h(?=batang|dotum))", "hancom", key)
    return (key.replace("바탕", "batang").replace("돋움", "dotum")
            .replace("확장", "ext").replace("굵게", "bold"))


def is_hancom_face(name):
    return _key(name).startswith(_VENDOR_PREFIXES)


def _fontconfig_names():
    deadline = time.monotonic() + SCAN_SECONDS
    output = bytearray()
    with subprocess.Popen(["fc-list", "--format", "%{family}\n%{fullname}\n"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as child:
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                while len(output) <= MAX_OUTPUT:
                    if not ready.select(max(0, deadline - time.monotonic())) or time.monotonic() >= deadline:
                        return set(), False
                    block = os.read(child.stdout.fileno(), min(8192, MAX_OUTPUT + 1 - len(output)))
                    if not block:
                        if child.wait(timeout=max(0, deadline - time.monotonic())) == 0:
                            return set(re.split(r"[,\n]", output.decode("utf-8"))), True
                        return set(), False
                    output.extend(block)
            return set(), False
        finally:
            if child.poll() is None:
                child.kill()


def _windows_names(registry):
    names = set()
    complete = True
    deadline = time.monotonic() + SCAN_SECONDS
    budget = MAX_REGISTRY_VALUES
    output_budget = MAX_OUTPUT
    for hive in (registry.HKEY_LOCAL_MACHINE, registry.HKEY_CURRENT_USER):
        try:
            with registry.OpenKey(hive, _REGISTRY_FONTS, 0, registry.KEY_READ) as key:
                _, count, _ = registry.QueryInfoKey(key)
                for index in range(count):
                    if budget <= 0 or output_budget <= 0 or time.monotonic() >= deadline:
                        return names, False
                    label, filename, _ = registry.EnumValue(key, index)
                    budget -= 1
                    output_budget -= len(label) * 4 + (len(filename) * 4 if isinstance(filename, str) else 0)
                    if output_budget < 0:
                        return names, False
                    names.update(_FONT_FORMAT.sub("", label).split(" & "))
                    if isinstance(filename, str):
                        names.add(PureWindowsPath(filename).stem)
        except FileNotFoundError:
            # Windows need not create a per-user key before the first install.
            if hive == registry.HKEY_LOCAL_MACHINE:
                complete = False
        except OSError:
            complete = False
    return names, complete


def installed_states(faces):
    """Return installed/missing/unknown for each requested face."""
    if not faces:
        return {}
    names, complete = set(), False
    try:
        if sys.platform in {"linux", "darwin"}:
            names, complete = _fontconfig_names()
        elif sys.platform == "win32":
            import winreg

            names, complete = _windows_names(winreg)
    except (ImportError, OSError, subprocess.TimeoutExpired, UnicodeError):
        pass
    installed = {_alias(name) for name in names}
    absent = "missing" if complete else "unknown"
    return {face: "installed" if _alias(face) in installed else absent for face in faces}


def substitution_states(substitutions):
    """Add presence to the renderer's pairs and keep one row per document name."""
    pairs = {}
    for row in substitutions:
        name, drawn_with = row["want"], row["got"]
        if not isinstance(name, str) or not name or len(name) > MAX_FACE_LENGTH:
            continue
        if not isinstance(drawn_with, str):
            drawn_with = None
        if drawn_with and _alias(name) == _alias(drawn_with):
            continue
        if len(pairs) >= MAX_FACES and name not in pairs:
            break
        if not pairs.get(name):
            pairs[name] = drawn_with[:MAX_FACE_LENGTH] if drawn_with else None
    states = installed_states([name for name in pairs if is_hancom_face(name)])
    return [{"declared": name, "drawnWith": drawn_with, "state": states.get(name, "other")}
            for name, drawn_with in pairs.items()]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Report whether the named font families are installed.")
    parser.add_argument("face", nargs="+")
    args = parser.parse_args()
    if len(args.face) > MAX_FACES or any(len(face) > MAX_FACE_LENGTH for face in args.face):
        parser.error("too many faces or a face name is too long")
    print(json.dumps(installed_states(args.face), ensure_ascii=True))
