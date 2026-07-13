#!/usr/bin/env python3
"""Create a private local writing profile for report humanization."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _ask(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "user-profile" / "writing_preferences.json")
    parser.add_argument("--profile-root", type=Path, default=ROOT / ".local" / "personalization")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--level", default="high-school")
    parser.add_argument("--register", default="formal-student-report")
    parser.add_argument("--first-person", default="reflection-only")
    parser.add_argument("--advanced-terms", default="explain-or-remove")
    parser.add_argument("--avoid", action="append", default=[])
    args = parser.parse_args()
    if not args.non_interactive:
        args.language = _ask("Report language", args.language)
        args.level = _ask("Academic level", args.level)
        args.register = _ask("Writing register", args.register)
        args.first_person = _ask("First-person policy", args.first_person)
        args.advanced_terms = _ask("Advanced-term policy", args.advanced_terms)
        extra = input("Expressions to avoid (comma-separated, optional): ").strip()
        if extra:
            args.avoid.extend(item.strip() for item in extra.split(",") if item.strip())
    profile = {
        "schema": "report-pipeline/writing-profile-v1",
        "language": args.language,
        "academic_level": args.level,
        "register": args.register,
        "first_person": args.first_person,
        "advanced_terms": args.advanced_terms,
        "avoid_patterns": args.avoid,
        "protected": ["numbers", "units", "source_ids", "equations", "document_tags", "headings", "uncertainty", "negation", "logical_direction"],
        "privacy": {"local_only": True, "use_generated_reports_as_style_evidence": False},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "pipeline" / "scripts" / "personalization_ctl.py"),
                             "--profile-root", str(args.profile_root), "init"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    writing = args.profile_root / "writing" / "profile.json"
    writing.parent.mkdir(parents=True, exist_ok=True)
    writing.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "profile": str(args.output.resolve()), "personalization": str(writing.resolve())}, ensure_ascii=False))
    return 0



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; output may contain
    non-ASCII. Reconfigure stdio so printing never dies with UnicodeEncodeError
    (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
