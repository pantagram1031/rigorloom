"""Adapter/worker isolation, story_edit receipt refusal, and doc boundary tests (S8)."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
PIPELINE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"
AGENTHOST_SCRIPTS = REPO_ROOT / "agenthost" / "scripts"

for p in (RUNTIME_SCRIPTS, PIPELINE_SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rt_apply  # noqa: E402
import rt_core  # noqa: E402
import story_edit  # noqa: E402
import story_graph  # noqa: E402
from rt_codes import RpcError  # noqa: E402

TIMEOUT = 60

RAW_WORKER_MODULES = frozenset({
    "preedit",
    "xml_backend",
    "com_backend",
    "story_edit",
    "fill_report",
    "build_report",
    "tidy_hwpx",
})
RAW_WORKER_SCRIPTS = frozenset({f"{name}.py" for name in RAW_WORKER_MODULES})

FORBIDDEN_MONTHS_RE = re.compile(
    r"\b(?:January|February|March|April|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b"
)
DATE_OR_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}(?:-\d{2}-\d{2})?\b")
MARKETING_RE = re.compile(
    r"\b(?:revolutionary|world-class|best-in-class|cutting-edge|next-gen|next-generation"
    r"|enterprise-grade|production-ready|seamless(?:ly)?|effortless(?:ly)?|state-of-the-art|magic(?:al)?)\b",
    re.IGNORECASE,
)


def _adapter_files() -> list[Path]:
    files = [
        RUNTIME_SCRIPTS / "cli.py",
        RUNTIME_SCRIPTS / "rt_server.py",
        RUNTIME_SCRIPTS / "mcp_server.py",
        RUNTIME_SCRIPTS / "rt_ui.py",
    ]
    agenthost_py = sorted(AGENTHOST_SCRIPTS.glob("*.py"))
    assert agenthost_py, "expected agenthost/scripts/*.py adapter files"
    files.extend(agenthost_py)
    return files


def test_adapters_cannot_import_or_invoke_raw_edit_workers():
    for adapter in _adapter_files():
        assert adapter.is_file(), f"missing adapter {adapter}"
        source = adapter.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(adapter))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    leaf = alias.name.split(".")[-1]
                    assert leaf not in RAW_WORKER_MODULES, f"{adapter.name} imports {alias.name}"
                    assert leaf != "rt_apply", f"{adapter.name} directly imports rt_apply"
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").lstrip(".")
                leaf = mod.split(".")[-1] if mod else ""
                assert leaf not in RAW_WORKER_MODULES, f"{adapter.name} imports from {node.module}"
                if leaf == "rt_apply":
                    imported_names = {alias.name for alias in node.names}
                    # Only Cancelled exception class is shared by rt_server; never apply_plan/publish.
                    assert imported_names <= {"Cancelled"}, (
                        f"{adapter.name} imports forbidden rt_apply symbols: {sorted(imported_names)}"
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for script_name in RAW_WORKER_SCRIPTS:
                    assert script_name not in node.value, (
                        f"{adapter.name} embeds raw worker script reference {script_name!r}"
                    )


def _minimal_story_hwpx(path: Path) -> Path:
    hp = story_graph.PARAGRAPH_NS
    hs = story_graph.SECTION_NS
    hc = story_graph.CORE_NS
    opf = story_graph.OPF_NS
    ocf = story_graph.OCF_NS
    container_xml = (
        f'<ocf:container xmlns:ocf="{ocf}"><ocf:rootfiles>'
        '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
        "</ocf:rootfiles></ocf:container>"
    )
    hpf_xml = (
        f'<opf:package xmlns:opf="{opf}" id="" unique-identifier="" version="">'
        "<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>"
        "<opf:manifest>"
        '<opf:item id="header-def" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section-def" href="Contents/section0.xml" media-type="application/xml"/>'
        "</opf:manifest><opf:spine><opf:itemref idref=\"section-def\"/></opf:spine></opf:package>"
    )
    header_xml = f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"/>'
    section_xml = (
        f'<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}" xmlns:hc="{hc}">'
        '<hp:p><hp:run charPrIDRef="0"><hp:t>MAIN-BODY</hp:t>'
        '<hp:ctrl><hp:header id="HDR-1" applyPageType="BOTH">'
        '<hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>ORIGINAL-HEADER</hp:t></hp:run></hp:p>'
        "</hp:subList></hp:header></hp:ctrl></hp:run></hp:p><hp:secPr/></hs:sec>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", b"application/hwp+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("Contents/content.hpf", hpf_xml)
        zf.writestr("Contents/header.xml", header_xml)
        zf.writestr("Contents/section0.xml", section_xml)
    return path


def test_story_edit_receipts_are_refused_by_rt_apply_read_receipt(tmp_path: Path):
    source = _minimal_story_hwpx(tmp_path / "story-source.hwpx")
    graph = story_graph.inspect_story_graph(source)
    header_story = next(
        story
        for member in graph["members"]
        for story in member.get("stories", [])
        if story["role"] == "header"
    )
    op = {
        "schema": "rigorloom/hwpx-story-edit/v1",
        "expected_input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selector": {
            "schema": "rigorloom/hwpx-story-edit-selector/v1",
            "address": f"{header_story['address']}/paragraph[0]",
        },
        "replacement": "UPDATED-HEADER",
    }
    edited_hwpx = tmp_path / "story-edited.hwpx"
    story_receipt_path = tmp_path / "story-receipt.json"
    story_receipt = story_edit.apply_story_edit(source, op, edited_hwpx, story_receipt_path)
    assert story_receipt["status"] == "passed"

    root = tmp_path / "runtime-root"
    core = rt_core.RuntimeCore(root, engine_root=REPO_ROOT)
    opened = core.open_path(str(source))
    session_id = (opened.get("session") or opened)["sessionId"]
    session = core.store.get(session_id)

    run_id = "run-story-edit-foreign"
    cand_dir = session.candidates_dir / run_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    (cand_dir / "artifact.hwpx").write_bytes(edited_hwpx.read_bytes())
    (cand_dir / "receipt.json").write_text(story_receipt_path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RpcError) as raw_exc:
        rt_apply.read_receipt(session, run_id)
    assert raw_exc.value.code == "receipt_body_mismatch"

    with pytest.raises(RpcError) as core_exc:
        core.receipt_read(session_id, run_id)
    assert core_exc.value.code == "receipt_body_mismatch"

    # Even adding a matching candidate pointer still lacks runtime receipt integrity binding.
    hybrid_receipt = dict(story_receipt)
    edited_bytes = edited_hwpx.read_bytes()
    hybrid_receipt["candidate"] = {
        "path": "artifact.hwpx",
        "sha256": hashlib.sha256(edited_bytes).hexdigest(),
        "bytes": len(edited_bytes),
    }
    (cand_dir / "receipt.json").write_text(json.dumps(hybrid_receipt), encoding="utf-8")
    with pytest.raises(RpcError) as hybrid_exc:
        rt_apply.read_receipt(session, run_id)
    assert hybrid_exc.value.code == "receipt_body_mismatch"


def test_architecture_and_protocol_docs_match_implemented_boundaries():
    arch_path = REPO_ROOT / "docs" / "architecture.md"
    proto_path = REPO_ROOT / "docs" / "runtime-protocol-v0.md"
    arch_text = arch_path.read_text(encoding="utf-8")
    proto_text = proto_path.read_text(encoding="utf-8")

    non_empty = [line for line in arch_text.splitlines() if line.strip()]
    assert 10 <= len(non_empty) <= 65
    assert len(arch_text) <= 5000

    assert "**" not in arch_text, "architecture.md must use plain prose without bold markers"
    assert DATE_OR_YEAR_RE.search(arch_text) is None, "architecture.md must not include dates or years"
    assert FORBIDDEN_MONTHS_RE.search(arch_text) is None, "architecture.md must not include month names"
    assert MARKETING_RE.search(arch_text) is None, "architecture.md must not use marketing adjectives"
    assert "@" not in arch_text
    assert "/home/" not in arch_text

    for required in (
        "RuntimeCore",
        "propose",
        "validate",
        "request",
        "resolve",
        "apply",
        "plan_preview",
        "cli.py",
        "rt_server.py",
        "mcp_server.py",
        "agenthost",
        "rt_ui.py",
        "guard",
        "style",
        "PIPELINE.md",
        "APPROVALS.md",
        "fill_report.py",
        "build_report.py",
        "story_edit.py",
        "tidy_hwpx.py",
    ):
        assert required in arch_text, f"architecture.md missing {required!r}"

    proto_head = "\n".join(proto_text.splitlines()[:15])
    assert "No runtime code exists yet" not in proto_text
    assert "nothing in this\ndocument is implemented" not in proto_text
    assert "nothing in this document is implemented" not in proto_text
    assert "RuntimeCore" in proto_head
    assert "historical" in proto_head.lower()
    assert "## 9. Implementation status (historical" in proto_text

    support_proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "support_matrix.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )
    assert support_proc.returncode == 0, support_proc.stderr
    support_payload = json.loads(support_proc.stdout)
    assert support_payload["ok"] is True
