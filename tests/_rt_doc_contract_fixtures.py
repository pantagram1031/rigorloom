# -*- coding: utf-8 -*-
"""Neutral document specs for tests/test_rt_doc_contract.py, and the committed
.hwpx fixtures the real ``rt_doc`` is tested on.

A spec is ``{family, headings, paragraphs, table, places}``. ``layout(spec)``
turns it into one fixed block order, used for both implementations:

    heading 0, its share of the paragraphs,
    heading 1, its share of the paragraphs, the table,
    ---page break---
    heading 2 .. n-1 with their shares, then every fill seat.

The fake gets that layout as an ``.fdoc`` file written per test. The real
``rt_doc`` gets ``tests/fixtures/rt_doc_contract/<family>.hwpx``, which is the
fake's HWPX export of the same layout (``_fake_rt_doc.hwpx_bytes``): headings are
paragraphs on styles "개요 1..3" (paraPr heading type OUTLINE), fill seats are
CLICK_HERE fields named by the seat id with the label as the field's
Direction, the table is a plain 1x1-cell grid with row 0 marked header, and the
page break is ``pageBreak="1"`` on the first paragraph of page 2.
``test_committed_hwpx_fixtures_match_their_specs`` keeps the committed bytes
equal to that export, member by member.

Regenerate after changing a spec:  python tests/_rt_doc_contract_fixtures.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _fake_rt_doc as fake  # noqa: E402

FIXTURE_DIR = HERE / "fixtures" / "rt_doc_contract"

#: ``basic``: three headings, four paragraphs, one 3x2 table, two fill seats,
#: two pages. Chosen words: "보존 포맷" occurs exactly once (in a paragraph),
#: "점검" occurs in two paragraphs and nowhere else, "인건비" is a table cell.
BASIC: dict = {
    "family": "basic",
    "headings": [[1, "사업 개요"], [2, "추진 배경"], [2, "세부 계획"]],
    "paragraphs": [
        "본 사업은 2026년 3월에 시작한다.",
        "점검 대상은 보존 포맷 메타데이터이다.",
        "점검 기간은 11월 18일부터 11월 27일까지이다.",
        "결과는 전자문서 시스템으로 회신한다.",
    ],
    "table": [["항목", "금액(천원)"], ["인건비", "7,000"], ["재료비", "5,000"]],
    "places": [{"id": "applicant", "label": "신청인"}, {"id": "written_on", "label": "작성일"}],
}

SPECS: dict[str, dict] = {"basic": BASIC}

#: Words with a known number of occurrences in BASIC's body text.
UNIQUE_WORD = "보존 포맷"
REPEATED_WORD = "점검"
CELL_WORD = "인건비"


def _shares(paragraphs: list[str], n: int) -> list[list[str]]:
    n = max(n, 1)
    size, extra = divmod(len(paragraphs), n)
    out, k = [], 0
    for i in range(n):
        take = size + (1 if i < extra else 0)
        out.append(paragraphs[k:k + take])
        k += take
    return out


def layout(spec: dict) -> list[fake.Block]:
    headings = spec.get("headings") or []
    shares = _shares(list(spec.get("paragraphs") or []), len(headings))
    blocks: list[fake.Block] = []
    table_after = min(1, len(headings) - 1) if headings else -1
    for i, (level, text) in enumerate(headings):
        if i == 2:
            blocks.append(fake.Block("break"))
        blocks.append(fake.Block("heading", text, level=level))
        blocks += [fake.Block("para", p) for p in shares[i]]
        if i == table_after and spec.get("table"):
            blocks.append(fake.Block("table", rows=[list(r) for r in spec["table"]]))
    if not headings:
        blocks += [fake.Block("para", p) for p in spec.get("paragraphs") or []]
        if spec.get("table"):
            blocks.append(fake.Block("table", rows=[list(r) for r in spec["table"]]))
    for place in spec.get("places") or []:
        blocks.append(fake.Block("place", "", place_id=place["id"], label=place["label"],
                                 place_kind=place.get("kind", "text")))
    return blocks


def fdoc_text(spec: dict) -> str:
    return fake.serialize(layout(spec))


def write_fdoc(path: Path, spec: dict) -> Path:
    path.write_bytes(fdoc_text(spec).encode("utf-8"))
    return path


def hwpx_bytes(spec: dict) -> bytes:
    return fake.hwpx_bytes(fdoc_text(spec))


def committed_fixture(family: str) -> Path:
    return FIXTURE_DIR / f"{family}.hwpx"


def members(data_or_path) -> dict[str, bytes]:
    """{name: uncompressed bytes}: compare packages without trusting deflate output."""
    import io
    src = io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else data_or_path
    with zipfile.ZipFile(src) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for family, spec in SPECS.items():
        committed_fixture(family).write_bytes(hwpx_bytes(spec))
        print(committed_fixture(family).relative_to(HERE.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
