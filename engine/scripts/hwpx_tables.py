#!/usr/bin/env python3
"""hwpx_tables.py — section XML의 표(hp:tbl)/셀(hp:tc) 스팬 스캐너 (중첩 안전).

`form_inspect`(table_map 보고)와 `preedit fill-cells`(cellAddr로 셀 채우기)가
**같은 표 색인·같은 셀 주소**를 봐야 하므로 스캐너를 한 곳에 둔다. 두 도구가
서로 다른 색인을 쓰면 `--table N`은 조용히 엉뚱한 표를 가리키는 함정이 된다.

왜 정규식 한 방이 아니라 태그 스택인가 — 표는 중첩된다. 셀(hp:tc) 안 문단이
다시 표를 담는 구조가 corpus 12개 양식 중 6개에서 실측된다(중첩 깊이 2).
비탐욕 `<hp:tbl>(.*?)</hp:tbl>` 는 바깥 표의 여는 태그와 **안쪽** 표의 닫는
태그를 짝지어, (a) 바깥 표의 몸통에 안쪽 표의 셀을 섞어 넣고 (b) 안쪽 표
뒤에 오는 바깥 표의 셀을 통째로 잃는다. 스택 스캔은 각 tbl의 진짜 짝을 찾고,
셀은 '가장 가까운 조상 tbl'에만 귀속시킨다.

색인 규약: **여는 태그의 문서 순서**. 섹션 파일은 이름순, 한 섹션 안에서는
`<hp:tbl` 이 등장하는 순서. 바깥 표가 안쪽 표보다 항상 먼저(작은 index).

주소 규약: `<hp:cellAddr colAddr=".." rowAddr=".."/>` 를 그대로 (row, col)로
읽는다 — 병합 셀의 주소는 그 셀의 좌상단 격자 좌표이고, rowSpan/colSpan이
덮는 나머지 좌표에는 tc가 존재하지 않는다(그래서 주소는 연속이 아니다).
"""
import re

NS = r'[A-Za-z0-9]+'
Q = r'["\']'
_TAG_RE = re.compile(r'<(/?)(' + NS + r'):([A-Za-z0-9]+)\b[^>]*?(/?)>', re.S)
_CELLADDR_RE = re.compile(r'<' + NS + r':cellAddr\b([^>]*?)/?>')
_CELLSPAN_RE = re.compile(r'<' + NS + r':cellSpan\b([^>]*?)/?>')


def attr(tag_attrs, name):
    """태그 속성 문자열에서 name="..." / name='...' 값 추출(속성 순서 무관)."""
    m = re.search(r'\b' + re.escape(name) + r'\s*=\s*(' + Q + r')(.*?)\1',
                  tag_attrs, re.S)
    return m.group(2) if m else None


