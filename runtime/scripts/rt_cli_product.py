#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Product verbs of the ``rigorloom`` command: the registry, driven by argv.

    rigorloom open 보고서.hwpx
    rigorloom read 보고서.hwpx --at t3
    rigorloom fill 신청서.hwpx --set 성명=홍길동 -o 신청서-작성.hwpx
    rigorloom save 보고서.hwpx            # write the draft over the file (asks)

Each verb parses its arguments into the SAME typed request the MCP server and
the agent send, and calls :func:`rt_tools.call`. Nothing about a document is
decided here; this module owns argv, the person-facing confirmation, and how a
result is printed.

The person's CLI reads files on disk (``--source disk``) and says when a draft
exists; ``--source draft`` reads the draft the way an agent does.

Legacy commands (``--root DIR open --path ...``, ``guard``, ``style``, ...)
never reach this module: ``cli.main`` routes them to the old parser
unchanged, so their argv, exit codes and stdout stay byte for byte.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:  # installed as rigorloom_runtime
    from . import rt_commit, rt_toolset  # rt_toolset registers the tools
    from .rt_cli_render import SHOW, candidates_line, person_error, shown
    from .rt_paths import STATE_MARKER, PathRefused, canonical, state_home
    from .rt_term import (Term, confirm, invisible_in, is_console, one_line, pad, prepare_stdio,
                          safe_text, save_question, undo_line, width)
    from .rt_tools import ERROR_EXIT, Context, ToolError, call, get, render_text
except ImportError:  # a checkout, runtime/scripts on sys.path
    import rt_commit
    import rt_toolset
    from rt_cli_render import SHOW, candidates_line, person_error, shown
    from rt_paths import STATE_MARKER, PathRefused, canonical, state_home
    from rt_term import (Term, confirm, invisible_in, is_console, one_line, pad, prepare_stdio,
                         safe_text, save_question, undo_line, width)
    from rt_tools import ERROR_EXIT, Context, ToolError, call, get, render_text

#: Verbs this module owns. ``open`` collides with the legacy protocol verb;
#: cli.main sends ``open`` here only when no global --root/--engine-root
#: precedes it (every legacy ``open`` has one).
PRODUCT_VERBS = ("open", "outline", "read", "find", "edit", "fill", "new",
                 "preview", "check", "save", "changes", "undo", "convert", "guide",
                 "mcp")

LEGACY_GLOBALS = ("--root", "--engine-root")
LEGACY_ALWAYS = ("install", "doctor", "guard", "style", "engine", "ui", "demo")

EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_INTERNAL = 0, 2, 3, 4

#: The top-level help, one (usage, what it does) row per verb. Usage columns
#: are padded by terminal width, so Korean in a usage still lines up.
HELP_SECTIONS = (
    ("읽기", (
        ("open FILE", "문서 구조: 쪽, 글꼴, 제목, 표, 채울 칸과 주소"),
        ("read FILE [--at 주소]", "본문 읽기 (긴 글은 --cursor로 이어 읽기)"),
        ("find FILE 찾을말", "찾은 곳의 주소 표시"),
        ("preview FILE", "쪽 미리보기(PNG)"),
    )),
    ("쓰기 (원본은 save 전까지 그대로)", (
        ("edit FILE --op JSON", "고치기: set, replace, insert_after, delete, table.*"),
        ("fill FILE --set 칸=값", "양식 채우기 (서명·날인 칸은 건너뜀)"),
        ("new 내용.md", "마크다운으로 새 문서 만들기"),
        ("save FILE [--to 경로]", "초안을 파일로 저장 (덮어쓰기 전 확인, undo로 되돌리기)"),
        ("convert FILE -o OUT", "다른 형식으로 내보내기 (pdf, docx, md, png)"),
    )),
    ("점검과 기록", (
        ("check FILE", "문체·쪽 배치·글꼴 점검, 숫자 변경 확인"),
        ("changes [FILE]", "초안과 저장 기록"),
        ("undo FILE", "마지막 저장 되돌리기"),
        ("guide [주제]", "공문·보고서·양식 작성 안내"),
    )),
    ("에이전트", (
        ("mcp [--allow 폴더]", "에이전트가 이 명령들을 도구로 쓸 수 있도록 MCP 서버(stdio) 실행"),
    )),
)
HELP_TAIL = """\
공통 옵션: --json (JSON으로 출력)  --color auto|always|never
명령마다 자세히: rigorloom <명령> --help

앱·설치: ui  doctor  engine  install  demo  guard  style
프로토콜 명령 (--root 필요): capabilities sessions inspect read-region render
  geometry events modules module-check propose validate plan request-approval
  approval approve reject apply candidates compare receipt verify
  자세히: rigorloom protocol --help
"""
HELP_USAGE_COLUMNS = 22


def help_text() -> str:
    lines = ["rigorloom — 에이전트와 함께 한글·워드·마크다운 문서를 편집하는 도구", ""]
    for title, rows in HELP_SECTIONS:
        lines.append(title)
        for usage, what in rows:
            lines.append(f"  {pad(usage, HELP_USAGE_COLUMNS)}  {what}".rstrip())
        lines.append("")
    return "\n".join(lines) + "\n" + HELP_TAIL


