# -*- coding: utf-8 -*-
"""content_audit.py — composite content gate for stage 4.5.

Runs the five deterministic content checkers as subprocesses and combines their
verdicts:
  1. verify_content.py <WS>   (web-citation / polite-ending / figure / leak)
  2. check_style.py <WS>      (prose banned-patterns / signature caps / citation)
  3. check_numbers.py --require-seed <WS> (body numerals / RNG provenance)
  4. check_refs.py <WS>       (advisory figure/table numbering / xrefs)
  5. check_figdata.py <WS>    (referenced PNG checksum integrity)

When --profile-root <p> is given, pack files are resolved from it and forwarded.
When the option is absent, a valid directory named by
RIGORLOOM_PROFILE_ROOT is used instead:
  <p>/packs/gloss_allowlist.json  -> verify_content --allowlist  (terms extracted
        to a temp one-term-per-line file, since --allowlist takes a term list)
  <p>/packs/prose_rules.json      -> check_style --pack
  <p>/packs/report_structure.json -> check_style --structure-pack
  <p>/packs/numeral_allowlist.txt -> check_numbers --allow
All recognized JSON packs, including figure_style, are schema-validated before
the forwarded subset reaches the content checkers. A missing pack file simply
falls back to that checker's own neutral default.

Combined verdict: worst exit wins (3 hard > 2 usage > 0 pass). Any unexpected
nonzero sub-checker exit is normalized to hard failure so it cannot be silently
ignored. Findings from all five sub-checkers are merged (each tagged with its
source checker) into one JSON verdict printed to stdout. This is the argv bound
to the content_audit gate in stages.yaml.

Exit 0 = pass, 3 = HARD violation(s), 2 = a sub-checker usage error.
"""
import sys, os, json, argparse, subprocess, tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import personalization_ctl

_VALIDATED_PACKS = tuple(personalization_ctl.PACK_TYPES)


def _resolve_profile_root(profile_root):
    """Prefer an explicit root; otherwise accept a valid environment root."""
    if profile_root is not None:
        return Path(profile_root)
    configured = os.environ.get("RIGORLOOM_PROFILE_ROOT")
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    return candidate if candidate.is_dir() else None


def _worst(codes):
    """3 (hard) is the most severe, then 2 (usage), then 0 (pass)."""
    order = {3: 3, 2: 2, 0: 1}
    normalized = [code if code in order else 3 for code in codes]
    ranked = sorted(normalized, key=lambda c: order[c], reverse=True)
    return ranked[0] if ranked else 0


def _run(argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    stdout = proc.stdout or ""
    stderr = (proc.stderr or "")[:400]
    try:
        verdict = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        verdict = {"ok": False, "error": "sub-checker produced non-JSON stdout",
                   "raw": stdout[:400], "stderr": stderr}
    if not stdout.strip() and proc.returncode != 0:
        verdict = {
            "ok": False,
            "error": (
                f"sub-checker exited {proc.returncode} without JSON stdout"
            ),
        }
        if stderr:
            verdict["stderr"] = stderr
    return verdict, proc.returncode


def _gloss_terms_tempfile(pack_path):
    """Extract terms[] from a gloss_allowlist pack and write them one-per-line
    to a temp file suitable for verify_content --allowlist. Returns the path
    (caller unlinks) or None if no usable terms."""
    try:
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


def _number_allowlist_path(profile_root):
    """Return the first numeric allowlist supported by a private profile."""
    if not profile_root:
        return None
    root = Path(profile_root)
    candidates = (
        root / "packs" / "numeral_allowlist.txt",
        root / "packs" / "numeral_allowlist.json",
        root / "packs" / "number_allowlist.txt",
        root / "packs" / "number_allowlist.json",
        root / "numeral_allowlist.txt",
        root / "number_allowlist.txt",
    )
    return next((path for path in candidates if path.is_file()), None)


def _validate_operator_packs(packs_dir):
    """Validate every existing operator pack before any checker sees it."""
    findings = []
    for pack_type in _VALIDATED_PACKS:
        path = packs_dir / f"{pack_type}.json"
        if not path.exists():
            continue
        try:
            pack = personalization_ctl.load_pack_file(path)
            errors = personalization_ctl.validate_instance(
                pack, personalization_ctl.pack_schema(pack_type))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors = [f"pack could not be validated: {exc}"]
        if errors:
            findings.append({
                "source": "content_audit",
                "code": "pack_schema_invalid",
                "msg": f"operator preference pack failed schema validation: {pack_type}",
                "at": str(path),
                "errors": errors,
            })
    return findings


def check(ws, profile_root=None):
    profile_root = _resolve_profile_root(profile_root)
    packs_dir = Path(profile_root) / "packs" if profile_root else None
    py = sys.executable

    pack_findings = _validate_operator_packs(packs_dir) if packs_dir else []
    if pack_findings:
        return {
            "ok": False,
            "workspace": ws,
            "checker": "content_audit",
            "sub_exit": {"verify_content": None, "check_style": None,
                         "check_numbers": None, "check_refs": None,
                         "check_figdata": None},
            "hard": pack_findings,
            "warn": [],
            "counts": {"hard": len(pack_findings), "warn": 0},
            "verdict": "fail",
        }, 3

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

        # --- check_numbers --------------------------------------------------
        cn_argv = [py, str(_SCRIPTS_DIR / "check_numbers.py"),
                   "--require-seed", ws]
        number_allow = _number_allowlist_path(profile_root)
        if number_allow:
            cn_argv += ["--allow", str(number_allow)]
        cn_verdict, cn_code = _run(cn_argv)

        # --- check_refs -----------------------------------------------------
        cr_argv = [py, str(_SCRIPTS_DIR / "check_refs.py"), ws]
        cr_verdict, cr_code = _run(cr_argv)

        # --- check_figdata --------------------------------------------------
        cf_argv = [py, str(_SCRIPTS_DIR / "check_figdata.py"), ws]
        cf_verdict, cf_code = _run(cf_argv)
    finally:
        if gloss_tmp and os.path.exists(gloss_tmp):
            os.unlink(gloss_tmp)

    hard, warn = [], []
    for name, verdict in (("verify_content", vc_verdict), ("check_style", cs_verdict),
                          ("check_numbers", cn_verdict), ("check_refs", cr_verdict),
                          ("check_figdata", cf_verdict)):
        for h in verdict.get("hard", []) or []:
            hard.append({"source": name, **h})
        for w in verdict.get("warn", []) or []:
            warn.append({"source": name, **w})
        err = verdict.get("error")
        if err:
            finding = {"source": name, "code": "USAGE", "msg": err}
            if verdict.get("stderr"):
                finding["stderr"] = verdict["stderr"]
            if verdict.get("raw"):
                finding["raw"] = verdict["raw"]
            hard.append(finding)

    code = _worst([vc_code, cs_code, cn_code, cr_code, cf_code])
    verdict = {
        "ok": code == 0,
        "workspace": ws,
        "checker": "content_audit",
        "sub_exit": {"verify_content": vc_code, "check_style": cs_code,
                     "check_numbers": cn_code, "check_refs": cr_code,
                     "check_figdata": cf_code},
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
                    help=("personalization profile root; packs/*.json forwarded to "
                          "sub-checkers (default: valid RIGORLOOM_PROFILE_ROOT)"))
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
