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
import sys
from pathlib import Path

try:  # installed as rigorloom_runtime
    from . import rt_commit, rt_toolset  # rt_toolset registers the tools
    from .rt_cli_render import SHOW
    from .rt_paths import PathRefused, canonical, state_home
    from .rt_term import Term, confirm, is_console, pad, prepare_stdio
    from .rt_tools import ERROR_EXIT, Context, ToolError, call, get, render_text
except ImportError:  # a checkout, runtime/scripts on sys.path
    import rt_commit
    import rt_toolset
    from rt_cli_render import SHOW
    from rt_paths import PathRefused, canonical, state_home
    from rt_term import Term, confirm, is_console, pad, prepare_stdio
    from rt_tools import ERROR_EXIT, Context, ToolError, call, get, render_text

#: Verbs this module owns. ``open`` collides with the legacy protocol verb;
#: cli.main sends ``open`` here only when no global --root/--engine-root
#: precedes it (every legacy ``open`` has one).
PRODUCT_VERBS = ("open", "outline", "read", "find", "edit", "fill", "new",
                 "preview", "check", "save", "changes", "undo", "convert", "guide")

LEGACY_GLOBALS = ("--root", "--engine-root")
LEGACY_ALWAYS = ("install", "doctor", "guard", "style", "engine", "ui", "demo")

EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_INTERNAL = 0, 2, 3, 4

#: The top-level help, one (usage, what it does) row per verb. Usage columns
#: are padded by terminal width, so Korean in a usage still lines up.
HELP_SECTIONS = (
    ("읽기", (
        ("open FILE", "문서 구조: 쪽, 글꼴, 제목, 표, 채울 칸과 주소"),
        ("read FILE [--at 주소]", "본문 읽기 (긴 글은 --cursor로 이어 읽기)"),
        ("find FILE 말", "찾은 곳마다 주소"),
        ("preview FILE", "쪽 그림 (PNG)"),
    )),
    ("쓰기 (원본은 save 전까지 그대로)", (
        ("edit FILE --op JSON", "고치기: set, replace, insert_after, delete, table.*"),
        ("fill FILE --set 칸=값", "양식 채우기 (서명·날인 칸은 사람 몫)"),
        ("new 내용.md", "마크다운으로 새 문서"),
        ("save FILE [--to 경로]", "초안을 파일로 저장 (덮어쓰기는 물어봄, undo 가능)"),
        ("convert FILE --to pdf -o OUT", ""),
    )),
    ("점검과 기록", (
        ("check FILE", "문체·쪽 배치·글꼴·숫자 바뀜 점검"),
        ("changes [FILE]", "초안과 변경 기록"),
        ("undo FILE", "마지막 저장 되돌리기"),
        ("guide [주제]", "공문·보고서·양식 작성 안내"),
    )),
)
HELP_TAIL = """\
공통 옵션: --json (기계용 출력)  --source disk|draft  --color auto|always|never

앱·설치: ui  doctor  engine  install  demo  guard  style
프로토콜 명령 (--root 필요): capabilities sessions inspect read-region render
  geometry events modules module-check propose validate plan request-approval
  approval approve reject apply candidates compare receipt verify
  자세히: rigorloom protocol --help
"""
HELP_USAGE_COLUMNS = 21


def help_text() -> str:
    lines = ["rigorloom — 한글·워드·마크다운 문서를 사람과 에이전트가 같이 고치는 도구", ""]
    for title, rows in HELP_SECTIONS:
        lines.append(title)
        for usage, what in rows:
            if not what:
                lines.append(f"  {usage}")
                continue
            lines.append(f"  {pad(usage, HELP_USAGE_COLUMNS)} {what}")
        lines.append("")
    return "\n".join(lines) + HELP_TAIL


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
    p.add_argument("--force", action="store_true", help="-o 대상이 있으면 덮어씀 (이전 판은 저장 기록에)")
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
    p.add_argument("-o", "--out"); p.add_argument("--force", action="store_true")
    _common(p)

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
    p.add_argument("path"); p.add_argument("--to")
    p.add_argument("--force", action="store_true",
                   help="있는 파일을 묻지 않고 덮어씀 (이전 판은 저장 기록에 남음)")
    _common(p)

    p = sub.add_parser("changes", help="초안과 변경 기록")
    p.add_argument("action", nargs="?", default="list",
                   choices=("list", "show", "discard", "clean"))
    p.add_argument("path", nargs="?"); p.add_argument("--id")
    p.add_argument("--older-than", type=int, metavar="일", default=RETENTION_DAYS,
                   help=f"clean: 이 날수보다 오래된 것만 지움 (기본 {RETENTION_DAYS}일)")
    p.add_argument("--all", action="store_true",
                   help="clean: 저장 안 한 초안까지 모두 지움")
    p.add_argument("--yes", action="store_true", help="clean: 묻지 않고 지움")
    _common(p)

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
                     "파일 이름과 위치를 확인하세요.") from exc


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
                     """--op '{"op":"set","at":"p1","text":"…"}' 또는 --ops-file 파일로 주세요.""")
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
        raise _Usage("채울 값이 없습니다.", "--set 성명=홍길동처럼 칸과 값을 주세요.")
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
    raise _Usage(f"지원하지 않는 명령입니다({v}).", "명령 목록: rigorloom --help")


