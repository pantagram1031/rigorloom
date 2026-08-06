#!/usr/bin/env python3
"""LaTeX -> HwpEqn (한글 수식 스크립트) 변환기.

한글 수식 편집기의 스크립트 언어(HwpEqn)는 LaTeX와 유사하지만 다른 문법을 쓴다.
이 모듈은 자주 쓰는 LaTeX 수식을 HwpEqn으로 변환한다. 완벽한 변환기가 아니라
'실용적 커버리지'를 목표로 한다. 변환이 애매한 명령은 그대로 통과시키고
경고 목록에 담아 반환한다.

사용:
    python eqn.py "\\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"
    -> {-b +- sqrt {b^{2} -4ac}} over {2a}

라이브러리:
    from eqn import latex_to_hwpeqn
    script, warnings = latex_to_hwpeqn(r"\\int_0^\\infty e^{-x^2} dx")
"""

import re
import sys
import json

# ---------------------------------------------------------------------------
# 단순 치환 테이블 (백슬래시 명령 -> HwpEqn 토큰)
# ---------------------------------------------------------------------------

GREEK = [
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
    "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon",
    "Phi", "Psi", "Omega",
]

SIMPLE_MAP = {
    # 연산자/관계
    r"\pm": "+-",
    r"\mp": "-+",
    r"\times": "times",
    r"\div": "div",
    r"\cdot": "cdot",
    r"\le": "leq", r"\leq": "leq",
    r"\ge": "geq", r"\geq": "geq",
    r"\ne": "neq", r"\neq": "neq",
    r"\approx": "approx",
    r"\equiv": "equiv",
    r"\propto": "prop",
    r"\sim": "sim",
    r"\in": "in",
    r"\notin": "notin",
    r"\subset": "subset",
    r"\supset": "supset",
    r"\cup": "cup",
    r"\cap": "cap",
    r"\forall": "forall",
    r"\exists": "exist",
    r"\infty": "inf",
    r"\partial": "partial",
    r"\nabla": "del",
    r"\therefore": "therefore",
    r"\because": "because",
    r"\angle": "angle",
    r"\perp": "bot",
    r"\parallel": "parallel",
    r"\circ": "circ",
    r"\prime": "prime",
    r"\hbar": "hbar",
    r"\ell": "ell",
    r"\emptyset": "emptyset",
    r"\cdots": "cdots",
    r"\ldots": "ldots",
    r"\vdots": "vdots",
    r"\ddots": "ddots",
    # 화살표
    r"\rightarrow": "rarrow", r"\to": "rarrow",
    r"\leftarrow": "larrow", r"\gets": "larrow",
    r"\leftrightarrow": "lrarrow",
    r"\Rightarrow": "RARROW",
    r"\Leftarrow": "LARROW",
    r"\Leftrightarrow": "LRARROW",
    r"\uparrow": "uparrow",
    r"\downarrow": "downarrow",
    # 큰 연산자 (적분/합/극한 등 — 첨자는 _, ^ 그대로 사용 가능)
    r"\int": "int",
    r"\iint": "dint",
    r"\iiint": "tint",
    r"\oint": "oint",
    r"\sum": "sum",
    r"\prod": "prod",
    r"\lim": "lim",
    r"\max": "max",
    r"\min": "min",
    r"\log": "log",
    r"\ln": "ln",
    r"\exp": "exp",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan",
    r"\csc": "csc", r"\sec": "sec", r"\cot": "cot",
    r"\sinh": "sinh", r"\cosh": "cosh", r"\tanh": "tanh",
    r"\arcsin": "arcsin", r"\arccos": "arccos", r"\arctan": "arctan",
    # 천문/기타 기호
    r"\odot": "⊙", r"\oplus": "⊕", r"\otimes": "⊗",
    # 공백
    r"\,": "`", r"\;": "``", r"\quad": "~", r"\qquad": "~~",
    r"\!": "",
}

# 장식 (한 인자) : \cmd{X} -> token {X}
ACCENT_MAP = {
    "vec": "vec", "bar": "bar", "hat": "hat", "dot": "dot",
    "ddot": "ddot", "tilde": "tilde", "overline": "bar",
    "underline": "under", "widehat": "hat", "widetilde": "tilde",
}

