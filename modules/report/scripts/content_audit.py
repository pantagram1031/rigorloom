# -*- coding: utf-8 -*-
"""content_audit.py — composite content gate for stage 4.5.

Runs nine deterministic content checkers in-process and combines their
verdicts:
  1. verify_content.check       (web-citation / polite-ending / figure / leak)
  2. check_style.check          (prose banned-patterns / signature caps / citation)
  3. check_numbers.check        (body numerals / RNG provenance)
  4. check_refs.check           (advisory figure/table numbering / xrefs)
  5. check_figdata.check        (referenced PNG checksum integrity)
  6. check_sources.check        (offline citation-reality verification)
  7. check_units.check          (advisory unit/dimension consistency)
  8. check_saeteuk.check        (advisory early saeteuk consistency mirror)
  9. check_claims.check         (claim-ledger evidence traceability)

Stage 4.5 is early discovery: valid check_saeteuk HARD findings are demoted to
WARN here. Stage 6 remains the full enforcement authority for those findings.

When --profile-root <p> is given, pack files are resolved from it and forwarded.
When the option is absent, a valid directory named by RIGORLOOM_PROFILE_ROOT is
used instead. All recognized JSON packs are schema-validated before the
forwarded subset reaches the content checkers. A missing pack file falls back
to that checker's neutral default. The resolved profile root is also forwarded
to check_sources for its offline cache/sources lookup.
When RIGORLOOM_REQUIRE_LEDGER is truthy, check_claims runs in strict mode.

Combined verdict: worst effective exit wins (3 hard > 2 usage > 0 pass). Any
exception, invalid return, or unexpected exit is normalized to hard failure so
it cannot pass silently. Findings are tagged with their source checker.

Exit 0 = pass, 3 = HARD violation(s), 2 = a sub-checker usage error.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

# Module-script import mechanism (see modules/README.md): sibling scripts via
# the module scripts dir, core helpers via the core pipeline/scripts dir.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_CORE_SCRIPTS_DIR = _SCRIPTS_DIR.parents[2] / "pipeline" / "scripts"
for _dir in (_CORE_SCRIPTS_DIR, _SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_figdata  # noqa: E402
import check_claims  # noqa: E402
import check_numbers  # noqa: E402
import check_refs  # noqa: E402
import check_saeteuk  # noqa: E402
import check_sources  # noqa: E402
import check_units  # noqa: E402
import personalization_ctl  # noqa: E402
import verify_content  # noqa: E402
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    usage_error,
    verdict_skeleton,
)


def _resolve_check_style():
    """Resolve the 'check_style' checker without a module->module import.

    check_style is style-module payload (v0.16 W4.2) and module->module
    imports are not in the distribution-module contract, so content_audit
    looks the checker up through the registry (by checker name, never by
    module name) and loads it from the registered script path. In a
    flattened skill install (module scripts synced beside core scripts) the
    plain sibling import works instead. Unresolvable = None; check() then
    refuses loudly (exit 2) — this composite gate stays fail-closed, never
    silently thinner.
    """
    try:
        from module_registry import ModuleError, ModuleRegistry
        for row in ModuleRegistry().enabled_checkers():
            if row["name"] == "check_style":
                spec = importlib.util.spec_from_file_location(
                    "check_style", row["script"])
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    except (ModuleError, OSError, ImportError):
        pass
    try:
        import check_style  # flattened install layout
        return check_style
    except ImportError:
        return None


check_style = _resolve_check_style()

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


def _environment_truthy(name):
    value = os.environ.get(name)
    return bool(
        value and value.strip().casefold() in {"1", "true", "yes", "on"}
    )


def _worst(codes):
    """3 (hard) is the most severe, then 2 (usage), then 0 (pass)."""
    order = {3: 3, 2: 2, 0: 1}
    normalized = [code if code in order else 3 for code in codes]
    ranked = sorted(normalized, key=lambda c: order[c], reverse=True)
    return ranked[0] if ranked else 0


def _run(name, checker, *args, **kwargs):
    """Call one checker and normalize every fail-open return to exit 3."""

    def invalid(message, *, exception=None):
        payload = {
            "ok": False,
            "verdict": "fail",
            "error": message,
            "hard": [],
            "warn": [],
            "_failure_code": "USAGE",
        }
        if exception is not None:
            payload["traceback"] = traceback.format_exc()[-1600:]
        return payload, 3

    try:
        result = checker(*args, **kwargs)
    except Exception as exc:
        return invalid(
            f"{type(exc).__name__}: {exc}",
            exception=exc,
        )

    if not isinstance(result, tuple) or len(result) != 2:
        return invalid("sub-checker must return (verdict_dict, code)")
    verdict, code = result
    if not isinstance(verdict, dict):
        return invalid("sub-checker verdict must be an object")
    expected = {
        0: (True, "pass"),
        2: (False, "usage_error"),
        3: (False, "fail"),
    }.get(code)
    if expected is None:
        return invalid(f"sub-checker returned unexpected exit {code}")
    expected_ok, expected_verdict = expected
    if (
        verdict.get("ok") is not expected_ok
        or verdict.get("verdict") != expected_verdict
        or (code == 0 and bool(verdict.get("hard")))
    ):
        return invalid("sub-checker exit is inconsistent with its JSON verdict")
    return verdict, code


def _gloss_terms(pack_path):
    """Return the two legacy allowlist views without creating a temp file."""
    try:
        pack = personalization_ctl.load_pack_file(Path(pack_path))
    except Exception:
        return set(), []
    return _gloss_terms_from_pack(pack)


def _gloss_terms_from_pack(pack):
    """Return checker-specific term views from resolved pack content."""
    terms = pack.get("terms") if isinstance(pack, dict) else None
    if not terms:
        return set(), []

    rendered = "".join(f"{term}\n" for term in terms)
    verify_terms = set()
    for raw in rendered.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if len(line) >= 2 and line[0] in "\"'" and line[-1] == line[0]:
            line = line[1:-1]
        if line:
            verify_terms.add(line)
    style_terms = [
        line.strip()
        for line in rendered.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return verify_terms, style_terms


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
    if check_style is None:
        # Fail-closed: the composite audit is defined to include the prose
        # style leg; running without it would be a silently thinner gate.
        return usage_error(
            ws, "content_audit",
            "checker 'check_style' is not available: no enabled distribution "
            "module provides it (enable the 'style' module, or install its "
            "scripts beside core)")
    profile_root = _resolve_profile_root(profile_root)
    packs_dir = Path(profile_root) / "packs" if profile_root else None
    checker_names = (
        "verify_content",
        "check_style",
        "check_numbers",
        "check_refs",
        "check_figdata",
        "check_sources",
        "check_units",
        "check_saeteuk",
        "check_claims",
    )

    pack_findings = _validate_operator_packs(packs_dir) if packs_dir else []
    resolved_packs = None
    if profile_root and not pack_findings:
        try:
            resolved_packs = personalization_ctl.resolve_pack_set(
                Path(profile_root), None, None
            )["contents"]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            pack_findings.append({
                "source": "content_audit",
                "code": "extension_pack_invalid",
                "msg": "installed extension pack failed integrity validation",
                "at": str(Path(profile_root) / "extensions"),
                "errors": [str(exc)],
            })
    if pack_findings:
        verdict = verdict_skeleton(
            ws,
            "content_audit",
            hard=pack_findings,
            warn=[],
            extra={"sub_exit": {name: None for name in checker_names}},
        )
        return verdict, 3

    if resolved_packs is not None:
        verify_gloss_terms, style_gloss_terms = _gloss_terms_from_pack(
            resolved_packs["gloss_allowlist"]
        )
    else:
        verify_gloss_terms, style_gloss_terms = _gloss_terms(
            check_style.DEFAULT_GLOSS_PACK
        )

    def run_style():
        prose_pack = (resolved_packs["prose_rules"] if resolved_packs is not None
                      else check_style._load_pack(None, check_style.DEFAULT_PROSE_PACK))
        structure_pack = (resolved_packs["report_structure"]
                          if resolved_packs is not None else None)
        return check_style.check(
            ws,
            prose_pack=prose_pack,
            structure_pack=structure_pack,
            allow_terms=style_gloss_terms,
        )

    def run_numbers():
        number_allow = _number_allowlist_path(profile_root)
        if number_allow is None:
            # Preserve the old subprocess CLI's inherited-environment fallback.
            number_allow = check_numbers._environment_allowlist_path()
        try:
            allowed = check_numbers.load_allowlist(number_allow)
            constants = (resolved_packs["constants_allowlist"]
                         if resolved_packs is not None
                         else check_numbers.load_constants_allowlist(None))
        except (OSError, ValueError) as exc:
            return check_numbers._usage(
                ws, f"allowlist unreadable: {exc}"
            )
        return check_numbers.check(
            ws,
            allowed_numbers=allowed,
            require_seed=True,
            constants=constants,
        )

    results = [
        (
            "verify_content",
            *_run(
                "verify_content",
                verify_content.check,
                ws,
                allow_gloss=verify_gloss_terms,
            ),
        ),
        ("check_style", *_run("check_style", run_style)),
        ("check_numbers", *_run("check_numbers", run_numbers)),
        ("check_refs", *_run("check_refs", check_refs.check, ws)),
        ("check_figdata", *_run("check_figdata", check_figdata.check, ws)),
        (
            "check_sources",
            *_run(
                "check_sources",
                check_sources.check,
                ws,
                profile_root=profile_root,
            ),
        ),
        ("check_units", *_run("check_units", check_units.check, ws)),
        (
            "check_saeteuk",
            *_run("check_saeteuk", check_saeteuk.check, ws),
        ),
        (
            "check_claims",
            *_run(
                "check_claims",
                check_claims.check,
                ws,
                require_ledger=_environment_truthy(
                    "RIGORLOOM_REQUIRE_LEDGER"
                ),
            ),
        ),
    ]

    hard, warn = [], []
    effective_codes = []
    sub_exit = {}
    for name, sub_verdict, sub_code in results:
        sub_exit[name] = sub_code
        advisory_saeteuk = name == "check_saeteuk"
        for finding in sub_verdict.get("hard", []) or []:
            tagged = {"source": name, **finding}
            if advisory_saeteuk:
                tagged["severity"] = "WARN"
                warn.append(tagged)
            else:
                hard.append(tagged)
        for finding in sub_verdict.get("warn", []) or []:
            warn.append({"source": name, **finding})

        error = sub_verdict.get("error")
        if error:
            finding = {
                "source": name,
                "code": sub_verdict.get("_failure_code", "USAGE"),
                "msg": error,
            }
            for field in ("traceback", "stderr", "raw"):
                if sub_verdict.get(field):
                    finding[field] = sub_verdict[field]
            if advisory_saeteuk:
                # The 4.5 saeteuk run is an early-discovery mirror; its own
                # crash/usage failure must not block the cheap-edit stage.
                # Stage 6 re-runs the same check with full HARD authority,
                # so fail-closed enforcement is preserved there.
                finding["severity"] = "WARN"
                warn.append(finding)
            else:
                hard.append(finding)

        if advisory_saeteuk:
            effective_codes.append(0)
        else:
            effective_codes.append(sub_code)

    code = _worst(effective_codes)
    verdict = verdict_skeleton(
        ws,
        "content_audit",
        hard=hard,
        warn=warn,
        extra={"sub_exit": sub_exit},
        ok=code == 0,
        verdict=(
            "pass" if code == 0
            else ("fail" if code == 3 else "usage_error")
        ),
    )
    return verdict, code


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="composite stage 4.5 content gate"
    )
    parser.add_argument(
        "workspace",
        help="report workspace dir (…/workspaces/report-<slug>)",
    )
    parser.add_argument(
        "--profile-root",
        default=None,
        help=(
            "personalization profile root; packs/*.json forwarded to "
            "sub-checkers (default: valid RIGORLOOM_PROFILE_ROOT)"
        ),
    )
    parser.add_argument(
        "--out", default=None, help="write combined verdict JSON here"
    )
    return cli_main(
        parser,
        lambda args: check(
            args.workspace, profile_root=args.profile_root
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
