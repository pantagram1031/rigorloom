"""Verify parity between rt_doc.queue_addresses and the HWPX inspect/queue path over the corpus forms."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import zipfile

import pytest

from _runtime_client import runtime_scripts_on_path

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests" / "corpus" / "forms"
BASIC_FIXTURE = REPO / "tests" / "fixtures" / "rt_doc_contract" / "basic.hwpx"
ENGINE_SCRIPTS = REPO / "engine" / "scripts"

runtime_scripts_on_path()
if str(ENGINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ENGINE_SCRIPTS))

import form_inspect  # noqa: E402
import preedit  # noqa: E402
import rt_doc  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("RIGORLOOM_HWP_ENGINE"),
    reason="RIGORLOOM_HWP_ENGINE is unset",
)


def _corpus_documents():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("documents") or []
    hwpx_slugs = {
        entry["slug"]
        for entry in entries
        if entry.get("format") == "hwpx" or str(entry.get("path", "")).endswith(".hwpx")
    }
    cases = []
    seen_paths: set[Path] = set()
    for entry in entries:
        slug = entry["slug"]
        rel_path = entry["path"]
        fmt = entry.get("format") or Path(rel_path).suffix.lstrip(".").lower()
        if fmt == "hwp":
            if slug in hwpx_slugs:
                continue
            cases.append(
                pytest.param(
                    slug,
                    (CORPUS / rel_path).resolve(),
                    entry["sha256"],
                    id=slug,
                    marks=pytest.mark.skip(reason=f"{rel_path} is .hwp only with no paired .hwpx in manifest.json"),
                )
            )
            continue
        if fmt != "hwpx":
            continue
        resolved = (CORPUS / rel_path).resolve()
        seen_paths.add(resolved)
        cases.append(pytest.param(slug, resolved, entry["sha256"], id=slug))

    basic_resolved = BASIC_FIXTURE.resolve()
    if basic_resolved not in seen_paths:
        cases.append(pytest.param("basic", basic_resolved, None, id="basic"))
    return cases


def _queue_paragraphs_and_tables(source: Path):
    """Collect top-level paragraph and table addresses and content via form_inspect / preedit."""
    _infos, contents = preedit._read_zip(source)
    section_names = preedit._section_names(contents)

    top_at_paras: list[int] = []
    at_para = 0
    for sname in section_names:
        xml = contents[sname].decode("utf-8")
        top_spans = {(start, end) for start, end, _ in preedit._find_paragraphs(xml)}
        for start, end, _p_xml in preedit._iter_document_paragraphs(xml):
            if (start, end) in top_spans:
                top_at_paras.append(at_para)
            at_para += 1

    profile, _ = form_inspect.analyze(
        source,
        full_text=[("para", idx) for idx in top_at_paras],
    )
    queue_paras = {
        f"p{entry['at_para']}": entry["text"]
        for entry in profile.get("full_text") or []
        if "at_para" in entry
    }

    cell_requests = []
    first_cells: dict[str, tuple[int, int]] = {}
    queue_tables: dict[str, dict] = {}
    for table in profile.get("table_map") or []:
        t_idx = int(table["index"])
        q_addr = f"t{t_idx}"
        queue_tables[q_addr] = {
            "rows": table["rowCnt"],
            "cols": table["colCnt"],
            "first_cell_text": "",
        }
        non_empty = next(
            (cell for cell in table.get("cells") or [] if (cell.get("text_preview") or "").strip()),
            None,
        )
        if non_empty is not None and non_empty.get("addr"):
            row = int(non_empty["addr"]["row"])
            col = int(non_empty["addr"]["col"])
            first_cells[q_addr] = (row, col)
            cell_requests.append((t_idx, row, col))

    if cell_requests:
        with zipfile.ZipFile(source) as zf:
            cell_entries = form_inspect._full_text(section_names, zf, cell_requests)
        for entry in cell_entries:
            q_addr = f"t{entry['table']}"
            coord = (int(entry["addr"]["row"]), int(entry["addr"]["col"]))
            if first_cells.get(q_addr) == coord:
                queue_tables[q_addr]["first_cell_text"] = entry["text"]

    return queue_paras, queue_tables


def _core_table_first_cell_text(source: Path, core_addr: str, cells_grid: list[list[str]]) -> str:
    for r_idx, row in enumerate(cells_grid):
        for c_idx, cell_text in enumerate(row):
            if cell_text.strip():
                cell_read = rt_doc.read(source, f"{core_addr}/r{r_idx}/c{c_idx}")
                assert cell_read["ok"], f"{source.name}: read({core_addr}/r{r_idx}/c{c_idx}) failed: {cell_read}"
                return "".join(block["text"] for block in cell_read["blocks"])
    return ""


@pytest.mark.parametrize("doc_id, source, expected_sha256", _corpus_documents())
def test_queue_address_parity(doc_id: str, source: Path, expected_sha256: str | None):
    if expected_sha256 is not None:
        actual_sha256 = sha256(source.read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256, (
            f"{doc_id} ({source.name}): sha256 {actual_sha256} != manifest {expected_sha256}"
        )

    mapped_res = rt_doc.queue_addresses(source)
    assert mapped_res["ok"], f"{doc_id} ({source.name}): queue_addresses failed: {mapped_res}"
    addresses: dict[str, str] = mapped_res["addresses"]

    queue_paras, queue_tables = _queue_paragraphs_and_tables(source)

    seen_values: dict[str, str] = {}
    for core_addr, queue_addr in addresses.items():
        assert queue_addr not in seen_values, (
            f"{doc_id}: mapping is not one-to-one; doc-core {seen_values[queue_addr]} and {core_addr} "
            f"both map to queue {queue_addr} (texts: '' vs '')"
        )
        seen_values[queue_addr] = core_addr

    core_para_map = {k: v for k, v in addresses.items() if k.startswith("p")}
    core_table_map = {k: v for k, v in addresses.items() if k.startswith("t")}

    for q_addr, q_text in queue_paras.items():
        count = sum(1 for v in core_para_map.values() if v == q_addr)
        assert count == 1, (
            f"{doc_id}: doc-core <unmapped> -> queue {q_addr} appears {count} times in mapped paragraphs "
            f"(core text: '' vs queue text: {q_text.strip()[:40]!r})"
        )

    for core_addr, q_addr in core_para_map.items():
        read_res = rt_doc.read(source, core_addr)
        assert read_res["ok"] and read_res["blocks"], (
            f"{doc_id}: doc-core {core_addr} -> queue {q_addr} read failed: {read_res}"
        )
        core_text = read_res["blocks"][0]["text"].strip()
        assert q_addr in queue_paras, (
            f"{doc_id}: doc-core {core_addr} -> queue {q_addr} not found in queue paragraphs "
            f"(core text: {core_text[:40]!r} vs queue text: '<missing>')"
        )
        queue_text = queue_paras[q_addr].strip()
        assert core_text == queue_text, (
            f"{doc_id}: paragraph text mismatch at doc-core {core_addr} -> queue {q_addr}: "
            f"core={core_text[:40]!r} vs queue={queue_text[:40]!r}"
        )

    for q_addr, q_table in queue_tables.items():
        count = sum(1 for v in core_table_map.values() if v == q_addr)
        assert count == 1, (
            f"{doc_id}: doc-core <unmapped> -> queue {q_addr} appears {count} times in mapped tables "
            f"(core text: '<unmapped>' vs queue text: {q_table['first_cell_text'].strip()[:40]!r})"
        )

    for core_addr, q_addr in core_table_map.items():
        read_res = rt_doc.read(source, core_addr)
        assert read_res["ok"] and read_res["blocks"], (
            f"{doc_id}: doc-core {core_addr} -> queue {q_addr} read failed: {read_res}"
        )
        block = read_res["blocks"][0]
        core_first = _core_table_first_cell_text(source, core_addr, block["cells"]).strip()
        assert q_addr in queue_tables, (
            f"{doc_id}: doc-core {core_addr} -> queue {q_addr} not found in queue tables "
            f"(core text: {core_first[:40]!r} vs queue text: '<missing>')"
        )
        q_table = queue_tables[q_addr]
        queue_first = q_table["first_cell_text"].strip()
        assert (block["rows"], block["cols"]) == (q_table["rows"], q_table["cols"]), (
            f"{doc_id}: table shape mismatch at doc-core {core_addr} -> queue {q_addr}: "
            f"core=({block['rows']}, {block['cols']}) ({core_first[:40]!r}) vs "
            f"queue=({q_table['rows']}, {q_table['cols']}) ({queue_first[:40]!r})"
        )
        assert core_first == queue_first, (
            f"{doc_id}: table first non-empty cell text mismatch at doc-core {core_addr} -> queue {q_addr}: "
            f"core={core_first[:40]!r} vs queue={queue_first[:40]!r}"
        )
