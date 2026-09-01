# shell-tauri — throwaway measurement harness

The Tauri 2 arm of the desktop shell spike. **Not product code.** Its only job
is to produce the numbers in the `## Decision` section of
`docs/desktop-shell-spike.md`. Delete it once the shell is chosen.

## Prerequisites (measured 2026-09-01, all already present on the dev machine)

Rust 1.97.1 (`x86_64-pc-windows-msvc`), MSVC Build Tools 2019, WebView2 Runtime
151.0.4129.107, Node 22.16.0 / npm 10.9.2.

**Pin the interpreter.** The sidecar venv must be built from the non-Store
CPython at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` (3.12.10). The
`python` on PATH is a Microsoft Store build that PyInstaller cannot freeze
from, and `C:\Python313` is a partial install with no `Lib/`.

## Build

```sh
# 1. sidecar venv (once)
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m venv sidecar/.venv
./sidecar/.venv/Scripts/python.exe -m pip install pyinstaller pymupdf

# 2. freeze the sidecar (both packaging modes + the M11 console control arm)
bash sidecar/build.sh

# 3. frontend deps + app
npm install
npx tauri build
```

Artifacts: `src-tauri/target/release/rigorloom-shell-spike.exe` and
`src-tauri/target/release/bundle/nsis/*-setup.exe`.

## Runtime switches (the spike's A/B arms)

| Env var | Effect |
|---|---|
| `RIGORLOOM_SPIKE_SIDECAR=<abs path>` | run that sidecar instead of the bundled `externalBin` — lets one shell binary measure both packaging modes |
| `RIGORLOOM_SPIKE_NOJOB=1` | disable the kill-on-close job object (M11 unmitigated control) |
| `RIGORLOOM_SPIKE_IGNORE_EOF=1` | sidecar ignores stdin EOF (M11 hostile-sidecar control) |
| `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--force-device-scale-factor=1.25` | M15 scale factors without touching the machine's display settings |

## Measurement scripts

All under `measure/`, all PowerShell except two Python helpers:

- `measure.ps1 -Mode startup|memory|orphan|tree` — general harness
- `orphan.ps1` — M10/M11, identifies *our* processes by image name and by the
  bundle identifier in the WebView2 command line, then polls for 30 s
- `memory.ps1` — M8/M9 by process identity (a ParentProcessId walk silently
  under-counted WebView2 hosts in an early run)
- `startup_matrix.ps1` — M1/M2 across both packaging modes, reading the app's
  own timings from `%TEMP%\rigorloom-spike-timings.txt`
- `sidecar_ready.py` — frozen-sidecar spawn→ready, no Tauri involved
- `dpi_matrix.ps1` + `shot.ps1` — M15 screenshots (DPI-aware capture)
- `ime_keys.py` — sends **real scan codes** so the Windows IME composes. The
  desktop-automation tooling types by injecting Unicode, which bypasses the IME
  entirely and would have made M13 a false pass.

## What this harness does NOT do

No COM, no Hancom, no network. It never writes outside its own directory,
`%TEMP%`, and the screenshots folder.