#: Each verb's own --help: what it does, then two command lines to copy.
VERB_HELP = {
    "open": ("쪽, 글꼴, 제목, 표, 채울 칸과 그 주소를 확인합니다.",
             ("rigorloom open 보고서.hwpx",
              "rigorloom open 신청서.hwpx --source draft")),
    "outline": ("open과 같습니다.", ("rigorloom outline 보고서.hwpx",)),
    "read": ("본문을 주소와 함께 읽습니다. 긴 글은 마지막 줄에 나오는 명령으로 이어 읽습니다.",
             ("rigorloom read 보고서.hwpx --at p12",
              "rigorloom read 보고서.hwpx --at t3")),
    "find": ("찾는 말이 나온 곳마다 주소를 표시합니다.",
             ("rigorloom find 보고서.hwpx 예산",
              'rigorloom find 계약서.hwpx "제[0-9]+조" --regex')),
    "edit": ("초안을 고칩니다. 원본 파일은 save 전까지 그대로입니다.\n"
             "작업: set, replace, insert_after, delete, table.set_cells, table.add_row, "
             "table.delete_row, style, char_shape(글자 모양), para_shape(문단 모양), "
             "numbering(개요·문단 번호, 글머리표), table.merge·table.split(셀 합치기·나누기), "
             "table.add_col·table.delete_col(칸 넣기·지우기), table.size(셀 너비·높이), "
             "page_setup(편집 용지), columns(다단), break(쪽·단·구역 나누기), "
             "header(머리말·꼬리말), page_number(쪽 번호 매기기), "
             "table.cell_style(셀 테두리·배경·정렬·여백·제목 셀), table.style(제목 줄 반복, 쪽 경계에서 나눔), "
             "style.create(스타일 추가: 이름, 바탕 스타일, 글자 모양, 문단 모양), "
             "note(각주·미주), caption(표 캡션)",
             ("""rigorloom edit 보고서.hwpx --op '{"op":"replace","at":"p3","find":"사본하여","with":"복사하여"}'""",
              """rigorloom edit 보고서.hwpx --op '{"op":"set","at":"p0","text":"2027년 업무계획"}' -o 보고서-수정.hwpx""")),
    "fill": ("양식의 빈칸을 채웁니다. 서명·날인·결재일 칸은 비워 두고 어떤 칸인지 알려 줍니다.",
             ("rigorloom fill 신청서.hwpx --set 성명=홍길동 --set 소속=총무과",
              "rigorloom fill 신청서.hwpx --values 값.json -o 신청서-작성.hwpx")),
    "new": ("마크다운으로 새 문서를 만듭니다. 양식 파일을 지정하면 그 양식에 내용을 채웁니다.",
            ("rigorloom new 초안.md -o 보고서.hwpx",
             "rigorloom new 초안.md --form 기안문양식.hwpx -o 기안문.hwpx")),
    "preview": ("쪽을 그림(PNG)으로 만듭니다. 한글 엔진이 있어야 합니다.",
                ("rigorloom preview 보고서.hwpx --page 1",
                 "rigorloom preview 보고서.hwpx --source draft --changed")),
    "check": ("문체, 쪽 배치, 글꼴을 점검하고 숫자·사실이 바뀌었는지 확인합니다.",
              ("rigorloom check 보고서.hwpx --source draft",
               "rigorloom check 보고서-수정.hwpx --against 보고서.hwpx --pack gongmun")),
    "save": ("초안을 파일로 저장합니다. 있는 파일을 덮어쓸 때는 먼저 묻고, "
             "이전 내용은 저장 기록에 남깁니다.",
             ("rigorloom save 보고서.hwpx",
              "rigorloom save 보고서.hwpx --to 보고서-수정.hwpx")),
    "changes": ("초안과 저장 기록을 봅니다. discard는 초안을 버리고, "
                "clean은 오래된 초안·미리보기·저장 기록을 지웁니다.",
                ("rigorloom changes 보고서.hwpx",
                 "rigorloom changes clean --older-than 30")),
    "undo": ("마지막 저장을 되돌립니다. 그 뒤에 파일이 바뀌었으면 되돌리지 않습니다.",
             ("rigorloom undo 보고서.hwpx",)),
    "convert": ("다른 형식으로 내보냅니다. -o로 지정한 파일의 확장자는 --to로 지정한 형식과 일치해야 합니다.",
                ("rigorloom convert 보고서.hwpx --to pdf -o 보고서.pdf",
                 "rigorloom convert 보고서.hwpx --to docx -o 보고서.docx")),
    "guide": ("공문·보고서·양식 작성 안내를 봅니다. 주제 없이 실행하면 주제 목록이 나옵니다.",
              ("rigorloom guide", "rigorloom guide gongmun")),
}


class _Help(argparse.RawDescriptionHelpFormatter):
    """argparse's layout with Korean section names."""

    _HEADINGS = {"positional arguments": "인자", "options": "옵션",
                 "optional arguments": "옵션"}

    def start_section(self, heading):
        super().start_section(self._HEADINGS.get(heading, heading))

    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "사용법: " if prefix is None else prefix)

    def format_help(self) -> str:
        # argparse pads by character count; a Korean metavar is two columns
        # per character, so pull its help text back to the shared column.
        out = []
        for line in super().format_help().split("\n"):
            m = re.match(r"^(\s+)(-\S.*?)( {2,})(\S.*)$", line)
            if m:
                extra = width(m.group(2)) - len(m.group(2))
                gap = m.group(3)
                if extra > 0 and len(gap) - extra >= 2:
                    line = m.group(1) + m.group(2) + gap[extra:] + m.group(4)
            out.append(line)
        return "\n".join(out)