MATRIX_ENVS = {
    "pmatrix": "pmatrix", "bmatrix": "bmatrix", "vmatrix": "dmatrix",
    "matrix": "matrix", "cases": "cases", "aligned": "eqalign",
    "align": "eqalign", "align*": "eqalign",
}


# ---------------------------------------------------------------------------
# 중괄호 매칭 유틸
# ---------------------------------------------------------------------------

def _read_group(s, i):
    """s[i]가 '{'일 때, 매칭되는 '}'까지의 내용과 다음 인덱스를 반환."""
    assert s[i] == "{"
    depth = 0
    j = i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ValueError(f"중괄호가 닫히지 않음: ...{s[i:i+30]}")


def _read_arg(s, i):
    """\\frac 등의 인자 하나 읽기: {그룹} 또는 단일 토큰."""
    while i < len(s) and s[i] in " \t":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        return _read_group(s, i)
    if s[i] == "\\":  # \alpha 같은 명령 하나
        m = re.match(r"\\[a-zA-Z]+", s[i:])
        if m:
            return m.group(0), i + m.end()
        return s[i:i + 2], i + 2
    return s[i], i + 1


# ---------------------------------------------------------------------------
# 구조 변환 (재귀)
# ---------------------------------------------------------------------------

def _matrix_rowsep(body):
    """행렬/케이스 환경 본문의 행 구분 백슬래시를 ' # '로 바꾼다.

    LaTeX 행 구분은 '\\\\'(백슬래시 둘)이지만, 셸/JSON 이스케이프를 거치면
    홑 '\\'로 줄어든 채 들어오기도 한다. 두 경우 모두 처리하되 '\\alpha'처럼
    문자로 이어지는 명령은 건드리지 않는다:
      - '\\\\'(둘 이상 연속) -> 행 구분
      - 홑 '\\' 뒤가 공백/문자열끝/'&' -> 행 구분 (명령이 아님)
    """
    body = re.sub(r"\\{2,}", " # ", body)          # \\ (LaTeX 표준)
    body = re.sub(r"\\(?=\s|$|&)", " # ", body)     # 이스케이프로 남은 홑 \
    return body


