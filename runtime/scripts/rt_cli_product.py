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
import sys
from pathlib import Path

import rt_toolset  # noqa: F401 - registers the tools
from rt_term import Term, confirm, prepare_stdio
from rt_tools import Context, ToolError, call, get, render_text

#: Verbs this module owns. ``open`` collides with the legacy protocol verb;
#: cli.main sends ``open`` here only when no global --root/--engine-root
#: precedes it (every legacy ``open`` has one).
PRODUCT_VERBS = ("open", "outline", "read", "find", "edit", "fill", "new",
                 "preview", "check", "save", "changes", "undo", "convert", "guide")

LEGACY_GLOBALS = ("--root", "--engine-root")
LEGACY_ALWAYS = ("install", "doctor", "guard", "style", "engine", "ui", "demo")

EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_INTERNAL = 0, 2, 3, 4

HELP = """\
rigorloom — 한글·워드·마크다운 문서를 사람과 에이전트가 같이 고치는 도구

읽기
  open FILE            문서 구조: 쪽, 글꼴, 제목, 표, 입력란과 주소
  read FILE [--at 주소] 본문 읽기 (긴 글은 --cursor로 이어 읽기)
  find FILE 말          찾은 곳마다 주소
  preview FILE         쪽 그림 (PNG)

쓰기 (원본은 save 전까지 그대로)
  edit FILE --op JSON  고치기: set, replace, insert_after, delete, table.*
  fill FILE --set 칸=값  양식 채우기 (서명·날인 칸은 사람 몫)
  new 내용.md            마크다운으로 새 문서
  save FILE [--to 경로]  초안을 파일로 저장 (덮어쓰기는 물어봄, undo 가능)
  convert FILE --to pdf -o OUT

점검과 기록
  check FILE           문체·쪽 배치·글꼴·숫자 바뀜 점검
  changes [FILE]       초안과 변경 기록
  undo FILE            마지막 저장 되돌리기
  guide [주제]           공문·보고서·양식 작성 안내

공통 옵션: --json (기계용 출력)  --source disk|draft  --color auto|always|never

앱·설치: ui  doctor  engine  install  demo  guard  style
프로토콜 명령 (--root 필요): capabilities sessions inspect read-region render
  geometry events modules module-check propose validate plan request-approval
  approval approve reject apply candidates compare receipt verify
  자세히: rigorloom protocol --help
"""


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


# --------------------------------------------------------------------------
# argv -> typed request
# --------------------------------------------------------------------------

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="기계용 JSON 한 덩어리로 출력")
    p.add_argument("--source", choices=("disk", "draft"), default="disk",
                   help="읽을 대상: 디스크의 파일(기본) 또는 초안")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    p.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)


def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="rigorloom", add_help=False)
    sub = root.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("open", help="문서 구조"); p.add_argument("path"); _common(p)
    p = sub.add_parser("outline", help="문서 구조 (open과 같음)"); p.add_argument("path"); _common(p)

    p = sub.add_parser("read", help="본문 읽기")
    p.add_argument("path"); p.add_argument("--at")
    p.add_argument("--cursor"); p.add_argument("--max-chars", type=int)
    p.add_argument("--runs", action="store_true"); _common(p)

    p = sub.add_parser("find", help="찾기")
    p.add_argument("path"); p.add_argument("query")
    p.add_argument("--regex", action="store_true"); p.add_argument("--scope")
    p.add_argument("--limit", type=int); _common(p)

    p = sub.add_parser("edit", help="고치기")
    p.add_argument("path")
    p.add_argument("--op", action="append", default=[], metavar="JSON")
    p.add_argument("--ops-file")
    p.add_argument("--base", help="읽었던 rev (생략하면 지금 판)")
    p.add_argument("-o", "--out", help="고친 결과를 이 파일로 저장")
    p.add_argument("--force", action="store_true", help="-o 대상이 있으면 덮어씀 (이전 판은 이력에)")
    _common(p)

    p = sub.add_parser("fill", help="양식 채우기")
    p.add_argument("path")
    p.add_argument("--set", action="append", default=[], metavar="칸=값")
    p.add_argument("--values", help="칸→값 JSON 파일 (- 이면 표준 입력)")
    p.add_argument("--base")
    p.add_argument("-o", "--out"); p.add_argument("--force", action="store_true")
    _common(p)

    p = sub.add_parser("new", help="새 문서")
    p.add_argument("markdown", help="마크다운 파일 (- 이면 표준 입력)")
    p.add_argument("--form"); p.add_argument("--name")
    p.add_argument("-o", "--out"); _common(p)

    p = sub.add_parser("preview", help="쪽 그림")
    p.add_argument("path"); p.add_argument("--page", type=int, action="append")
    p.add_argument("--changed", action="store_true"); p.add_argument("--scale", type=float)
    _common(p)

    p = sub.add_parser("check", help="점검")
    p.add_argument("path"); p.add_argument("--against")
    p.add_argument("--pack", choices=("gongmun", "minwon", "hr", "grant"))
    p.add_argument("--only", action="append",
                   choices=("style", "layout", "fonts", "guard"))
    _common(p)

    p = sub.add_parser("save", help="초안 저장")
    p.add_argument("path"); p.add_argument("--to"); _common(p)

    p = sub.add_parser("changes", help="초안과 변경 기록")
    p.add_argument("action", nargs="?", default="list", choices=("list", "show", "discard"))
    p.add_argument("path", nargs="?"); p.add_argument("--id"); _common(p)

    p = sub.add_parser("undo", help="마지막 저장 되돌리기")
    p.add_argument("path"); _common(p)

    p = sub.add_parser("convert", help="형식 바꾸기")
    p.add_argument("path"); p.add_argument("--to", required=True,
                                           choices=("hwpx", "hwp", "pdf", "png", "md", "docx"))
    p.add_argument("-o", "--out", required=True); p.add_argument("--force", action="store_true")
    _common(p)

    p = sub.add_parser("guide", help="작성 안내")
    p.add_argument("topic", nargs="?"); _common(p)
    return root