def _verb(sub, name: str, summary: str) -> argparse.ArgumentParser:
    what, examples = VERB_HELP[name]
    epilog = "예:\n" + "\n".join(f"  {line}" for line in examples)
    return sub.add_parser(name, help=summary, description=what, epilog=epilog,
                          formatter_class=_Help, add_help=False)


def is_product(argv: list[str]) -> bool:
    """Does this argv belong to the product verbs (not the legacy parser)?"""
    for token in argv:
        if token in LEGACY_GLOBALS or any(token.startswith(g + "=") for g in LEGACY_GLOBALS):
            return False
        if token.startswith("-"):
            continue
        return token in PRODUCT_VERBS
    return False


def wants_product_help(argv: list[str]) -> bool:
    return argv in (["--help"], ["-h"], ["help"], [])


def is_unknown(argv: list[str], legacy_commands) -> bool:
    """A first word that is neither a product verb nor a legacy command.

    Without this, a typo (``opn``) fell through to the protocol parser and
    printed its English list of 28 internal commands.
    """
    if not argv or argv[0].startswith("-"):
        return False
    return argv[0] not in PRODUCT_VERBS and argv[0] not in legacy_commands \
        and argv[0] not in ("protocol", "help")


def _unknown(word: str) -> "_Usage":
    import difflib
    known = list(PRODUCT_VERBS) + list(LEGACY_ALWAYS)
    near = difflib.get_close_matches(word, known, n=1, cutoff=0.6)
    if near:
        return _Usage(f"알 수 없는 명령입니다: {word} (혹시 {near[0]}?)",
                      f"명령 목록: rigorloom --help")
    return _Usage(f"알 수 없는 명령입니다: {word}", "명령 목록: rigorloom --help")


# --------------------------------------------------------------------------
# argv -> typed request
# --------------------------------------------------------------------------

def _common(p: argparse.ArgumentParser, *, source: bool = False) -> None:
    p.add_argument("-h", "--help", action="help", help="이 도움말")
    p.add_argument("--json", action="store_true", help="결과를 JSON으로 출력 (프로그램·에이전트용)")
    if source:
        p.add_argument("--source", choices=("disk", "draft"), default="disk",
                       help="저장된 파일(disk, 기본값) 또는 초안(draft) 읽기")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                   help="색상 표시 (기본값 auto는 터미널에서만 색을 사용)")
    p.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)


class _Parser(argparse.ArgumentParser):
    """argparse, but a wrong command line is a _Usage, not a print-and-exit."""

    def error(self, message: str):  # noqa: D401 - argparse API
        verb = self.prog.split()[-1] if " " in self.prog else ""
        raise _Usage(f"명령을 해석하지 못했습니다: {message}",
                     f"도움말: rigorloom {verb} --help".replace("  ", " "))


