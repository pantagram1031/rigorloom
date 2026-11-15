"""``rigorloom style check FILE``: Korean phrasing worth a second look.

Each rule is a plain pattern with an id, a severity and a short reason. The
checker prints where each one matched (``file:line:col rule-id``) and exits 3
only when a rule marked ``error`` matched. Everything else is a notice: a
person reads it and decides. Most patterns here are common in careful human
writing too, so a notice is a question ("is this what you meant to say?"),
never a verdict on who wrote the text. Nothing here measures or targets any
detector.

The rules are versioned (``RULESET``). Changing a pattern, its severity or the
document types it applies to means a new version, so a stored result always
says which rules produced it.

Sources: 국립국어원's guidance on double passives and translated phrasing, and
research notes kept outside this repository on report style (paragraph
openers, sentence length, hedges) and on where such rules misfire across
genres. docs/korean-style-rules.md says which rule came from which, and lists
each rule with a positive and a negative example.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from .rt_guard import GuardInputError, read_paragraphs
except ImportError:  # run from the checkout as runtime/scripts/cli.py
    from rt_guard import GuardInputError, read_paragraphs

RULESET = "ko-style/1"  # bump on any rule change; see docs/korean-style-rules.md
STYLE_SCHEMA = "rigorloom/style-check-v1"
DOC_TYPES = ("report", "gongmun", "grant", "minwon", "contract", "any")
SEVERITIES = ("error", "notice")


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: str
    severity: str
    doc_types: tuple[str, ...]
    why: str
    suggest: str

    def regex(self) -> re.Pattern:
        return _compiled(self.pattern)


@lru_cache(maxsize=None)
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern)


ALL = ("report", "gongmun", "grant", "minwon", "contract")
PROSE = ("report", "grant")

RULES: tuple[Rule, ...] = (
    Rule("ko.double-passive", r"되어(?:지[다는고면며게지었]|진|짐|져|질)",
         "error", ALL,
         "이중 피동입니다. '되다'가 이미 피동이라 '-어지다'를 겹칠 필요가 없습니다.",
         "되어진 → 된, 되어집니다 → 됩니다"),
    Rule("ko.e-isseoseo", r"에\s?있어(?:서)?(?:는|도|의|,)",
         "notice", ALL,
         "일본어 '~において'를 옮긴 말투로 자주 쓰입니다.",
         "~에서, ~할 때, ~에 대해"),
    Rule("ko.e-dareum-anida", r"에\s?다름\s?아니",
         "notice", ALL,
         "일본어 '~に他ならない'를 옮긴 표현입니다.",
         "~이나 다름없다, 바로 ~이다"),
    Rule("ko.ji-anhumyeon-an-doenda", r"지\s?않으면\s?안\s?(?:된|됩|되)",
         "notice", ALL,
         "이중 부정으로 의무를 말하는 번역 투입니다.",
         "~해야 한다"),
    Rule("ko.hayeogeum", r"(?:으로|로)\s?하여금",
         "notice", ALL,
         "사동을 겹쳐 쓰는 번역 투입니다. 누가 무엇을 하는지 바로 쓰면 짧아집니다.",
         "A로 하여금 B하게 하다 → A가 B하도록 하다"),
    Rule("ko.e-uihae", r"에\s?의해(?:서)?\s",
         "notice", PROSE,
         "행위자를 '~에 의해'로 붙인 피동문입니다. 능동문이 더 분명할 때가 많습니다.",
         "연구진에 의해 개발된 → 연구진이 개발한"),
    Rule("ko.gajigo-itda", r"(?:을|를)\s?(?:가지고|갖고)\s?(?:있|있었)(?:다|습니다|는|으며|고)",
         "notice", PROSE,
         "영어 'have'를 옮긴 말투일 수 있습니다. 성질이나 특징이면 다른 서술어가 자연스럽습니다.",
         "장점을 가지고 있다 → 장점이 있다"),
    Rule("ko.geot-i-pilyohada", r"(?:하는|되는)\s?것이\s?(?:필요|중요)(?:하다|합니다|하며|하고)",
         "notice", PROSE,
         "명사절로 감싼 서술입니다. 동사로 바로 쓰면 짧고 분명해집니다.",
         "확인하는 것이 필요하다 → 확인해야 한다"),
    Rule("ko.para-opener-summary", r"^\s*(?:결론적으로|요약하자면|요약하면|종합하면|이처럼|이와 같이)[,\s]",
         "notice", ("report",),
         "문단을 정리 문구로 여는 형태입니다. 앞 내용을 되풀이하는 문단이 아닌지 확인하십시오.",
         "되풀이라면 문단을 줄이거나 새 근거로 시작"),
    Rule("ko.filler-opener", r"^\s*(?:또한|아울러|더불어|나아가)[,\s]",
         "notice", ("report", "grant"),
         "문단을 덧붙임 접속어로 여는 형태입니다. 앞 문단과 이어지는 내용이면 접속어 없이도 읽힙니다.",
         "접속어를 빼고 새 내용으로 바로 시작"),
    Rule("ko.contrast-frame", r"(?:이|가)\s?아니라\s?\S+(?:이다|입니다)[.]",
         "notice", ("report",),
         "'A가 아니라 B이다' 대조 틀입니다. 한 보고서에 여러 번 나오면 틀이 눈에 띕니다.",
         "B를 바로 주장하고 근거를 붙임"),
    Rule("ko.md-bold", r"\*\*[^*\n]*[가-힣][^*\n]*\*\*",
         "notice", ("report", "gongmun", "contract", "minwon"),
         "본문 굵게 표시입니다. 한글 양식 문서에서는 대개 서식으로 강조하지 않습니다.",
         "강조가 필요하면 문장으로"),
    Rule("ko.exclamation", r"[가-힣]\s?!",
         "notice", ("report", "gongmun", "contract", "minwon", "grant"),
         "공식 문서 본문의 느낌표입니다.",
         "마침표"),
)

_BY_ID = {r.id: r for r in RULES}
assert len(_BY_ID) == len(RULES), "rule ids must be unique"


class StyleInputError(ValueError):
    """The input cannot be checked (missing, unsupported, unreadable)."""


def rules_for(doc_type: str) -> list[Rule]:
    if doc_type not in DOC_TYPES:
        raise StyleInputError(f"unknown document type {doc_type!r}; "
                              f"use one of {', '.join(DOC_TYPES)}")
    if doc_type == "any":
        return list(RULES)
    return [r for r in RULES if doc_type in r.doc_types]


def _units(path: Path) -> tuple[str, list[str]]:
    """(unit, texts): lines for text files, paragraphs for .hwpx."""
    if path.suffix.lower() == ".hwpx":
        try:
            return "paragraph", read_paragraphs(path)
        except GuardInputError as exc:
            raise StyleInputError(str(exc)) from exc
    try:
        read_paragraphs(path)  # same size and type checks as guard
    except GuardInputError as exc:
        raise StyleInputError(str(exc)) from exc
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return "line", text.split("\n")


def check_text(units: list[str], rules: list[Rule]) -> list[dict]:
    findings = []
    in_fence = False
    for n, text in enumerate(units, start=1):
        if text.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for rule in rules:
            for m in rule.regex().finditer(text):
                findings.append({"line": n, "col": m.start() + 1,
                                 "rule": rule.id, "severity": rule.severity,
                                 "match": m.group(0).strip(),
                                 "why": rule.why, "suggest": rule.suggest})
    return findings


def check(path: Path, doc_type: str = "any") -> dict:
    rules = rules_for(doc_type)
    if not path.is_file():
        raise StyleInputError(f"{path.name}: no such file")
    unit, units = _units(path)
    findings = check_text(units, rules)
    errors = sum(1 for f in findings if f["severity"] == "error")
    return {"schema": STYLE_SCHEMA, "ruleset": RULESET, "file": path.name,
            "docType": doc_type, "unit": unit,
            "rulesApplied": [r.id for r in rules],
            "pass": errors == 0,
            "counts": {"error": errors, "notice": len(findings) - errors},
            "findings": findings}


def format_lines(result: dict, shown_path: str) -> str:
    out = []
    for f in result["findings"]:
        out.append(f"{shown_path}:{f['line']}:{f['col']}: {f['severity']} "
                   f"{f['rule']}: {f['match']} -- {f['why']} ({f['suggest']})")
    c = result["counts"]
    out.append(f"{result['ruleset']} ({result['docType']}, per {result['unit']}): "
               f"{c['error']} error, {c['notice']} notice")
    return "\n".join(out) + "\n"
