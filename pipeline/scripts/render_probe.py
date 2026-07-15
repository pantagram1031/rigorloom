# -*- coding: utf-8 -*-
"""render_probe.py — capability detector for document rendering backends.

Stdlib only. Probes this machine (never launches Hancom, never raises) for:
  hancom_com    win32 only: pyhwpx importable AND the HWP COM ProgID exists
  soffice_path  `soffice` (or `soffice.com` on win32) resolvable on PATH
  soffice_wsl   win32 only: `wsl -e bash -lc "command -v soffice"` succeeds
  h2orestart    "yes"|"no"|"unknown" — only meaningful where soffice was
                found; probed via `unopkg list --bundled` (native or via wsl)

Each probe is individually guarded (catches its own exceptions) so a single
missing tool, unusual PATH, or WSL hiccup never blocks the others.

rhwp is exposed only as an experimental SVG renderer. It is never returned by
best_pdf_cmd and therefore cannot be mistaken for a LibreOffice PDF command.

Output schema (see probe()):
    {
      "capabilities": {"hancom_com": bool, "soffice_path": str|None,
                       "soffice_wsl": bool, "h2orestart": "yes"|"no"|"unknown",
                       "rhwp_path": str|None, "rhwp_wsl": bool,
                       "rhwp_version": str|None, "rhwp_reason": str},
      "renderers": [{"name": str, "wsl": bool, "argv": list[str]|None}, ...]
    }
No timestamps — the output is a pure function of machine state, kept
deterministic for tests and for diffing across runs.

Renderer argv templates use fill_report.py's `{in}` and `{outdir}`
placeholders. The WSL template accepts the substituted Windows paths as
positional arguments and translates them inside WSL with `wslpath`, so it is
safe to pass through `fill_report.py --pdf-cmd` just like the native template.

CLI:
    python render_probe.py [--json] [--out <path>]
        --json   print raw JSON (default: human-readable capability matrix)
        --out    also write the JSON result to this path
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

_SOFFICE_ARGS = (
    "--headless",
    "-env:UserInstallation=file:///tmp/lo-profile",
    "--convert-to", "pdf:writer_pdf_Export",
    "--outdir", "{outdir}", "{in}",
)

_WSL_SOFFICE_SCRIPT = (
    'exec soffice --headless '
    '-env:UserInstallation=file:///tmp/lo-profile '
    '--convert-to pdf:writer_pdf_Export '
    '--outdir "$(wslpath -a "$1")" "$(wslpath -a "$2")"'
)

_WSL_TIMEOUT = 10
_H2ORESTART_TIMEOUT = 10
_HANCOM_TIMEOUT = 10
_RHWP_TIMEOUT = 10

_HANCOM_PROBE_CODE = r"""
import importlib.util
import winreg

if importlib.util.find_spec("pyhwpx") is None:
    raise SystemExit(1)

progids = ("HWPFrame.HwpObject", "HWPFrame.HwpObject.1", "HWPFrame.HwpObject.2")
for progid in progids:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid):
            raise SystemExit(0)
    except OSError:
        pass