def _parser() -> argparse.ArgumentParser:
    root = _Parser(prog="rigorloom", add_help=False)
    sub = root.add_subparsers(dest="verb", required=True)

    for name in ("open", "outline"):
        p = _verb(sub, name, "문서 구조")
        p.add_argument("path", metavar="FILE", help="열 문서"); _common(p, source=True)

    p = _verb(sub, "read", "본문 읽기")
    p.add_argument("path", metavar="FILE", help="읽을 문서")
    p.add_argument("--at", metavar="주소", help="이 주소만 읽기 (p12, t3, t3/r2/c1, place:성명)")
    p.add_argument("--cursor", help="이어 읽을 위치 (이전 출력의 마지막 줄에 표시)")
    p.add_argument("--max-chars", type=int, metavar="글자수", help="한 번에 읽을 최대 글자 수")
    p.add_argument("--runs", action="store_true", help="글자 모양(굵게, 글꼴 등)도 표시")
    _common(p, source=True)

    p = _verb(sub, "find", "찾기")
    p.add_argument("path", metavar="FILE", help="찾을 문서")
    p.add_argument("query", metavar="찾을말", help="찾을 말")
    p.add_argument("--regex", action="store_true", help="말을 정규식으로 해석")
    p.add_argument("--scope", metavar="주소", help="이 주소 안에서만 찾기 (예: t3)")
    p.add_argument("--limit", type=int, metavar="개수", help="보여 줄 최대 개수")
    _common(p, source=True)

    p = _verb(sub, "edit", "고치기")
    p.add_argument("path", metavar="FILE", help="고칠 문서")
    p.add_argument("--op", action="append", default=[], metavar="JSON",
                   help="작업 하나 (여러 번 쓸 수 있음, 아래 예 참고)")
    p.add_argument("--ops-file", metavar="파일", help="작업 목록 JSON 파일 (파일 대신 -를 쓰면 표준 입력)")
    p.add_argument("--base", metavar="REV", help=argparse.SUPPRESS)
    p.add_argument("-o", "--out", metavar="OUT", help="고친 결과를 이 새 파일로 바로 저장")
    p.add_argument("--force", action="store_true", help="OUT이 있으면 덮어씀 (이전 내용은 저장 기록에 보관)")
    _common(p)

    p = _verb(sub, "fill", "양식 채우기")
    p.add_argument("path", metavar="FILE", help="채울 양식")
    p.add_argument("--set", action="append", default=[], metavar="칸=값",
                   help="채울 칸과 값 (여러 번 쓸 수 있음). 칸 이름은 open에 나옴")
    p.add_argument("--values", metavar="파일", help="칸 이름과 값을 짝지은 JSON 파일 (파일 대신 -를 쓰면 표준 입력)")
    p.add_argument("--base", metavar="REV", help=argparse.SUPPRESS)
    p.add_argument("-o", "--out", metavar="OUT", help="채운 결과를 이 새 파일로 바로 저장")
    p.add_argument("--force", action="store_true", help="OUT이 있으면 덮어씀 (이전 내용은 저장 기록에 보관)")
    _common(p)

    p = _verb(sub, "new", "새 문서")
    p.add_argument("markdown", metavar="내용.md", help="마크다운 파일 (파일 대신 -를 쓰면 표준 입력)")
    p.add_argument("--form", metavar="양식", help="새 문서 작성에 사용할 양식")
    p.add_argument("--dialect", choices=("commonmark", "report"),
                   help="마크다운 문법: commonmark(기본값, 표와 목록) 또는 report(□/○ 기호, 번호가 붙은 제목)")
    p.add_argument("--name", metavar="이름", help="초안 이름 (changes 목록에 보임)")
    p.add_argument("-o", "--out", metavar="OUT", help="만든 문서를 이 새 파일로 바로 저장")
    p.add_argument("--force", action="store_true", help="OUT이 있으면 덮어씀 (이전 내용은 저장 기록에 보관)")
    _common(p)

    p = _verb(sub, "preview", "쪽 미리보기")
    p.add_argument("path", metavar="FILE", help="볼 문서")
    p.add_argument("--page", type=int, action="append", metavar="쪽", help="볼 쪽 (여러 번 쓸 수 있음)")
    p.add_argument("--changed", action="store_true", help="초안에서 바뀐 쪽만")
    p.add_argument("--scale", type=float, metavar="배율", help="그림 배율 (기본 1.0)")
    _common(p, source=True)

    p = _verb(sub, "check", "점검")
    p.add_argument("path", metavar="FILE", help="점검할 문서")
    p.add_argument("--against", metavar="원본", help="이 문서와 비교해 숫자·사실이 바뀌었는지 보기")
    p.add_argument("--pack", choices=("gongmun", "minwon", "hr", "grant"),
                   help="문서 종류별 규칙 (공문, 민원, 인사, 지원사업)")
    p.add_argument("--only", action="append", choices=("style", "layout", "fonts", "guard"),
                   help="이 점검만 (여러 번 쓸 수 있음)")
    _common(p, source=True)

    p = _verb(sub, "save", "초안 저장")
    p.add_argument("path", metavar="FILE", help="초안이 있는 문서")
    p.add_argument("--to", metavar="경로", help="다른 이름으로 저장 (형식은 확장자를 따름)")
    p.add_argument("--force", action="store_true",
                   help="있는 파일을 묻지 않고 덮어씀 (이전 내용은 저장 기록에 남음)")
    _common(p)

    p = _verb(sub, "changes", "초안과 저장 기록")
    p.add_argument("action", nargs="?", default="list",
                   choices=("list", "show", "discard", "clean"), metavar="list|show|discard|clean",
                   help="list(기본): 초안 목록, show: 한 문서의 기록, discard: 초안 버리기, "
                        "clean: 오래된 초안·미리보기·저장 기록 지우기")
    p.add_argument("path", nargs="?", metavar="FILE", help="문서 (show, discard)")
    p.add_argument("--id", help=argparse.SUPPRESS)
    p.add_argument("--older-than", type=int, metavar="일", default=RETENTION_DAYS,
                   help=f"clean: 이 날수보다 오래된 것만 지움 (기본 {RETENTION_DAYS}일)")
    p.add_argument("--all", action="store_true",
                   help="clean: 저장 안 한 초안까지 모두 지움")
    p.add_argument("--yes", action="store_true", help="clean: 묻지 않고 지움")
    _common(p)

    p = _verb(sub, "undo", "마지막 저장 되돌리기")
    p.add_argument("path", metavar="FILE", help="되돌릴 파일"); _common(p)

    p = _verb(sub, "convert", "형식 바꾸기")
    p.add_argument("path", metavar="FILE", help="바꿀 문서")
    p.add_argument("--to", required=True, choices=("hwpx", "hwp", "pdf", "png", "md", "docx"),
                   help="만들 형식")
    p.add_argument("-o", "--out", required=True, metavar="OUT", help="만들 파일")
    p.add_argument("--force", action="store_true", help="OUT이 있으면 덮어씀 (이전 내용은 저장 기록에 보관)")
    _common(p)

    p = _verb(sub, "guide", "작성 안내")
    p.add_argument("topic", nargs="?", metavar="주제", help="gongmun, report, forms, layout, writing, workflow")
    _common(p)
    return root


