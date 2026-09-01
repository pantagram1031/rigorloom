#!/usr/bin/env python3
"""Time a frozen sidecar from spawn to its first `ready` JSONL line.

Isolates the PyInstaller packaging cost (one-file self-extract vs one-dir) from
everything Tauri does, so the M2 number can be attributed correctly.

    python measure/sidecar_ready.py <exe> [runs]
"""
import json
import subprocess
import sys
import time


def once(exe):
    t0 = time.perf_counter()
    p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, bufsize=0)
    ready = None
    while True:
        line = p.stdout.readline()
        if not line:
            break
        try:
            obj = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if obj.get("event") == "ready":
            ready = (time.perf_counter() - t0) * 1000
            break
    try:
        p.stdin.write(b'{"op":"quit"}\n')
        p.stdin.flush()
        p.wait(timeout=10)
    except Exception:
        p.kill()
    return ready


def main():
    exe = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    vals = []
    for i in range(runs):
        ms = once(exe)
        vals.append(ms)
        print(f"  run {i + 1}: {ms:.0f} ms" if ms else f"  run {i + 1}: FAILED")
        time.sleep(1.0)
    ok = sorted(v for v in vals if v)
    if ok:
        print(f"{exe}\n  median {ok[len(ok) // 2]:.0f} ms  "
              f"min {ok[0]:.0f}  max {ok[-1]:.0f}  n={len(ok)}")


if __name__ == "__main__":
    main()