class _Usage(Exception):
    pass


def _read_text_arg(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    try:
        return Path(value).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise _Usage(f"읽을 수 없습니다: {value} ({exc.strerror or exc})") from exc


def _ops(args) -> list:
    ops: list = []
    if args.ops_file:
        try:
            payload = json.loads(_read_text_arg(args.ops_file))
        except ValueError as exc:
            raise _Usage(f"--ops-file이 JSON이 아닙니다: {exc}") from exc
        payload = payload.get("ops", payload) if isinstance(payload, dict) else payload
        if not isinstance(payload, list):
            raise _Usage("--ops-file에는 작업 배열이 있어야 합니다.")
        ops.extend(payload)
    for index, text in enumerate(args.op):
        try:
            ops.append(json.loads(text))
        except ValueError as exc:
            raise _Usage(f"--op {index + 1}번째가 JSON이 아닙니다: {exc}") from exc
    if not ops:
        raise _Usage("고칠 내용이 없습니다. --op '{\"op\":\"set\",...}' 또는 --ops-file")
    return ops


def _values(args) -> dict:
    values: dict = {}
    if args.values:
        try:
            loaded = json.loads(_read_text_arg(args.values))
        except ValueError as exc:
            raise _Usage(f"--values가 JSON이 아닙니다: {exc}") from exc
        if not isinstance(loaded, dict):
            raise _Usage("--values에는 {칸: 값} 객체가 있어야 합니다.")
        values.update(loaded)
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise _Usage(f"--set은 칸=값 꼴이어야 합니다: {item}")
        values[key.strip()] = value
    if not values:
        raise _Usage("채울 값이 없습니다. --set 칸=값 또는 --values 파일")
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
        if args.to: req["to"] = args.to
        return "save", req
    if v == "changes":
        req: dict = {"action": "show" if args.path and args.action == "list" else args.action}
        if args.path: req["path"] = args.path
        if args.id: req["id"] = args.id
        return "changes", req
    if v == "guide":
        return "guide", ({"topic": args.topic} if args.topic else {})
    raise _Usage(f"모르는 명령: {v}")


# --------------------------------------------------------------------------
# running and printing
# --------------------------------------------------------------------------

def _context(args) -> Context:
    def ask(question: str, detail: dict) -> bool | None:
        pages = detail.get("changedPages") or []
        lines = [question]
        if pages:
            lines.append(f"  바뀐 쪽: {', '.join(map(str, pages))}")
        if detail.get("unreviewed"):
            lines.append(f"  사람이 아직 검토하지 않은 변경 묶음: {detail['unreviewed']}개")
        if detail.get("lossy"):
            lines.append("  변환하며 빠지는 것: " + ", ".join(detail["lossy"]))
        lines.append(f"  되돌리기: {detail.get('undo')}")
        sys.stderr.write("\n".join(lines[1:]) + "\n")
        return confirm(lines[0])
    return Context(client="cli", roots=None, source=getattr(args, "source", "disk"),
                   ask=ask)


def _emit(term: Term, args, verb: str, envelope: dict) -> int:
    if envelope["ok"]:
        code = EXIT_OK
        if verb == "check" and not envelope["result"].get("pass", True):
            code = EXIT_REFUSED
    else:
        code = _codes().get(envelope["error"]["code"], EXIT_INTERNAL)
    if args.json:
        payload = {"ok": envelope["ok"], "command": verb}
        payload["result" if envelope["ok"] else "error"] = (
            envelope["result"] if envelope["ok"] else envelope["error"])
        data = payload.get("error", {}).get("data") or {}
        if "trace" in data and not getattr(args, "debug", False):
            data.pop("trace")
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return code
    if envelope["ok"]:
        tool = get(_TOOL_OF.get(verb, verb) if verb != "convert" else "save")
        term.line(render_text(tool, envelope["result"]))
        return code
    err = envelope["error"]
    sys.stderr.write(f"{err['message']}\n")
    if err.get("hint"):
        sys.stderr.write(f"  {err['hint']}\n")
    if err.get("candidates"):
        sys.stderr.write("  후보: " + ", ".join(err["candidates"][:8]) + "\n")
    if getattr(args, "debug", False) and err.get("data"):
        sys.stderr.write(json.dumps(err["data"], ensure_ascii=False, indent=2) + "\n")
    return code


_TOOL_OF = {"outline": "open"}


def _codes():
    from rt_tools import ERROR_EXIT
    return ERROR_EXIT


def _save_after(ctx: Context, args, path: str) -> dict:
    """``-o OUT`` on edit/fill/new: stage, then save to OUT."""
    from rt_tools import call as _call
    req = {"path": path, "to": args.out}
    if getattr(args, "force", False):
        ctx.ask = lambda q, d: True  # the person typed --force for this target
    return _call(ctx, "save", req)


def _undo(term: Term, args) -> int:
    import rt_commit
    from rt_paths import canonical
    target = canonical(args.path)
    answer = confirm(f"{target}을(를) 마지막 저장 전으로 되돌릴까요?")
    if answer is None:
        envelope = {"ok": False, "error": ToolError(
            "needs_person", "되돌리기는 사람이 터미널에서 직접 확인해야 합니다.",
            hint=f'터미널에서 실행: rigorloom undo "{target}"').to_dict()}
    elif not answer:
        envelope = {"ok": False, "error": ToolError(
            "declined_by_person", "되돌리지 않았습니다.").to_dict()}
    else:
        try:
            envelope = {"ok": True, "result": rt_commit.undo(target, by="cli")}
        except ToolError as exc:
            envelope = {"ok": False, "error": exc.to_dict()}
    if envelope["ok"] and not args.json:
        r = envelope["result"]
        term.line(f"되돌렸습니다: {r['target']}" if not r["removed"]
                  else f"Rigorloom이 만든 파일을 이력으로 옮겼습니다: {r['target']}")
        return EXIT_OK
    return _emit(term, args, "undo", envelope)


def _convert(term: Term, args) -> int:
    ctx = _context(args)
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
        term.line(f"초안을 버렸습니다. 보관 위치: {envelope['result']['keptAt']}")
        return EXIT_OK
    return _emit(term, args, "changes", envelope)


def main(argv: list[str]) -> int:
    prepare_stdio()
    if wants_product_help(argv):
        sys.stdout.write(HELP)
        return EXIT_OK
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) and EXIT_USAGE
    term = Term.detect(getattr(args, "color", "auto"))
    try:
        if args.verb == "undo":
            return _undo(term, args)
        if args.verb == "convert":
            return _convert(term, args)
        if args.verb == "changes" and args.action == "discard":
            if not args.path:
                raise _Usage("버릴 초안의 파일을 적어 주세요.")
            return _discard(term, args)
        tool, req = request_for(args)
    except _Usage as exc:
        sys.stderr.write(f"{exc}\n  도움말: rigorloom {argv[0]} --help\n")
        return EXIT_USAGE
    ctx = _context(args)
    if tool in ("edit", "fill") and "base" not in req:
        # A person on the CLI edits what is there now; staleness protects
        # agents that read earlier, not a person typing one command.
        ctx_read = Context(client="cli", source="draft", _drafts=ctx.drafts)
        try:
            ref = rt_toolset.resolve(ctx_read, req["path"])
            req["base"] = ctx_read.drafts.input_for(ref).rev
        except ToolError as exc:
            return _emit(term, args, args.verb, {"ok": False, "error": exc.to_dict()})
    envelope = call(ctx, tool, req)
    if envelope["ok"] and getattr(args, "out", None) and tool in ("edit", "fill", "new"):
        envelope = _save_after(ctx, args, envelope["result"]["path"])
        return _emit(term, args, "save", envelope)
    return _emit(term, args, args.verb, envelope)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