def _int_attr(tag_attrs, name):
    v = attr(tag_attrs, name)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def scan_tables(xml):
    """section XML 하나에서 표 목록을 문서 순서로.

    반환: [{"start", "end", "attrs", "depth", "cells": [cell, ...]}, ...]
      - start/end: `<hp:tbl` … `</hp:tbl>` 전체 스팬(슬라이스 가능)
      - attrs: 여는 태그의 속성 문자열(rowCnt/colCnt 등은 attr()로)
      - depth: 0 = 최상위 표, 1 = 셀 안에 중첩된 표 …
      - cells: 이 표에 **직접** 속한 tc만(중첩 표의 셀은 그 표에 귀속)
    cell: {"start","end","attrs","body_start","body_end","addr":(row,col)|None,
           "span":(rowSpan,colSpan)}
      body_start/body_end 는 `<hp:tc ...>` 와 `</hp:tc>` 사이(자식 내용) 스팬.
    """
    tables = []
    stack = []          # [(local, start_pos, body_start)]
    tbl_stack = []      # 열려 있는 표들의 tables[] 인덱스
    tc_stack = []       # 열려 있는 tc의 (owner_table_index, start, body_start)
    pos, length = 0, len(xml)
    while pos < length:
        m = _TAG_RE.search(xml, pos)
        if not m:
            break
        is_close, _prefix, local, selfclose = m.groups()
        pos = m.end()
        if selfclose:
            continue
        if not is_close:
            stack.append((local, m.start(), m.end()))
            if local == "tbl":
                tables.append({
                    "start": m.start(),
                    "end": None,
                    "attrs": xml[m.start():m.end()],
                    "depth": len(tbl_stack),
                    "cells": [],
                })
                tbl_stack.append(len(tables) - 1)
            elif local == "tc":
                # 가장 가까운 조상 tbl에 귀속. 조상이 없으면 손상 XML —
                # 조용히 버리지 않고 무시(스캐너는 진단 도구가 아니다).
                owner = tbl_stack[-1] if tbl_stack else None
                tc_stack.append((owner, m.start(), m.end()))
            continue
        # 닫는 태그
        if not stack:
            continue
        opened_local, open_start, body_start = stack.pop()
        if opened_local != local:
            # well-formed 가정 위반(호출자가 검증한다) — 스택만 되돌린다.
            continue
        if local == "tbl" and tbl_stack:
            idx = tbl_stack.pop()
            tables[idx]["end"] = m.end()
        elif local == "tc" and tc_stack:
            owner, tc_start, tc_body_start = tc_stack.pop()
            if owner is None:
                continue
            body = xml[tc_body_start:m.start()]
            # cellAddr/cellSpan 은 tc의 **직속** 자식이지만, 중첩 표의 셀도
            # body 안에 있으므로 첫 매치를 그대로 쓰면 안 된다. 중첩 표
            # 스팬을 잘라낸 뒤 찾는다(중첩 표는 이미 tables에 등록돼 있다).
            own = _strip_nested_tables(body, tc_body_start, tables, owner)
            am = _CELLADDR_RE.search(own)
            addr = None
            if am:
                r = _int_attr(am.group(1), "rowAddr")
                c = _int_attr(am.group(1), "colAddr")
                if r is not None and c is not None:
                    addr = (r, c)
            sm = _CELLSPAN_RE.search(own)
            span = ((_int_attr(sm.group(1), "rowSpan") or 1,
                     _int_attr(sm.group(1), "colSpan") or 1) if sm else (1, 1))
            tables[owner]["cells"].append({
                "start": tc_start,
                "end": m.end(),
                "attrs": xml[tc_start:tc_body_start],
                "body_start": tc_body_start,
                "body_end": m.start(),
                "addr": addr,
                "span": span,
            })
    for t in tables:
        if t["end"] is None:            # 닫히지 않은 표 — 손상 입력
            t["end"] = length
        t["cells"].sort(key=lambda c: c["start"])
    return tables


def _strip_nested_tables(body, body_offset, tables, owner_idx):
    """tc 몸통에서 중첩 표 스팬을 지운 문자열 — cellAddr 오귀속 방지.

    중첩 표의 첫 셀에도 cellAddr이 있으므로, 그걸 바깥 셀의 주소로 읽으면
    주소가 통째로 뒤바뀐다(rowspan 라벨 열이 있는 정부 양식에서 치명적).
    """
    lo, hi = body_offset, body_offset + len(body)
    spans = [(t["start"], t["end"]) for i, t in enumerate(tables)
             if i != owner_idx and t["end"] is not None
             and t["start"] >= lo and t["end"] <= hi]
    if not spans:
        return body
    out, cur = [], lo
    for s, e in sorted(spans):
        if s < cur:
            continue
        out.append(body[cur - lo:s - lo])
        cur = e
    out.append(body[cur - lo:])
    return "".join(out)


def find_cell(table, row, col):
    """표 dict에서 cellAddr (row, col)인 셀 하나. 없으면 None."""
    for cell in table["cells"]:
        if cell["addr"] == (row, col):
            return cell
    return None