class _Usage(Exception):
    """A wrong command line: one line of what, one line of what to type."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def _read_text_arg(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    try:
        return Path(value).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise _Usage(f"입력 파일을 읽을 수 없습니다({value}, {exc.strerror or exc}).",
                     "파일 이름과 경로를 확인하세요.") from exc


def _ops(args) -> list:
    ops: list = []
    if args.ops_file:
        try:
            payload = json.loads(_read_text_arg(args.ops_file))
        except ValueError as exc:
            raise _Usage(f"--ops-file로 지정한 입력의 문법이 맞지 않습니다({exc}).",
                         "오류에 나온 위치에서 작업 목록의 JSON 문법을 고치세요.") from exc
        payload = payload.get("ops", payload) if isinstance(payload, dict) else payload
        if not isinstance(payload, list):
            raise _Usage("--ops-file로 지정한 작업 목록의 형식이 맞지 않습니다.",
                         '작업을 [{"op": "set", ...}, ...]처럼 대괄호로 묶어 주세요.')
        ops.extend(payload)
    for index, text in enumerate(args.op):
        try:
            ops.append(json.loads(text))
        except ValueError as exc:
            raise _Usage(f"--op로 입력한 {index + 1}번째 작업의 문법이 맞지 않습니다({exc}).",
                         """예: --op '{"op":"set","at":"p1","text":"제목"}'""") from exc
    if not ops:
        raise _Usage("고칠 내용을 지정하지 않았습니다.",
                     """--op '{"op":"set","at":"p1","text":"…"}' 또는 --ops-file 파일로 고칠 내용을 지정하세요.""")
    return ops


def _values(args) -> dict:
    values: dict = {}
    if args.values:
        try:
            loaded = json.loads(_read_text_arg(args.values))
        except ValueError as exc:
            raise _Usage(f"--values로 지정한 입력의 문법이 맞지 않습니다({exc}).",
                         '칸과 값을 {"성명": "홍길동"}처럼 적으세요.') from exc
        if not isinstance(loaded, dict):
            raise _Usage("--values로 지정한 입력의 형식이 맞지 않습니다.",
                         '칸과 값을 {"성명": "홍길동"}처럼 적으세요.')
        values.update(loaded)
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise _Usage(f"--set 뒤의 값이 칸=값 형식에 맞지 않습니다({item}).",
                         "예: --set 성명=홍길동")
        values[key.strip()] = value
    if not values:
        raise _Usage("채울 값이 없습니다.", "--set 성명=홍길동처럼 칸 이름과 값을 입력하세요.")
    return values


def request_for(args) -> tuple[str, dict]:
    """The tool name and typed request this argv means."""
    v = args.verb
    if v in ("open", "outline"):
        return "open", {"path": args.path}
    if v == "read":
        req = {"path": args.path}
        if args.at: req["at"] = args.at
        if args.cursor: req["cursor"] = args.cursor
        if args.max_chars: req["max_chars"] = args.max_chars
        if args.runs: req["with_runs"] = True
        return "read", req
    if v == "find":
        req = {"path": args.path, "query": args.query}
        if args.regex: req["regex"] = True
        if args.scope: req["scope"] = args.scope
        if args.limit: req["limit"] = args.limit
        return "find", req
    if v == "edit":
        req = {"path": args.path, "ops": _ops(args)}
        if args.base: req["base"] = args.base
        return "edit", req
    if v == "fill":
        req = {"path": args.path, "values": _values(args)}
        if args.base: req["base"] = args.base
        return "fill", req
    if v == "new":
        req = {"markdown": _read_text_arg(args.markdown)}
        if args.markdown != "-":
            req["base_dir"] = str(Path(args.markdown).resolve().parent)
        if args.form: req["form"] = args.form
        if args.dialect: req["dialect"] = args.dialect
        if args.name: req["name"] = args.name
        return "new", req
    if v == "preview":
        req = {"path": args.path}
        if args.changed: req["pages"] = "changed"
        elif args.page: req["pages"] = args.page
        if args.scale: req["scale"] = args.scale
        return "preview", req
    if v == "check":
        req = {"path": args.path}
        if args.against: req["against"] = args.against
        if args.pack: req["pack"] = args.pack
        if args.only: req["only"] = args.only
        return "check", req
    if v == "save":
        req = {"path": args.path}
        if args.to is not None: req["to"] = args.to  # '' is refused, not dropped
        return "save", req
    if v == "changes":
        req: dict = {"action": "show" if args.path and args.action == "list" else args.action}
        if args.path: req["path"] = args.path
        if args.id: req["id"] = args.id
        return "changes", req
    if v == "guide":
        return "guide", ({"topic": args.topic} if args.topic else {})
    raise _Usage(f"지원하지 않는 명령입니다({v}).", "명령 목록: rigorloom --help")


# --------------------------------------------------------------------------
# running and printing
# --------------------------------------------------------------------------

def _context(args) -> Context:
    def ask(question: str, detail: dict) -> bool | None:
        if not (is_console(sys.stdin) and is_console(sys.stderr)):
            return None
        # The question first, then what the person needs to answer it, then y/N.
        lines = save_question(question, detail, shown=shown)
        sys.stderr.write(safe_text(lines[0] + " [y/N]\n" + "\n".join("  " + x for x in lines[1:])) + "\n")
        return confirm("", prompt="> ")
    return Context(client="cli", roots=None, source=getattr(args, "source", "disk"),
                   ask=ask, force=bool(getattr(args, "force", False)))


def _emit(term: Term, args, verb: str, envelope: dict) -> int:
    if envelope["ok"]:
        code = EXIT_OK
        if verb == "check" and envelope["result"].get("pass") is not True:
            code = EXIT_REFUSED
    else:
        code = ERROR_EXIT.get(envelope["error"]["code"], EXIT_INTERNAL)
    if args.json:
        payload = {"ok": envelope["ok"], "command": verb}
        payload["result" if envelope["ok"] else "error"] = (
            envelope["result"] if envelope["ok"] else envelope["error"])
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return code
    if envelope["ok"]:
        tool = _TOOL_OF.get(verb, verb)
        show = SHOW.get(tool)
        if show is not None:
            show(term, envelope["result"])
        else:
            term.line(render_text(get(tool), envelope["result"]))
        return code
    err = envelope["error"]
    message, hint = person_error(err, getattr(args, "path", None))
    sys.stderr.write(f"{safe_text(message)}\n")
    if hint:
        sys.stderr.write(f"  {safe_text(hint)}\n")
    if err.get("candidates") and err.get("code") != "person_only_seat" and not (
            len(err["candidates"]) == 1 and str(err["candidates"][0]) in (hint or "")):
        sys.stderr.write("  후보: " + candidates_line(err["candidates"]) + "\n")
    if getattr(args, "debug", False):
        if message != err["message"]:
            sys.stderr.write(f"  ({safe_text(err['message'])})\n")
        if err.get("data"):
            sys.stderr.write(json.dumps(err["data"], ensure_ascii=False, indent=2) + "\n")
    return code


def _draft_note(ctx: Context, path: str) -> str | None:
    """One line when a person reads the file while a draft holds unsaved work."""
    try:
        ref = rt_toolset.resolve(ctx, path)
        if ref.source is None:
            return None
        draft = ctx.drafts.input_for(ref, use_draft=False).draft or {}
    except (ToolError, OSError):
        return None
    if draft.get("sourceChanged"):
        return ("초안을 만든 뒤 파일이 바뀌었습니다. 초안을 버리려면: "
                f'rigorloom changes discard "{path}"')
    if draft.get("unsaved"):
        return (f"저장 안 한 초안({draft.get('revision')}판)이 있습니다. 지금 본 것은 파일입니다. "
                "초안을 보려면 --source draft를 붙이세요.")
    return None


_TOOL_OF = {"outline": "open", "convert": "save"}


def _save_after(ctx: Context, args, path: str) -> dict:
    """``-o OUT`` on edit/fill/new: stage in a private draft, save to OUT, and
    drop that draft; the shared draft of the same file is never touched."""
    req = {"path": path, "to": args.out}
    envelope = call(ctx, "save", req)
    try:
        ref = rt_toolset.resolve(ctx, path)
    except ToolError:
        return envelope
    if envelope["ok"]:
        ctx.drafts.remove(ref)
    else:
        # Not saved: keep the edited copy so the work is not lost.
        head = ctx.drafts.load(ref) or {}
        if head.get("head"):
            kept = ctx.drafts.dir_for(ref) / head["head"]["file"]
            envelope["error"].setdefault("data", {})["kept"] = str(kept)
            envelope["error"]["hint"] = ((envelope["error"].get("hint") or "")
                                         + f" 고친 내용은 {kept}에 남겨 두었습니다.").strip()
    return envelope


def _undo(term: Term, args) -> int:
    try:
        target = canonical(args.path)
        # Say "nothing to undo" before asking, not after the person said yes.
        entry = rt_commit.undoable(target)
    except PathRefused as exc:
        return _emit(term, args, "undo", {"ok": False, "error": ToolError(
            exc.code, exc.message, at=exc.path).to_dict()})
    except OSError as exc:
        return _emit(term, args, "undo", {"ok": False, "error": ToolError(
            "internal", "파일을 읽지 못해 되돌리지 않았습니다.",
            hint=safe_text(exc.strerror or type(exc).__name__), at=str(args.path)).to_dict()})
    except ToolError as exc:
        return _emit(term, args, "undo", {"ok": False, "error": exc.to_dict()})
    name = shown(str(target))
    if entry.get("oldSha256") is None:
        sys.stderr.write(f"{name} 파일은 Rigorloom이 새로 만든 파일입니다. "
                         "되돌리면 파일을 저장 기록에 보관하고 현재 경로에서 삭제합니다.\n")
    when = (entry.get("at") or "").replace("T", " ").replace("Z", " UTC")
    hidden = invisible_in(str(target))
    if hidden:
        sys.stderr.write(f"파일 이름에 보이지 않는 문자가 있습니다: {', '.join(hidden)}\n")
    answer = confirm(f'"{name}" 파일을 마지막 저장({when}) 전으로 되돌릴까요?')
    if answer is None:
        envelope = {"ok": False, "error": ToolError(
            "needs_person", "되돌리기는 터미널에서 직접 확인해야 합니다.",
            hint=undo_line(str(target), shown=shown)).to_dict()}
    elif not answer:
        envelope = {"ok": False, "error": ToolError(
            "declined_by_person", "되돌리지 않았습니다.").to_dict()}
    else:
        try:
            envelope = {"ok": True, "result": rt_commit.undo(
                target, by="cli", expect=rt_commit.entry_id(entry))}
        except ToolError as exc:
            envelope = {"ok": False, "error": exc.to_dict()}
        except OSError as exc:
            envelope = {"ok": False, "error": ToolError(
                "internal", "파일을 읽거나 옮기지 못해 되돌리지 않았습니다.",
                hint=safe_text(exc.strerror or type(exc).__name__), at=str(target)).to_dict()}
    if envelope["ok"] and not args.json:
        r = envelope["result"]
        term.line(f"되돌렸습니다: {shown(r['target'])}" if not r["removed"]
                  else f"새로 만들었던 파일을 치웠습니다: {shown(r['target'])} (저장 기록에 보관)")
        return EXIT_OK
    return _emit(term, args, "undo", envelope)


def _convert(term: Term, args) -> int:
    suffix = Path(args.out).suffix.lower().lstrip(".")
    if suffix != args.to:
        raise _Usage(f"--to {args.to}와 저장할 파일의 확장자(.{suffix or '없음'})가 다릅니다.",
                     f"예: rigorloom convert {Path(args.path).name} --to {args.to} "
                     f"-o {Path(args.out).stem or '결과'}.{args.to}")
    if Path(args.path).suffix.lower().lstrip(".") == args.to:
        raise _Usage(f"원래 문서도 .{args.to} 형식입니다.",
                     f'초안을 다른 이름으로 저장하려면: rigorloom save "{args.path}" --to "{args.out}"')
    ctx = _context(args)
    ctx.create_only = not args.force
    envelope = call(ctx, "save", {"path": args.path, "to": args.out})
    # Converting a file with no draft: save treats a format change as an export.
    return _emit(term, args, "convert", envelope)


def _discard(term: Term, args) -> int:
    ctx = _context(args)
    try:
        ref = rt_toolset.resolve(ctx, args.path)
        envelope = {"ok": True, "result": ctx.drafts.discard(ref)}
    except ToolError as exc:
        envelope = {"ok": False, "error": exc.to_dict()}
    if envelope["ok"] and not args.json:
        term.line(f"초안을 버렸습니다: {shown(args.path)}")
        term.line(term.dim(f"버린 초안은 여기 보관합니다: {envelope['result']['keptAt']}"))
        return EXIT_OK
    return _emit(term, args, "changes", envelope)


#: What ``changes clean`` looks in: only folders Rigorloom made inside its
#: state directory, never the directory itself (RIGORLOOM_HOME may point anywhere).
STATE_PARTS = ("drafts", "drafts-discarded", "previews", "exports", "history")
#: The state directory's retention limit: ``changes clean`` removes what has
#: not changed for this many days, except drafts with unsaved work.
RETENTION_DAYS = 30


def _newest_mtime(path: Path) -> float:
    newest = path.lstat().st_mtime
    if path.is_dir() and not path.is_symlink():
        for child in path.rglob("*"):
            try:
                newest = max(newest, child.lstat().st_mtime)
            except OSError:
                continue
    return newest


def _has_unsaved_work(folder: Path) -> bool:
    try:
        record = json.loads((folder / "draft.json").read_text(encoding="utf-8"))
        head = record.get("head") or {}
        return bool(head) and head.get("sha256") != (record.get("source") or {}).get("sha256")
    except (OSError, ValueError, AttributeError):
        return True  # cannot tell: keep it


def _clean_plan(home: Path, older_than: int, everything: bool) -> tuple[list[Path], int]:
    """(entries to remove, unsaved drafts kept). Entries are children of STATE_PARTS."""
    import time
    if everything:
        return [home / part for part in STATE_PARTS if (home / part).exists()], 0
    cutoff = time.time() - older_than * 86400
    remove, kept = [], 0
    for part in STATE_PARTS:
        root = home / part
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            try:
                if _newest_mtime(entry) >= cutoff:
                    continue
            except OSError:
                continue
            if part == "drafts" and _has_unsaved_work(entry):
                kept += 1
                continue
            remove.append(entry)
    return remove, kept


def _clean(term: Term, args) -> int:
    import shutil
    if args.older_than < 0:
        raise _Usage("--older-than에 0 이상의 일수를 입력하세요.", "예: --older-than 30")
    home = state_home()
    if any((home / part).exists() for part in STATE_PARTS) and \
            not (home / STATE_MARKER).exists():
        return _emit(term, args, "changes", {"ok": False, "error": ToolError(
            "invalid_params", f"Rigorloom 상태 폴더가 아닌 것 같아 지우지 않았습니다({home}).",
            hint="RIGORLOOM_HOME이 가리키는 폴더를 확인하세요.").to_dict()})
    remove, kept = _clean_plan(home, args.older_than, args.all)
    scope = "모두" if args.all else f"{args.older_than}일 넘게 쓰지 않은 것"
    if not remove:
        if args.json:
            return _emit(term, args, "changes", {"ok": True, "result": {
                "action": "clean", "removed": [], "keptUnsaved": kept}})
        term.line(f"지울 것이 없습니다 ({scope})."
                  + (f" 저장 안 한 초안 {kept}개는 남겼습니다." if kept else ""))
        return EXIT_OK
    if not args.yes:
        sys.stderr.write(f"  위치: {home}\n  지울 항목: {len(remove)}개 ({scope})\n"
                         "  지운 저장 기록은 undo로 되돌릴 수 없습니다.\n")
        answer = confirm("초안, 미리보기, 저장 기록을 지울까요?")
        if answer is not True:
            code = "declined_by_person" if answer is False else "needs_person"
            return _emit(term, args, "changes", {"ok": False, "error": ToolError(
                code, "아무것도 지우지 않았습니다.",
                hint="묻지 않고 지우려면 같은 명령에 --yes를 붙이세요." if answer is None else None,
            ).to_dict()})
    for entry in remove:
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    if args.json:
        return _emit(term, args, "changes", {"ok": True, "result": {
            "action": "clean", "removed": [str(p) for p in remove], "keptUnsaved": kept}})
    term.line(f"{len(remove)}개를 지웠습니다 ({scope}). 위치: {home}"
              + (f"\n저장 안 한 초안 {kept}개는 남겼습니다. 모두 지우려면 --all" if kept else ""))
    return EXIT_OK


def main(argv: list[str]) -> int:
    if argv[:1] == ["mcp"]:
        # stdio belongs to the protocol: no reconfiguring, no human output.
        try:
            from . import rt_mcp
        except ImportError:
            import rt_mcp
        return rt_mcp.main(argv[1:])
    try:
        return _main(argv)
    except BrokenPipeError:
        # `rigorloom read big.hwpx | head`: the reader left; that is not an error.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return EXIT_OK


def _usage(exc: "_Usage", argv: list[str]) -> int:
    hint = exc.hint or f"도움말: rigorloom {argv[0] if argv else ''} --help"
    if "--json" in argv:
        sys.stdout.write(json.dumps({"ok": False, "command": argv[0] if argv else None,
                                     "error": {"code": "invalid_params",
                                               "message": safe_text(str(exc)),
                                               "hint": safe_text(hint), "retryable": False}},
                                    ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stderr.write(f"{safe_text(str(exc))}\n  {safe_text(hint)}\n")
    return EXIT_USAGE


def _main(argv: list[str]) -> int:
    prepare_stdio()
    if wants_product_help(argv):
        sys.stdout.write(help_text())
        return EXIT_OK
    if argv and not argv[0].startswith("-") and argv[0] not in PRODUCT_VERBS:
        return _usage(_unknown(argv[0]), argv)
    if argv[:1] == ["changes"] and len(argv) > 1 and not argv[1].startswith("-") \
            and argv[1] not in ("list", "show", "discard", "clean"):
        argv = ["changes", "show", *argv[1:]]  # `changes FILE`, as --help shows it
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help
        return int(exc.code or 0) and EXIT_USAGE
    except _Usage as exc:
        return _usage(exc, argv)
    if getattr(args, "out", None) == "" or (args.verb == "save" and args.to == ""):
        # An empty name must not quietly mean "the source" (review re-check F6).
        return _usage(_Usage("저장할 경로가 비어 있습니다.",
                             "보고서.hwpx처럼 파일 이름을 포함한 경로를 입력하세요."), argv)
    term = Term.detect(getattr(args, "color", "auto"))
    if getattr(args, "debug", False):
        os.environ["RIGORLOOM_DEBUG"] = "1"
    try:
        if args.verb == "undo":
            return _undo(term, args)
        if args.verb == "convert":
            return _convert(term, args)
        if args.verb == "changes" and args.action == "clean":
            return _clean(term, args)
        if args.verb == "changes" and args.action == "discard":
            if not args.path:
                raise _Usage("어느 초안을 버릴지 지정하지 않았습니다.",
                             "예: rigorloom changes discard 보고서.hwpx")
            return _discard(term, args)
        tool, req = request_for(args)
    except _Usage as exc:
        return _usage(exc, argv)
    ctx = _context(args)
    out = getattr(args, "out", None)
    if out and not getattr(args, "force", False):
        ctx.create_only = True
        # -o names a file to create; replacing one takes --force (the old
        # bytes still go to history first).
        try:
            exists = canonical(out).exists()
        except PathRefused as exc:
            return _emit(term, args, args.verb, {"ok": False, "error": ToolError(
                exc.code, exc.message, at=exc.path).to_dict()})
        if exists:
            return _emit(term, args, args.verb, {"ok": False, "error": ToolError(
                "target_exists", f"저장하려는 이름의 파일이나 폴더가 이미 있습니다({out}).",
                hint="덮어쓰려면 --force를 붙이세요. 이전 내용은 저장 기록에 남습니다. undo로 되돌릴 수 있습니다.",
                at=out).to_dict()})
    if out and tool in ("edit", "fill", "new"):
        import secrets
        ctx.draft_scope = "cli-" + secrets.token_hex(4)
    if tool in ("edit", "fill") and "base" not in req:
        # A person on the CLI edits what is there now; staleness protects
        # agents that read earlier, not a person typing one command.
        ctx_read = Context(client="cli", source="draft", _drafts=ctx.drafts,
                           draft_scope=ctx.draft_scope)
        try:
            ref = rt_toolset.resolve(ctx_read, req["path"])
            req["base"] = ctx_read.drafts.input_for(ref).rev
        except ToolError as exc:
            return _emit(term, args, args.verb, {"ok": False, "error": exc.to_dict()})
    envelope = call(ctx, tool, req)
    if envelope["ok"] and out and tool in ("edit", "fill", "new"):
        envelope = _save_after(ctx, args, envelope["result"]["path"])
        return _emit(term, args, "save", envelope)
    code = _emit(term, args, args.verb, envelope)
    if envelope["ok"] and not args.json and getattr(args, "source", None) == "disk" \
            and tool in ("read", "find", "check", "preview"):
        note = _draft_note(ctx, req["path"])
        if note:
            sys.stderr.write(term.style(note, "yellow") + "\n"
                             if Term.detect(args.color, sys.stderr).color else note + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
