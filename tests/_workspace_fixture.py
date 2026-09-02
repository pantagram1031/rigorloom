# -*- coding: utf-8 -*-
"""A report workspace to run the real workspace checkers against.

Helper, not a test module — same convention as ``tests/_module_gating.py``.

**THIS IS ASSEMBLED, AND THE ASSEMBLY IS THE DISCLOSURE.** There is no complete
report workspace in this checkout and there is not supposed to be one: a
workspace holds a person's report, ``examples/workspace/README.md`` says to
create a real one with ``scripts/new_report.py`` and ``.gitignore`` keeps them
out. So this is not "the corpus" and must never be called that. It is a
workspace built out of two kinds of repo-owned pieces, named here one by one:

**Made by the product, not by this file.** The skeleton — ``PIPELINE.md``,
``.pipeline/handoff.json``, ``.pipeline/artifacts.json``, ``events.jsonl``,
``WORKSPACE_INDEX.md``, ``NEXT_TASK.md``, ``work/stage-0/`` and the canonical
directories — is written by ``modules/report/scripts/pipeline_ctl.py init``,
resolved through the module registry the way ``scripts/new_report.py`` resolves
it. ``request.yaml``, ``build.yaml`` and ``APPROVALS.md`` come from
``new_report``'s own template functions, imported rather than retyped, against
the real corpus form the rest of the runtime suite uses. Nothing in that half
is a guess about what a workspace looks like; it is what the scaffolder makes.

**Copied from this repository's own checker tests.** The stage-4-and-later
content, which a scaffolder does not write because a person writes it:

| part | taken from |
| --- | --- |
| ``bundle/content.md`` | ``modules/report/tests/test_verify_content.py`` (its clean-content case) |
| ``bundle/figures/plot1.png`` | the same test's ``add_figure`` bytes |
| ``claims.yaml`` | ``modules/report/tests/test_check_claims.py::_write_claims`` |
| ``research/sources.json`` | the source ids that ledger cites, so it resolves |
| ``output/QUESTIONS.md`` | ``modules/report/tests/test_check_understanding.py`` |
| ``output/scorecard.json`` | ``modules/report/tests/test_check_scorecard.py::passing_scorecard`` |
| ``_saeteuk/notes.md`` | prose written here, because that artifact is a person's |

A verdict from this fixture is therefore evidence that the WIRE works — that a
workspace checker receives a workspace, reads it, and returns a verdict the
Runtime normalizes correctly. It is not evidence about report quality, and no
number out of it belongs in a quality claim.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_FORM = (REPO_ROOT / "tests" / "corpus" / "forms" / "converted"
               / "gianmun-byeolji-1ho.hwpx")

#: modules/report/tests/test_verify_content.py, the clean-content case.
CONTENT_MD = """# 서론

이 글은 감쇠 진동에서 에너지가 어떻게 줄어드는지를 측정한 기록이다. 여러 조건에서
값이 안정적으로 나타났고, 각 조건의 차이는 표에 정리하였다.

[[FIG file="plot1.png"]]

## 방법

측정은 같은 장치에서 세 번 반복하였다. 관측값은 표에 정리하였고 해석은 본문에서
다룬다.

## 결과

감쇠 계수는 0.42 로 나타났다 [S1]. 초기 진폭은 12.0 cm 였다.

## 참고 문헌

- Example Author (2024). Synthetic source. Journal of Nothing.
"""

#: modules/report/tests/test_check_understanding.py, with the answers its
#: supervised-pass case appends.
QUESTIONS_MD = """# Stage 5.5 questions

1. **[derive]** Why does the integer index matter?
   What breaks in continuous time?
   Answer: This answer explains the report in my own words.

2. **[verify]** Why separate expected and measured values?
   Answer: This answer explains the report in my own words.

3. **[control]** Which variable stays fixed, and why?
   Answer: This answer explains the report in my own words.

4. **[limits]** Why is equality a boundary case?
   Answer: This answer explains the report in my own words.

5. **[next]** What question follows from this result?
   Answer: This answer explains the report in my own words.