# --------------------------------------------------------------------------
# running and printing
# --------------------------------------------------------------------------

def _context(args) -> Context:
    def ask(question: str, detail: dict) -> bool | None:
        if getattr(args, "force", False):
            return True  # the person named this target and typed --force
        if not (is_console(sys.stdin) and is_console(sys.stderr)):
            return None
        pages = detail.get("changedPages") or []
        lines = [question]
        if pages:
            lines.append(f"  바뀐 쪽: {', '.join(map(str, pages))}")
        if detail.get("unreviewed"):
            lines.append(f"  사람이 아직 검토하지 않은 변경 묶음: {detail['unreviewed']}개")
        if detail.get("lossy"):
            lines.append("  변환하며 빠지는 것: " + ", ".join(detail["lossy"]))
        if detail.get("fontsSubstituted"):
            pairs = ", ".join(f"{s.get('want')} → {s.get('got')}"
                              for s in detail["fontsSubstituted"])
            lines.append(f"  글꼴 대체: {pairs} (쪽 나눔이 한글과 다를 수 있음)")
        lines.append(f"  되돌리기: {detail.get('undo')}")
        sys.stderr.write("\n".join(lines[1:]) + "\n")
        return confirm(lines[0])
    return Context(client="cli", roots=None, source=getattr(args, "source", "disk"),
                   ask=ask)


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
    sys.stderr.write(f"{err['message']}\n")
    if err.get("hint"):
        sys.stderr.write(f"  {err['hint']}\n")
    if err.get("candidates"):
        sys.stderr.write("  후보: " + ", ".join(err["candidates"][:8]) + "\n")
    if getattr(args, "debug", False) and err.get("data"):
        sys.stderr.write(json.dumps(err["data"], ensure_ascii=False, indent=2) + "\n")
    return code


_TOOL_OF = {"outline": "open", "convert": "save"}


def _save_after(ctx: Context, args, path: str) -> dict:
    """``-o OUT`` on edit/fill/new: stage in a private draft, save to OUT, and
    drop that draft; the shared draft of the same file is never touched."""
    req = {"path": path, "to": args.out}
    try:
        return call(ctx, "save", req)
    finally:
        try:
            ctx.drafts.remove(rt_toolset.resolve(ctx, path))
        except ToolError:
            pass


def _undo(term: Term, args) -> int:
    try:
        target = canonical(args.path)
    except PathRefused as exc:
        return _emit(term, args, "undo", {"ok": False, "error": ToolError(
            exc.code, exc.message, at=exc.path).to_dict()})
    answer = confirm(f"{target}을(를) 마지막 저장 전으로 되돌릴까요?")
    if answer is None:
        envelope = {"ok": False, "error": ToolError(
            "needs_person", "되돌리기는 사람이 터미널에서 직접 확인해야 합니다.",
            hint=f'터미널에서 직접 rigorloom undo "{target}" 명령을 실행하세요.').to_dict()}
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
                  else f"Rigorloom이 만든 파일을 저장 기록으로 옮겼습니다: {r['target']}")
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
        raise _Usage("--older-than에는 0 이상의 날수를 입력해야 합니다.", "예: --older-than 30")
    home = state_home()
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


def _main(argv: list[str]) -> int:
    prepare_stdio()
    if wants_product_help(argv):
        sys.stdout.write(help_text())
        return EXIT_OK
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) and EXIT_USAGE
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
        sys.stderr.write(f"{exc}\n  {exc.hint or f'도움말: rigorloom {argv[0]} --help'}\n")
        return EXIT_USAGE
    ctx = _context(args)
    out = getattr(args, "out", None)
    if out and not getattr(args, "force", False):
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
                hint="덮어쓰려면 --force를 붙이세요. 이전 판은 저장 기록에 남아 undo로 되돌릴 수 있습니다.",
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
    return _emit(term, args, args.verb, envelope)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