raise SystemExit(1)
"""


def _probe_hancom_com() -> bool:
    if sys.platform != "win32":
        return False
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _HANCOM_PROBE_CODE],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_HANCOM_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return proc.returncode == 0


def _probe_soffice_path() -> str | None:
    names = ["soffice.com", "soffice"] if sys.platform == "win32" else ["soffice"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _probe_soffice_wsl() -> bool:
    if sys.platform != "win32":
        return False
    try:
        proc = subprocess.run(
            ["wsl", "-e", "bash", "-lc", "command -v soffice"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_WSL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return proc.returncode == 0


def _probe_h2orestart(soffice_path: str | None, soffice_wsl: bool) -> str:
    """"yes"/"no" only when we could actually ask a soffice install; otherwise
    "unknown" — including any probe failure, which we tolerate rather than
    treat as a hard "no" (H2Orestart may simply be un-checkable here)."""
    if soffice_path:
        cmd = ["unopkg", "list", "--bundled"]
    elif soffice_wsl:
        cmd = ["wsl", "-e", "bash", "-lc", "unopkg list --bundled"]
    else:
        return "unknown"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_H2ORESTART_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    blob = ((proc.stdout or "") + (proc.stderr or "")).lower()
    normalized = re.sub(r"[^a-z0-9]+", "", blob)
    # Debian packages call the filter H2Orestart, while its bundled extension
    # id is commonly `net.sf.h2restart.oxt` (without the letter O).
    return "yes" if ("h2orestart" in normalized or
                     "h2restart" in normalized) else "no"


def _probe_rhwp() -> dict:
    """Probe a configured or PATH rhwp binary without attempting a render."""
    configured = os.environ.get("RHWP_BIN", "").strip()
    candidate = configured or shutil.which("rhwp")
    if not candidate:
        return {
            "path": None, "wsl": False, "version": None, "reason": "not_found",
        }
    candidate = os.path.abspath(os.path.expanduser(candidate))
    if configured and not os.path.isfile(candidate):
        return {
            "path": candidate, "wsl": sys.platform == "win32",
            "version": None, "reason": "configured_path_missing",
        }
    via_wsl = sys.platform == "win32"
    command = (
        ["wsl", "--", to_wsl_path(candidate), "--version"]
        if via_wsl else [candidate, "--version"]
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_RHWP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {
            "path": candidate, "wsl": via_wsl,
            "version": None, "reason": "probe_timeout",
        }
    except (OSError, ValueError):
        return {
            "path": candidate, "wsl": via_wsl,
            "version": None, "reason": "probe_failed",
        }
    if completed.returncode != 0:
        return {
            "path": candidate, "wsl": via_wsl,
            "version": None, "reason": "probe_nonzero",
        }
    version_blob = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    version = next((line.strip() for line in version_blob.splitlines() if line.strip()), "unknown")
    return {
        "path": candidate, "wsl": via_wsl,
        "version": version, "reason": "available",
    }


def _build_renderers(capabilities: dict) -> list[dict]:
    renderers: list[dict] = []
    if capabilities["hancom_com"]:
        renderers.append({"name": "hancom", "wsl": False, "argv": None})
    if (capabilities.get("rhwp_path")
            and capabilities.get("rhwp_reason") == "available"):
        binary = capabilities["rhwp_path"]
        via_wsl = capabilities.get("rhwp_wsl") is True
        if via_wsl:
            binary = to_wsl_path(binary)
        argv = (
            ["wsl", "--", binary, "export-svg", "{in}", "-o", "{outdir}"]
            if via_wsl else
            [binary, "export-svg", "{in}", "-o", "{outdir}"]
        )
        renderers.append({
            "name": "rhwp_svg",
            "wsl": via_wsl,
            "argv": argv,
            "version": capabilities.get("rhwp_version"),
            "proof_grade": "experimental-rhwp",
        })
    if capabilities["soffice_path"]:
        renderers.append({"name": "soffice_local", "wsl": False,
                          "argv": [capabilities["soffice_path"], *_SOFFICE_ARGS]})
    if capabilities["soffice_wsl"]:
        renderers.append({"name": "soffice_wsl", "wsl": True,
                          "argv": [
                              "wsl", "-e", "bash", "-lc", _WSL_SOFFICE_SCRIPT,
                              "render_probe", "{outdir}", "{in}",
                          ]})
    return renderers


def probe() -> dict:
    """Run every capability probe (each already self-guarded) and assemble the
    capabilities + renderers document. Never raises."""
    try:
        hancom_com = _probe_hancom_com()
    except Exception:
        hancom_com = False
    try:
        soffice_path = _probe_soffice_path()
    except Exception:
        soffice_path = None
    try:
        soffice_wsl = _probe_soffice_wsl()
    except Exception:
        soffice_wsl = False
    try:
        h2orestart = _probe_h2orestart(soffice_path, soffice_wsl)
    except Exception:
        h2orestart = "unknown"
    try:
        rhwp = _probe_rhwp()
    except Exception:
        rhwp = {
            "path": None, "wsl": False, "version": None,
            "reason": "probe_failed",
        }

    capabilities = {
        "hancom_com": hancom_com,
        "soffice_path": soffice_path,
        "soffice_wsl": soffice_wsl,
        "h2orestart": h2orestart,
        "rhwp_path": rhwp["path"],
        "rhwp_wsl": rhwp["wsl"],
        "rhwp_version": rhwp["version"],
        "rhwp_reason": rhwp["reason"],
    }
    return {"capabilities": capabilities, "renderers": _build_renderers(capabilities)}


def to_wsl_path(path: str) -> str:
    """Translate a Windows absolute path to its WSL /mnt/<drive> form, e.g.
    'C:\\Users\\x\\a.hwpx' -> '/mnt/c/Users/x/a.hwpx'. Paths without a drive
    letter are left as-is (backslashes normalized to forward slashes)."""
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if not m:
        return path.replace("\\", "/")
    drive, rest = m.groups()
    return f"/mnt/{drive.lower()}/{rest.replace(chr(92), '/')}"


def best_pdf_cmd(result: dict) -> list[str] | None:
    """First renderer usable as a fill_report.py --pdf-cmd argv.

    Hancom is capability-only and has no argv. WSL argv templates are usable:
    they perform their path translation inside WSL after fill_report replaces
    `{in}` and `{outdir}`.
    """
    for renderer in result.get("renderers", []):
        if (renderer.get("name") in {"soffice_local", "soffice_wsl"}
                and renderer.get("argv")):
            return list(renderer["argv"])
    return None


def hwpx_has_equations(path) -> bool:
    """Return whether an HWPX section contains a literal equation element.

    The check is deliberately document-local and does not alter ``probe()``'s
    machine-capability schema. Missing pre-assembly outputs are equation-free
    for selection purposes; malformed archives still surface to the caller.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not fnmatch.fnmatchcase(name, "Contents/section*.xml"):
                    continue
                if b"<hp:equation" in archive.read(name):
                    return True
    except FileNotFoundError:
        return False
    return False


