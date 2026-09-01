#!/usr/bin/env python3
"""rigorloomd — throwaway JSONL-over-stdio sidecar for the desktop shell spike.

Not product code. It exists so the spike measures a sidecar with the real
dependency graph (PyMuPDF is imported at module scope on purpose, because its
import cost is part of what M2 measures) rather than a hello-world.

Protocol: one JSON object per line on stdin, one JSON object per line on
stdout. stderr is logs only. EOF on stdin => exit 0 (this is the stdin-EOF
half of the M11 orphan mitigation).

ops:
  ping                      -> {ok:true, id}
  pid                       -> {ok:true, pid}
  echo   {n}                -> n lines of {ok:true, i, pad} (throughput probe)
  render_page {zoom}        -> {ok:true, png_b64} for a generated sample page
  open_path {path}          -> {ok:true, path, exists, bytes} (dialog round-trip)
  crash                     -> hard exit, no response (M12)
  quit                      -> {ok:true} then exit
"""
import base64
import json
import os
import sys
import time

import fitz  # PyMuPDF — imported eagerly: its cost belongs to sidecar-ready time.


def log(msg):
    print(f"[rigorloomd] {msg}", file=sys.stderr, flush=True)


def _sample_doc():
    """A text-dense two-page document, built in memory.

    Density matters: an almost-blank page compresses to a few tens of KiB and
    would make M5 (large payload) meaningless. A real report page is text-dense,
    so this one is too.
    """
    doc = fitz.open()
    for n in (1, 2):
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((72, 90), f"Rigorloom spike sample - page {n}",
                         fontsize=18)
        page.insert_text((72, 118), "form_inspect table_map / proof_grade",
                         fontsize=11)
        y = 150
        for i in range(42):
            page.insert_text(
                (72, y),
                f"{i:02d}  fill_target addr=[{i},3] charpr=12 script_anomaly=False "
                f"color_anomaly=False  proof_grade=advisory  needs=2",
                fontsize=9)
            y += 15
        page.draw_rect(fitz.Rect(66, 140, 529, y - 6), color=(0.6, 0.6, 0.6))
        for i in range(1, 42, 4):
            yy = 140 + i * 15
            page.draw_line(fitz.Point(66, yy), fitz.Point(529, yy),
                           color=(0.85, 0.85, 0.85))
    return doc


def handle(req):
    op = req.get("op")
    if op == "ping":
        return {"ok": True, "id": req.get("id")}
    if op == "pid":
        return {"ok": True, "pid": os.getpid()}
    if op == "open_path":
        path = req.get("path") or ""
        try:
            size = os.path.getsize(path)
            exists = True
        except OSError:
            size, exists = 0, False
        return {"ok": True, "path": path, "exists": exists, "bytes": size}
    if op == "render_page":
        zoom = float(req.get("zoom") or 1.5)
        t0 = time.perf_counter()
        doc = _sample_doc()
        pix = doc[int(req.get("page") or 0)].get_pixmap(
            matrix=fitz.Matrix(zoom, zoom))
        png = pix.tobytes("png")
        doc.close()
        return {"ok": True, "png_b64": base64.b64encode(png).decode("ascii"),
                "bytes": len(png), "ms": round((time.perf_counter() - t0) * 1000, 2)}
    if op == "crash":
        log("crash requested — exiting hard")
        os._exit(9)
    if op == "quit":
        return {"ok": True, "bye": True}
    return {"ok": False, "error": f"unknown op {op!r}"}


def main():
    # Binary-safe line IO; never let a Windows console codepage kill us.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    log(f"ready pid={os.getpid()} python={sys.version.split()[0]} fitz={fitz.__doc__ and 'ok'}")
    # Spike bookkeeping: prove which env the sidecar actually inherited from the
    # Tauri shell (tauri-plugin-shell could sanitise it) before drawing any
    # conclusion from the M11 control arm.
    try:
        import tempfile
        with open(os.path.join(tempfile.gettempdir(),
                               "rigorloomd-spike-env.txt"), "a",
                  encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} "
                     f"IGNORE_EOF={os.environ.get('RIGORLOOM_SPIKE_IGNORE_EOF')!r} "
                     f"at={time.strftime('%H:%M:%S')}\n")
    except OSError:
        pass
    print(json.dumps({"ok": True, "event": "ready", "pid": os.getpid()}),
          flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": f"bad json: {exc}"}),
                  flush=True)
            continue

        if req.get("op") == "echo":
            n = int(req.get("n") or 1)
            pad = "x" * int(req.get("pad") or 80)
            out = sys.stdout
            for i in range(n):
                out.write(json.dumps({"ok": True, "i": i, "pad": pad}) + "\n")
            out.flush()
            continue

        try:
            resp = handle(req)
        except Exception as exc:  # throwaway: never die on a bad request
            resp = {"ok": False, "error": repr(exc)}
        resp.setdefault("id", req.get("id"))
        print(json.dumps(resp), flush=True)
        if resp.get("bye"):
            break

    # M11 control arm: with RIGORLOOM_SPIKE_IGNORE_EOF=1 the sidecar refuses to
    # notice that its parent is gone, which is how a naive sidecar behaves. The
    # spike measures both so we know whether stdin-EOF is doing the work or the
    # OS is.
    if os.environ.get("RIGORLOOM_SPIKE_IGNORE_EOF") == "1":
        log("stdin closed — IGNORING (naive control arm), sleeping forever")
        while True:
            time.sleep(5)

    log("stdin closed — exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