"""

#: modules/report/tests/test_check_scorecard.py::passing_scorecard
SCORECARD = {
    "dimensions": {"logic": 9, "source_coverage": 8},
    "stop_lines": {
        "SENSITIVE_FRAMING": False,
        "LOAD_BEARING_DISPUTE": False,
        "UNSUPPORTED_NOVELTY": False,
    },
    "panelists": [{"name": "logic", "verdict": "pass", "findings": []}],
    "verdict": "approved",
}

#: modules/report/tests/test_check_claims.py::_write_claims / _evidence
CLAIMS = {
    "schema": "rigorloom-claims/v1",
    "claims": [
        {
            "id": "damping-coefficient",
            "text": "감쇠 계수는 0.42 이다.",
            "kind": "numeric",
            "evidence": [{"source_id": "S1", "locator": "section 2",
                          "quote": "Synthetic support."}],
        },
        {
            "id": "initial-amplitude",
            "text": "초기 진폭은 12.0 cm 이다.",
            "kind": "numeric",
            "evidence": [{"source_id": "S1", "locator": "section 3",
                          "quote": "Synthetic support."}],
        },
    ],
}

SOURCES = {
    "schema": "rigorloom-sources/v1",
    "sources": [
        {"id": "S1", "title": "Synthetic source", "author": "Example Author",
         "year": 2024, "kind": "journal"},
    ],
}

SAETEUK_MD = """감쇠 진동 탐구를 정리하면서, 감쇠 계수는 0.42 로 측정되었다는 점을
가장 먼저 적어 두었다. 초기 진폭은 12.0 cm 였다.
"""


def _new_report_module():
    """``scripts/new_report.py``, imported for its template functions.

    Imported rather than retyped so ``request.yaml`` and ``build.yaml`` here
    are the scaffolder's own text and cannot drift from it silently.
    """
    path = REPO_ROOT / "scripts" / "new_report.py"
    spec = importlib.util.spec_from_file_location("_new_report_for_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pipeline_ctl(modules_root: Path, enabled_file: Path) -> Path:
    """The report module's ``pipeline`` CLI, through the registry.

    Resolved the way ``scripts/new_report.py`` resolves it — by typed accessor,
    never by path — so the enablement this fixture uses is the test's own file
    and never the operator's.
    """
    scripts = REPO_ROOT / "pipeline" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from module_registry import ModuleRegistry  # noqa: PLC0415

    registry = ModuleRegistry(modules_root, enabled_file=enabled_file,
                              pyproject=REPO_ROOT / "pyproject.toml")
    for row in registry.enabled_cli():
        if row["command"] == "pipeline":
            return Path(row["script"])
    raise AssertionError("the enabled modules provide no 'pipeline' CLI; this "
                         "fixture needs the report distribution module")


def scaffold(target: Path, *, modules_root: Path, enabled_file: Path,
             slug: str = "e4fixture", mode: str = "supervised") -> Path:
    """The product's own skeleton, then the content a person would write."""
    new_report = _new_report_module()
    args = SimpleNamespace(topic="감쇠 진동의 에너지 소산 측정", subject="물리",
                           mode=mode, pages=[5, 12], min_figures=4)
    target.mkdir(parents=True, exist_ok=True)
    for relative in ("bundle/figures", "research", "sim", "figures", "output",
                     "refs", "archive"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    (target / "request.yaml").write_text(
        new_report._request_text(args, CORPUS_FORM), encoding="utf-8")
    (target / "build.yaml").write_text(
        new_report._build_text(args), encoding="utf-8")
    (target / "APPROVALS.md").write_text(
        new_report._approvals_text(), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(_pipeline_ctl(modules_root, enabled_file)),
         "init", str(target), "--slug", f"report-{slug}", "--mode", mode,
         "--subject", args.subject, "--topic", args.topic,
         "--form", str(CORPUS_FORM)],
        capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert completed.returncode == 0, (
        f"pipeline init failed ({completed.returncode}):\n"
        f"{completed.stdout}\n{completed.stderr}")

    fill(target)
    return target


def fill(target: Path) -> Path:
    """The stage-4-and-later content, from this repository's checker tests."""
    (target / "bundle" / "figures").mkdir(parents=True, exist_ok=True)
    (target / "bundle" / "content.md").write_text(CONTENT_MD, encoding="utf-8")
    (target / "bundle" / "figures" / "plot1.png").write_bytes(b"\x89PNG\r\n")
    (target / "claims.yaml").write_text(
        json.dumps(CLAIMS, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "research").mkdir(parents=True, exist_ok=True)
    (target / "research" / "sources.json").write_text(
        json.dumps(SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "output").mkdir(parents=True, exist_ok=True)
    (target / "output" / "QUESTIONS.md").write_text(QUESTIONS_MD, encoding="utf-8")
    (target / "output" / "scorecard.json").write_text(
        json.dumps(SCORECARD, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "_saeteuk").mkdir(parents=True, exist_ok=True)
    (target / "_saeteuk" / "notes.md").write_text(SAETEUK_MD, encoding="utf-8")
    return target


#: What the assembly is, in one place, so a report can quote it rather than
#: paraphrase it. Consumed by the tests and by the evidence run.
ASSEMBLY = {
    "scaffolded_by": "modules/report/scripts/pipeline_ctl.py init "
                     "(resolved through the module registry, as "
                     "scripts/new_report.py does)",
    "templates_from": "scripts/new_report.py (_request_text, _build_text, "
                      "_approvals_text), imported not retyped",
    "form": "tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx",
    "content_from": {
        "bundle/content.md": "modules/report/tests/test_verify_content.py",
        "bundle/figures/plot1.png": "modules/report/tests/test_verify_content.py",
        "claims.yaml": "modules/report/tests/test_check_claims.py",
        "research/sources.json": "written here to resolve the ledger's source id",
        "output/QUESTIONS.md": "modules/report/tests/test_check_understanding.py",
        "output/scorecard.json": "modules/report/tests/test_check_scorecard.py",
        "_saeteuk/notes.md": "written here; a saeteuk artifact is a person's text",
    },
    "not_a_corpus": ("assembled from repo-owned pieces; evidence about the "
                     "wire, never about report quality"),
}
