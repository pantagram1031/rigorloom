#!/usr/bin/env bash
# Freeze the spike sidecar, both packaging modes. Run from spikes/shell-tauri/.
#
# Interpreter is PINNED to the non-Store CPython 3.12 (docs/desktop-shell-spike.md
# §2 and the Decision section): the PATH default is a Microsoft Store build,
# which PyInstaller cannot freeze from, and C:\Python313 on this machine turned
# out to be a partial install with no Lib/ — it cannot create a venv at all.
#
# --noconsole (windowed) is the shipping-realistic mode: a --console sidecar
# drags a conhost.exe into the process tree. It also changes M11 behaviour --
# see the Decision section. Do not switch back to --console casually.
set -euo pipefail
cd "$(dirname "$0")"

PY=./.venv/Scripts/python.exe
TRIPLE=x86_64-pc-windows-msvc

"$PY" -c "import sys;print('freezing with', sys.version)"

common=(--noconfirm --clean --noconsole
        --specpath build-spec rigorloomd.py)

"$PY" -m PyInstaller "${common[@]:0:3}" --onefile --name rigorloomd-onefile \
  --distpath dist-onefile --workpath build-onefile \
  --specpath build-spec rigorloomd.py

"$PY" -m PyInstaller "${common[@]:0:3}" --onedir --name rigorloomd-onedir \
  --distpath dist-onedir --workpath build-onedir \
  --specpath build-spec rigorloomd.py

# The console variant exists only as the M11 control arm (see Decision §M11).
"$PY" -m PyInstaller --noconfirm --clean --console --onefile \
  --name rigorloomd-console --distpath dist-onefile --workpath build-onefile \
  --specpath build-spec rigorloomd.py

mkdir -p ../src-tauri/binaries
cp dist-onefile/rigorloomd-onefile.exe \
   "../src-tauri/binaries/rigorloomd-$TRIPLE.exe"

echo "--- sizes (bytes) ---"
du -sb dist-onefile/rigorloomd-onefile.exe \
       dist-onefile/rigorloomd-console.exe \
       dist-onedir/rigorloomd-onedir
