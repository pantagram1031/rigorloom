# -*- coding: utf-8 -*-
"""backend_precheck.py — deterministic model/CLI preflight (config-driven).

Pings each configured reviewer backend with a bounded trivial request and
records live/dead + version into run_capabilities.json. The orchestrator/council
MUST read this (not a static status field) to decide seats and fall back — so a
dead model is caught BEFORE a run relies on it.

Backends are declared in a --config YAML file (see references/backends.example.yaml).
There are NO hardcoded personal model/CLI specifics here; the example config
ships generic placeholders you copy and fill in privately.

Usage: python backend_precheck.py [--config backends.yaml] [--out run_capabilities.json] [--live]
  --live  actually issue each backend's live_cmd (slower); default does
          PATH/version checks only. Council quorum should require --live receipts.
"""
import sys, os, re, json, shutil, subprocess, argparse

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              os.pardir, "references", "backends.example.yaml")


def run(cmd, timeout, stdin=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           input=stdin, encoding="utf-8", errors="ignore")
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def ver_tuple(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _kv(d, s):
    if ":" not in s:
        return
    k, v = s.split(":", 1)
    k = k.strip()
    v = v.strip()
    if v.startswith("[") or v.startswith("{"):
        try:
            d[k] = json.loads(v)
            return
        except Exception:
            pass
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    d[k] = v


def load_backends(path):
    """Load the `backends:` list from a config file. Uses pyyaml if available,
    else a minimal block-YAML parser for the constrained schema (a list of maps
    whose values are scalars or JSON inline arrays). JSON files also accepted."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".json"):
        return json.loads(text).get("backends", [])
    try:
        import yaml  # optional dependency
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "backends" in data:
            return data["backends"]
    except Exception:
        pass
    backends, cur = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^backends:\s*$", line):
            continue
        m_item = re.match(r"^(\s*)-\s*(.*)$", line)
        if m_item:
            cur = {}
            backends.append(cur)
            rest = m_item.group(2)
            if rest:
                _kv(cur, rest)
            continue
        m_kv = re.match(r"^\s+(\S.*)$", line)
        if m_kv and cur is not None:
            _kv(cur, m_kv.group(1))
    return backends


def check_backend(be, live):
    name = be.get("name", "?")
    which = be.get("which")
    r = {"backend": name, "on_path": None}
    exe = shutil.which(which) if which else None
    r["on_path"] = bool(exe) if which else None
    if which and not exe:
        r["live"] = False
        r["note"] = f"{which} not on PATH"
        return r
    vc = be.get("version_cmd")
    if vc:
        _, out, err = run(vc, 40)
        blob = ((out or "") + " " + (err or "")).strip()
        r["version"] = blob
        minv = be.get("min_version")
        if minv:
            r["version_ok"] = ver_tuple(blob) >= ver_tuple(minv)
            if not r["version_ok"]:
                r["live"] = False
                r["note"] = f"{name} version < {minv}"
                return r
    if live:
        lc = be.get("live_cmd")
        if not lc:
            r["live"] = None
            r["note"] = "no live_cmd configured"
            return r
        code, out, _ = run(lc, int(be.get("live_timeout", 130)), stdin=be.get("live_stdin"))
        expect = be.get("expect", "PING_OK")
        r["live"] = (code == 0 and expect in out)
        r["exit"] = code
    else:
        r["live"] = None  # PATH/version ok but not live-tested
    return r


def main():
    ap = argparse.ArgumentParser(description="deterministic model/CLI preflight")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="backends YAML/JSON config (default: references/backends.example.yaml)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    try:
        backends_cfg = load_backends(a.config)
    except OSError as e:
        print(json.dumps({"ok": False, "error": f"config unreadable: {e}"}, ensure_ascii=False))
        sys.exit(2)
    results = [check_backend(be, a.live) for be in backends_cfg]
    live_ok = [b for b in results if b.get("live") is True]
    caps = {
        "backends": results,
        "reviewers_live": len(live_ok),
        # council fallback policy: need >=1 live external seat; otherwise the
        # orchestrator degrades to distinct-lens in-session review.
        "council_mode": ("dual-pool" if len(live_ok) >= 1 else "degraded-single-pool"),
    }
    js = json.dumps(caps, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js)
    print(js)
    # exit 0 always (informational); the council runner decides seating from council_mode
    sys.exit(0)


if __name__ == "__main__":
    main()