def format_table(result: dict) -> str:
    """Human-readable capability matrix (used by bootstrap.py and the CLI's
    default, non-JSON output)."""
    caps = result.get("capabilities", {})
    rows = [
        ("hancom_com", str(caps.get("hancom_com"))),
        ("soffice_path", str(caps.get("soffice_path"))),
        ("soffice_wsl", str(caps.get("soffice_wsl"))),
        ("h2orestart", str(caps.get("h2orestart"))),
        ("rhwp_path", str(caps.get("rhwp_path"))),
        ("rhwp_wsl", str(caps.get("rhwp_wsl"))),
        ("rhwp_version", str(caps.get("rhwp_version"))),
        ("rhwp_reason", str(caps.get("rhwp_reason"))),
    ]
    width = max(len(label) for label, _ in rows)
    lines = ["Render capability matrix", "-" * 40]
    lines += [f"  {label.ljust(width)}  {value}" for label, value in rows]
    renderers = result.get("renderers", [])
    names = ", ".join(r["name"] for r in renderers) if renderers else "(none usable)"
    lines.append(f"  {'renderers'.ljust(width)}  {names}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Render capability probe (Hancom COM / rhwp / soffice / WSL / H2Orestart)")
    ap.add_argument("--json", action="store_true",
                    help="print raw JSON instead of the human-readable table")
    ap.add_argument("--out", default=None, help="also write the JSON result to this path")
    a = ap.parse_args(argv)

    result = probe()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text if a.json else format_table(result))
    return 0


def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; output may contain
    non-ASCII (e.g. soffice paths under Korean usernames). Reconfigure stdio
    so printing never dies with UnicodeEncodeError (no-op where already
    UTF-8 or unsupported)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