def _convert_structures(s, warnings):
    """\\frac, \\sqrt, \\text, 장식, 행렬 환경 등 인자를 갖는 구조를 변환."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue

        m = re.match(r"\\([a-zA-Z]+\*?)", s[i:])
        if not m:
            out.append(s[i:i + 2])
            i += 2
            continue
        cmd = m.group(1)
        j = i + m.end()

        # 직전 출력이 영문자로 끝나면 공백을 넣어 토큰 병합 방지 (m\vec{a} -> m vec{a})
        if out and out[-1] and out[-1][-1].isalnum():
            out.append(" ")

        if cmd in ("frac", "dfrac", "tfrac"):
            num, j = _read_arg(s, j)
            den, j = _read_arg(s, j)
            out.append("{%s} over {%s}" % (
                _convert_structures(num, warnings),
                _convert_structures(den, warnings)))
            i = j
        elif cmd == "sqrt":
            # \sqrt[n]{x} -> root {n} of {x}
            if j < n and s[j] == "[":
                k = s.index("]", j)
                idx = s[j + 1:k]
                arg, j2 = _read_arg(s, k + 1)
                out.append("root {%s} of {%s}" % (
                    _convert_structures(idx, warnings),
                    _convert_structures(arg, warnings)))
                i = j2
            else:
                arg, j2 = _read_arg(s, j)
                out.append("sqrt {%s}" % _convert_structures(arg, warnings))
                i = j2
        elif cmd in ("text", "mathrm", "textrm", "mbox", "operatorname"):
            arg, j2 = _read_arg(s, j)
            out.append('"%s"' % arg)  # HwpEqn: 큰따옴표 = 리터럴 텍스트
            i = j2
        elif cmd in ACCENT_MAP:
            arg, j2 = _read_arg(s, j)
            out.append("%s {%s}" % (ACCENT_MAP[cmd],
                                    _convert_structures(arg, warnings)))
            i = j2
        elif cmd == "begin":
            env, j2 = _read_arg(s, j)
            end_tag = "\\end{%s}" % env
            k = s.find(end_tag, j2)
            if k == -1:
                warnings.append(f"\\begin{{{env}}}에 대응하는 \\end 없음")
                i = j2
                continue
            body = s[j2:k]
            hwp_env = MATRIX_ENVS.get(env)
            if hwp_env is None:
                warnings.append(f"지원하지 않는 환경: {env} (내용만 변환)")
                out.append(_convert_structures(_matrix_rowsep(body), warnings))
            else:
                # 행 구분(\\ 또는 셸/JSON 이스케이프로 하나 남은 \)을 먼저
                # 센티널로 바꾼 뒤 재귀 변환한다. 재귀 전에 처리해야 홑
                # 백슬래시가 명령으로 오인되지 않는다.
                body = _convert_structures(_matrix_rowsep(body), warnings)
                out.append("%s{%s}" % (hwp_env, body.strip()))
            i = k + len(end_tag)
        elif cmd in ("left", "right"):
            # \left( -> left (   /  \left\{ -> left {
            delim = ""
            if j < n:
                if s[j] == "\\" and j + 1 < n:
                    delim = s[j + 1]
                    j += 2
                else:
                    delim = s[j]
                    j += 1
            out.append("%s %s " % (cmd, delim if delim != "." else ""))
            i = j
        else:
            out.append("\\" + cmd)  # 다음 단계(SIMPLE_MAP/그리스)에서 처리
            i = i + m.end()
    return "".join(out)


def _brace_scripts(s):
    """Bare ^x / _x 를 ^{x} / _{x} 로 감싼다.

    HwpEqn의 ^ / _ 는 중괄호가 없으면 '다음 공백까지의 토큰 전체'를 첨자로
    삼는다. 그래서 `x^2)=D(x cdot x)` 같은 식에서 `x^` 뒤에 공백이 없으면
    `2)=D(x` 전체가 위첨자로 올라가 렌더가 깨진다(실측: 미적분 곱법칙 보고서
    p4 `D(x^2)=...`). 다음 단일 원자(문자/숫자, \\command, 또는 이미 있는
    {그룹})만 첨자가 되도록 명시적으로 감싼다. LaTeX 의미(`x^2`=x², `x^ab`=x²b)와
    동일하므로 무손실이고, 이미 `x^{k-1}`처럼 감싼 것은 그대로 둔다.
    """
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        out.append(c)
        if c in "^_":
            j = i + 1
            while j < n and s[j] == " ":  # ^ 와 인자 사이 공백 흡수
                j += 1
            if j >= n or s[j] == "{":       # 끝 또는 이미 {그룹} → 그대로
                i += 1
                continue
            if s[j] == "\\":                # \command 원자
                m = re.match(r"\\([a-zA-Z]+\*?|.)", s[j:])
                atom = m.group(0)
                out.append("{" + atom + "}")
                i = j + len(atom)
                continue
            out.append("{" + s[j] + "}")    # 단일 문자 원자
            i = j + 1
            continue
        i += 1
    return "".join(out)


def latex_to_hwpeqn(latex):
    """LaTeX 수식 문자열을 HwpEqn 스크립트로 변환.

    Returns:
        (script, warnings) 튜플.
    """
    warnings = []
    s = latex.strip()
    s = s.strip("$")  # $...$ 허용

    # 0) 이중 백슬래시 정규화: LLM이 만든 번들은 latex 속성을 흔히 이중 escape한다
    #    (예: "\\frac", "\\left", "\\!"). 명령/공백 토큰 앞의 여분 백슬래시를 하나로
    #    접는다.
    #
    #    행렬류 환경(pmatrix/bmatrix/cases/aligned/...) 본문은 이 정규화에서
    #    반드시 제외해야 한다: 행 구분자 "\\"(둘) 바로 뒤에 다음 셀 값이 문자로
    #    시작하면(예: "a&b\\c&d"의 "\\c") 이 lookahead가 "\\\\c" -> "\\c"로 접어,
    #    _matrix_rowsep()이 실행되기 전에 행 구분자를 명령처럼 보이는 잔여
    #    단일 백슬래시로 무너뜨려 버린다(_matrix_rowsep은 구조 변환 단계에서
    #    나중에 실행됨 — 이미 늦음). 그래서 \begin{ENV}...\end{ENV} 블록은
    #    통째로 보호(센티널로 치환)한 뒤 바깥쪽만 de-escape하고, 나중에
    #    원문 그대로 복원해 _convert_structures/_matrix_rowsep이 원본 "\\"를
    #    보게 한다.
    _protected = []

    def _protect_env(m):
        _protected.append(m.group(0))
        return f"\x00PROTECTED{len(_protected) - 1}\x00"

    _env_names = "|".join(re.escape(e) for e in MATRIX_ENVS)
    s = re.sub(r"\\begin\{(?:" + _env_names + r")\}.*?\\end\{(?:" + _env_names + r")\}",
               _protect_env, s, flags=re.S)

    s = re.sub(r"\\{2,}(?=[A-Za-z!,;:])", "\\\\", s)

    for idx, chunk in enumerate(_protected):
        s = s.replace(f"\x00PROTECTED{idx}\x00", chunk)

    # 1) 구조(인자 있는 명령) 변환
    s = _convert_structures(s, warnings)

    # 1.5) bare ^x/_x 를 ^{x}/_{x} 로 감싸 HwpEqn 첨자 과잉 스코프 방지
    s = _brace_scripts(s)

    # 2) 그리스 문자 (백슬래시 제거)
    for g in sorted(GREEK, key=len, reverse=True):
        s = s.replace("\\" + g, " %s " % g)

    # 3) 단순 치환 (긴 명령 먼저)
    for k in sorted(SIMPLE_MAP, key=len, reverse=True):
        s = s.replace(k, " %s " % SIMPLE_MAP[k] if SIMPLE_MAP[k] else "")

    # 4) 남은 백슬래시 명령 -> 경고 후 백슬래시 제거
    leftover = set(re.findall(r"\\[a-zA-Z]+", s))
    for cmd in leftover:
        warnings.append(f"미지원 명령 통과: {cmd}")
        s = s.replace(cmd, " %s " % cmd[1:])

    # 5) 공백 정리 (백틱 ` 은 수식 공백이므로 유지)
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\s*([{}^_])\s*", r"\1", s)  # 구조 문자 주변 압축
    s = re.sub(r"{ ", "{", s).strip()

    return s, warnings


# HwpEqn이 처리하지 못하는 것으로 알려진 LaTeX 잔여 토큰. 출력에 남아 있으면
# 한글 수식 편집기에서 깨지므로 sanity check를 FAIL 시킨다.
UNSUPPORTED_TOKENS = (
    "binom", "mathbb", "boxed", "overrightarrow", "substack",
)


def hwpeqn_sanity_check(script):
    """HwpEqn 스크립트의 기초 무결성 검사 (중괄호 균형, 미변환 토큰 등)."""
    depth = 0
    for ch in script:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False, "닫는 중괄호 과잉"
    if depth != 0:
        return False, f"중괄호 불균형 (깊이 {depth})"
    if script.count('"') % 2 != 0:
        return False, "리터럴 따옴표 불균형"
    # 미변환 행 구분/명령 백슬래시가 남아 있으면 한글에서 깨진다.
    if "\\" in script:
        return False, "미변환 백슬래시 잔여 (행 구분 \\\\ 등)"
    for tok in UNSUPPORTED_TOKENS:
        if tok in script:
            return False, f"HwpEqn 미지원 토큰: {tok}"
    return True, "ok"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    script, warns = latex_to_hwpeqn(sys.argv[1])
    ok, msg = hwpeqn_sanity_check(script)
    print(json.dumps({"hwpeqn": script, "warnings": warns,
                      "sanity": msg}, ensure_ascii=False, indent=2))
