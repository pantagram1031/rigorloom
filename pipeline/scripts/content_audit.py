# -*- coding: utf-8 -*-
"""content_audit.py — composite content gate for stage 4.5.

Runs the two deterministic content checkers as subprocesses and combines their
verdicts:
  1. verify_content.py <WS>   (web-citation / polite-ending / figure / leak)
  2. check_style.py <WS>      (prose banned-patterns / signature caps / citation)

When --profile-root <p> is given, pack files are resolved from it and forwarded:
  <p>/packs/gloss_allowlist.json  -> verify_content --allowlist  (terms extracted
        to a temp one-term-per-line file, since --allowlist takes a term list)
  <p>/packs/prose_rules.json      -> check_style --pack
  <p>/packs/report_structure.json -> check_style --structure-pack
A missing pack file simply falls back to that checker's own neutral default.

Combined verdict: worst exit wins (3 hard > 2 usage > 0 pass). Findings from
both sub-checkers are merged (each tagged with its source checker) into one JSON
verdict printed to stdout. This is the argv bound to the content_audit gate in
stages.yaml.

Exit 0 = pass, 3 = HARD violation(s), 2 = a sub-checker usage error.
"""
import sys, os, json, argparse, subprocess, tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent


def _worst(codes):
    """3 (hard) is the most severe, then 2 (usage), then 0 (pass)."""
    order = {3: 3, 2: 2, 0: 1}
    ranked = sorted(codes, key=lambda c: order.get(c, 2), reverse=True)
    return ranked[0] if ranked else 0


def _run(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    try:
        verdict = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        verdict = {"ok": False, "error": "sub-checker produced non-JSON stdout",
                   "raw": (proc.stdout or "")[:400], "stderr": (proc.stderr or "")[:400]}
    return verdict, proc.returncode


def _gloss_terms_tempfile(pack_path):
    """Extract terms[] from a gloss_allowlist pack and write them one-per-line
    to a temp file suitable for verify_content --allowlist. Returns the path
    (caller unlinks) or None if no usable terms."""
    try:
        sys.path.insert(0, str(_SCRIPTS_DIR))
        import personalization_ctl
        pack = personalization_ctl.load_pack_file(Path(pack_path))
    except Exception:
        return None
    terms = pack.get("terms") if isinstance(pack, dict) else None
    if not terms:
        return None
    fd, path = tempfile.mkstemp(prefix="gloss_allow_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for t in terms:
            f.write(f"{t}\n")
    return path


def check(ws, profile_root=None):
    packs_dir = Path(profile_root) / "packs" if profile_root else None
    py = sys.executable

    # --- verify_content ------------------------------------------------------
    vc_argv = [py, str(_SCRIPTS_DIR / "verify_content.py"), ws]
    gloss_tmp = None
    if packs_dir:
        gloss = packs_dir / "gloss_allowlist.json"
        if gloss.exists():
            gloss_tmp = _gloss_terms_tempfile(gloss)
            if gloss_tmp:
                vc_argv += ["--allowlist", gloss_tmp]
    try:
        vc_verdict, vc_code = _run(vc_argv)

        # --- check_style -----------------------------------------------------
        cs_argv = [py, str(_SCRIPTS_DIR / "check_style.py"), ws]
        if packs_dir:
            prose = packs_dir / "prose_rules.json"
            if prose.exists():
                cs_argv += ["--pack", str(prose)]
            structure = packs_dir / "report_structure.json"
            if structure.exists():
                cs_argv += ["--structure-pack", str(structure)]
        if gloss_tmp:
            # same allowlist exempts gloss-style banned patterns (e.g. "(dB)")
            cs_argv += ["--allowlist", gloss_tmp]
        cs_verdict, cs_code = _run(cs_argv)
    finally:
        if gloss_tmp and os.path.exists(gloss_tmp):
            os.unlink(gloss_tmp)

    hard, warn = [], []
    for name, verdict in (("verify_content", vc_verdict), ("check_style", cs_verdict)):
        for h in verdict.get("hard", []) or []:
            hard.append({"source": name, **h})
        for w in verdict.get("warn", []) or []:
            warn.append({"source": name, **w})
        err = verdict.get("error")
        if err:
            hard.append({"source": name, "code": "USAGE", "msg": err})

    code = _worst([vc_code, cs_code])
    verdict = {
        "ok": code == 0,
        "workspace": ws,
        "checker": "content_audit",
        "sub_exit": {"verify_content": vc_code, "check_style": cs_code},
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if code == 0 else ("fail" if code == 3 else "usage_error"),
    }
    return verdict, code


def main():
    ap = argparse.ArgumentParser(description="composite stage 4.5 content gate")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--profile-root", default=None,
                    help="personalization profile root; packs/*.json forwarded to sub-checkers")
    ap.add_argument("--out", default=None, help="write combined verdict JSON here")
    a = ap.parse_args()
    v, code = check(a.workspace, profile_root=a.profile_root)
    js = json.dumps(v, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js)
    print(js)
    sys.exit(code)



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    main()
