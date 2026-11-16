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

import json
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
PACK_NAMES = ("gongmun", "minwon", "hr", "grant")
PACK_BASE_DOC_TYPES = {
    "gongmun": "gongmun",
    "minwon": "minwon",
    "hr": "gongmun",
    "grant": "grant",
}


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


_PACK_ID_RE = re.compile(r"\A[a-z0-9-]+\.[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_REQUIRED_PACK_KEYS = ("pack", "version", "baseDocType", "note", "rules")
_REQUIRED_RULE_KEYS = (
    "id", "pattern", "severity", "why", "suggest", "positive", "negative", "source"
)
_REQUIRED_SOURCE_KEYS = ("title", "edition", "section", "page")


@dataclass(frozen=True)
class StylePack:
    pack: str
    version: str
    base_doc_type: str
    note: str
    rules: tuple[Rule, ...]
    raw_rules: tuple[dict, ...]


def _default_pack_dir() -> Path:
    here = Path(__file__).resolve().parent
    packaged = here / "style_packs"
    if packaged.is_dir():
        return packaged
    checkout = here.parent / "style_packs"
    if checkout.is_dir():
        return checkout
    return packaged


def _pack_error(pack_name: str, detail: str) -> StyleInputError:
    return StyleInputError(f"pack {pack_name!r}: {detail}")


def _parse_quantifier(pattern: str, index: int) -> tuple[int, int | None, int] | None:
    """Parse a regex quantifier at ``index`` -> ``(min_rep, max_rep, next_index)`` or None."""
    n = len(pattern)
    ch = pattern[index]
    if ch == "*":
        end = index + 1
        q_min, q_max = 0, None
    elif ch == "+":
        end = index + 1
        q_min, q_max = 1, None
    elif ch == "?":
        end = index + 1
        q_min, q_max = 0, 1
    elif ch == "{":
        m = re.match(r"\{(?:(\d+)|(\d*),(\d*))\}", pattern[index:])
        if m is None:
            return None
        if m.group(1) is not None:
            val = int(m.group(1))
            q_min, q_max = val, val
        else:
            s_min, s_max = m.group(2), m.group(3)
            if not s_min and not s_max:
                return None
            q_min = int(s_min) if s_min else 0
            q_max = int(s_max) if s_max else None
        end = index + m.end()
    else:
        return None
    if end < n and pattern[end] in "?+":
        end += 1
    return q_min, q_max, end


def _has_nested_quantifier(pattern: str) -> bool:
    """Return True if a variable-length quantifier is nested inside a repeating group."""
    # Each stack frame is [is_lookaround, has_var, is_verbose].
    stack: list[list[bool]] = [[False, False, False]]
    last_atom_has_var = False
    has_atom = False
    i = 0
    n = len(pattern)

    while i < n:
        ch = pattern[i]
        verbose = stack[-1][2]

        if verbose:
            if ch.isspace():
                i += 1
                continue
            if ch == "#":
                nl = pattern.find("\n", i + 1)
                i = n if nl == -1 else nl + 1
                continue

        if ch == "\\":
            if pattern.startswith("\\N{", i):
                close = pattern.find("}", i + 3)
                i = (i + 2) if close == -1 else (close + 1)
            else:
                i += 2 if i + 1 < n else 1
            last_atom_has_var = False
            has_atom = True
            continue

        if ch == "[":
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            while i < n and pattern[i] != "]":
                if pattern[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            if i < n:
                i += 1
            last_atom_has_var = False
            has_atom = True
            continue

        if ch == "(":
            if i + 1 < n and pattern[i + 1] == "?":
                if i + 2 < n and pattern[i + 2] == "#":
                    close = pattern.find(")", i + 3)
                    i = n if close == -1 else close + 1
                    continue
                if pattern.startswith(("(?=", "(?!"), i):
                    stack.append([True, False, verbose])
                    i += 3
                    last_atom_has_var = False
                    has_atom = False
                    continue
                if pattern.startswith(("(?<=", "(?<!"), i):
                    stack.append([True, False, verbose])
                    i += 4
                    last_atom_has_var = False
                    has_atom = False
                    continue
                if pattern.startswith(("(?:", "(?>"), i):
                    stack.append([False, False, verbose])
                    i += 3
                    last_atom_has_var = False
                    has_atom = False
                    continue
                if pattern.startswith("(?P=", i):
                    close = pattern.find(")", i + 4)
                    i = n if close == -1 else close + 1
                    last_atom_has_var = False
                    has_atom = True
                    continue
                if pattern.startswith("(?P<", i):
                    close = pattern.find(">", i + 4)
                    i = i + 4 if close == -1 else close + 1
                    stack.append([False, False, verbose])
                    last_atom_has_var = False
                    has_atom = False
                    continue
                if pattern.startswith("(?(", i):
                    close = pattern.find(")", i + 3)
                    i = i + 3 if close == -1 else close + 1
                    stack.append([False, False, verbose])
                    last_atom_has_var = False
                    has_atom = False
                    continue
                m_flags = re.match(r"\(\?([aiLmsux]+)(?:-([imsx]+))?([:)])", pattern[i:])
                if m_flags is not None:
                    add_f, rem_f, term = m_flags.groups()
                    new_verbose = verbose or ("x" in add_f)
                    if rem_f and "x" in rem_f:
                        new_verbose = False
                    i += m_flags.end()
                    if term == ")":
                        stack[-1][2] = new_verbose
                    else:
                        stack.append([False, False, new_verbose])
                        last_atom_has_var = False
                        has_atom = False
                    continue
            stack.append([False, False, verbose])
            i += 1
            last_atom_has_var = False
            has_atom = False
            continue

        if ch == ")":
            if len(stack) > 1:
                is_lookaround, group_has_var, _ = stack.pop()
                if is_lookaround:
                    last_atom_has_var = False
                else:
                    last_atom_has_var = group_has_var
                    if group_has_var:
                        stack[-1][1] = True
                has_atom = True
            i += 1
            continue

        if ch == "|":
            last_atom_has_var = False
            has_atom = False
            i += 1
            continue

        quant = _parse_quantifier(pattern, i)
        if quant is not None and has_atom:
            q_min, q_max, next_i = quant
            if (q_max is None or q_max > 1) and last_atom_has_var:
                return True
            if q_max is None or q_min != q_max:
                last_atom_has_var = True
                stack[-1][1] = True
            i = next_i
            continue

        if ch in "^$":
            last_atom_has_var = False
            has_atom = False
            i += 1
            continue

        last_atom_has_var = False
        has_atom = True
        i += 1

    return False


def _validate_rule_source(pack_name: str, rule_id: str, source: object, note: str) -> None:
    if source == "house":
        if "house" not in note.lower() and "자체" not in note:
            raise _pack_error(
                pack_name,
                f"rule {rule_id!r} uses 'house' source, so pack 'note' must mention house/자체",
            )
        return
    if not isinstance(source, dict):
        raise _pack_error(pack_name, f"rule {rule_id!r} source must be an object or 'house'")
    for key in _REQUIRED_SOURCE_KEYS:
        val = source.get(key)
        if not isinstance(val, str) or not val.strip():
            raise _pack_error(pack_name, f"rule {rule_id!r} source missing non-empty {key!r}")


def load_pack(pack_name: str, *, pack_dir: Path | None = None) -> StylePack:
    if not isinstance(pack_name, str) or not pack_name or "/" in pack_name or "\\" in pack_name:
        raise _pack_error(str(pack_name), "invalid pack name")
    if pack_dir is None and pack_name not in PACK_NAMES:
        raise _pack_error(
            pack_name,
            f"unknown rule pack; use one of {', '.join(PACK_NAMES)}",
        )
    base_dir = _default_pack_dir() if pack_dir is None else pack_dir
    pack_path = base_dir / f"{pack_name}.json"
    if not pack_path.is_file():
        raise _pack_error(pack_name, f"pack file not found: {pack_path}")
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _pack_error(pack_name, f"cannot parse pack JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise _pack_error(pack_name, "top-level JSON value must be an object")
    for key in _REQUIRED_PACK_KEYS:
        if key not in data:
            raise _pack_error(pack_name, f"missing top-level field {key!r}")
    if data["pack"] != pack_name:
        raise _pack_error(pack_name, f"top-level 'pack' mismatch: {data['pack']!r}")
    expected_version = f"{pack_name}/1"
    if data["version"] != expected_version:
        raise _pack_error(pack_name, f"version must be {expected_version!r}, got {data['version']!r}")
    base_doc_type = data["baseDocType"]
    if not isinstance(base_doc_type, str) or base_doc_type not in DOC_TYPES or base_doc_type == "any":
        raise _pack_error(pack_name, f"invalid baseDocType {base_doc_type!r}")
    expected_base = PACK_BASE_DOC_TYPES.get(pack_name)
    if expected_base is not None and base_doc_type != expected_base:
        raise _pack_error(
            pack_name,
            f"baseDocType must be {expected_base!r}, got {base_doc_type!r}",
        )
    note = data["note"]
    if not isinstance(note, str) or not note.strip():
        raise _pack_error(pack_name, "top-level 'note' must be a non-empty string")
    raw_rules = data["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise _pack_error(pack_name, "top-level 'rules' must be a non-empty list")

    loaded_rules: list[Rule] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise _pack_error(pack_name, f"rule at index {index} must be an object")
        for key in _REQUIRED_RULE_KEYS:
            if key not in raw:
                raise _pack_error(pack_name, f"rule at index {index} missing field {key!r}")
        for key in ("id", "pattern", "severity", "why", "suggest", "positive", "negative"):
            val = raw[key]
            if not isinstance(val, str) or not val.strip():
                raise _pack_error(pack_name, f"rule at index {index} field {key!r} must be a non-empty string")

        rid = raw["id"]
        if not rid.startswith(f"{pack_name}.") or not _PACK_ID_RE.fullmatch(rid):
            raise _pack_error(pack_name, f"invalid rule id {rid!r}; expected {pack_name}.<kebab-name>")
        if rid in _BY_ID or rid in seen_ids:
            raise _pack_error(pack_name, f"duplicate rule id {rid!r}")
        seen_ids.add(rid)

        severity = raw["severity"]
        if severity not in SEVERITIES:
            raise _pack_error(pack_name, f"rule {rid!r} has invalid severity {severity!r}")

        _validate_rule_source(pack_name, rid, raw["source"], note)

        try:
            compiled = re.compile(raw["pattern"])
        except (re.error, OverflowError, RecursionError, Exception) as exc:
            raise _pack_error(pack_name, f"rule {rid!r} regex failed to compile: {exc}") from exc

        if _has_nested_quantifier(raw["pattern"]):
            raise _pack_error(pack_name, f"rule {rid!r} pattern contains nested quantifiers")

        if compiled.search(raw["positive"]) is None:
            raise _pack_error(pack_name, f"rule {rid!r} pattern did not match positive example")
        if compiled.search(raw["negative"]) is not None:
            raise _pack_error(pack_name, f"rule {rid!r} pattern matched negative example")

        loaded_rules.append(
            Rule(rid, raw["pattern"], severity, (base_doc_type,), raw["why"], raw["suggest"])
        )

    return StylePack(
        pack=pack_name,
        version=expected_version,
        base_doc_type=base_doc_type,
        note=note,
        rules=tuple(loaded_rules),
        raw_rules=tuple(dict(r) for r in raw_rules),
    )


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


def check(path: Path, doc_type: str | None = None, pack: str | None = None) -> dict:
    if pack is not None:
        loaded = load_pack(pack)
        effective_doc_type = loaded.base_doc_type if doc_type is None else doc_type
        rules = rules_for(effective_doc_type) + list(loaded.rules)
        ruleset = f"{RULESET}+{loaded.version}"
    else:
        effective_doc_type = "any" if doc_type is None else doc_type
        rules = rules_for(effective_doc_type)
        ruleset = RULESET
    if not path.is_file():
        raise StyleInputError(f"{path.name}: no such file")
    unit, units = _units(path)
    findings = check_text(units, rules)
    errors = sum(1 for f in findings if f["severity"] == "error")
    return {"schema": STYLE_SCHEMA, "ruleset": ruleset, "file": path.name,
            "docType": effective_doc_type, "unit": unit,
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
