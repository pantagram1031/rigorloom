"""tidy_hwpx.py 회귀 테스트 (T7 대응: COM 기반 blank-paragraph 정리 대체).

실제 픽스처(reports/report-aliasing-sampling/output/out.hwpx) 기반 — 없으면 skip.
COM 불필요, 오프라인. 픽스처는 항상 tmp_path로 복사한 뒤 편집(원본 비파괴).

주의: 라이브 워크스페이스 out.hwpx는 이후 빌드에서 정리될 수 있어(빈 문단이
이미 tidy돼 있음) 앵커 앞 빈 문단 개수에 결정론적으로 의존할 수 없다 — 그래서
빈 문단 개수를 직접 검증해야 하는 테스트는 tmp 복사본에 빈 문단 템플릿을
합성 삽입해(_with_synthetic_blanks) 라이브 파일 상태와 무관하게 만든다.
`python -m pytest tests/ -q`.
"""
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import tidy_hwpx  # noqa: E402

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
FIXTURE = os.path.join(_WS, "reports", "report-aliasing-sampling", "output", "out.hwpx") if _WS else ""
ANCHOR = "Ⅰ. 서 론"

pytestmark = pytest.mark.skipif(
    not os.path.exists(FIXTURE),
    reason="real fixture (report-aliasing-sampling/output/out.hwpx) not present on this machine",
)


def _copy_fixture(tmp_path):
    import shutil
    dst = tmp_path / "fixture.hwpx"
    shutil.copyfile(FIXTURE, dst)
    return dst


def _section_xml(path, name="Contents/section0.xml"):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def _write_section(path, xml_text, name="Contents/section0.xml"):
    with zipfile.ZipFile(path) as zin:
        items = {i.filename: (i, zin.read(i.filename)) for i in zin.infolist()}
    items[name] = (items[name][0], xml_text.encode("utf-8"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items.values():
            zout.writestr(info, data)


def _copy_fixture_with_synthetic_blanks(tmp_path, anchor, n_blanks):
    """FIXTURE를 tmp로 복사한 뒤, anchor 문단 바로 앞의 기존 빈 문단(있다면,
    라이브 파일이 이미 tidy됐을 수 있어 0~n개)을 모두 제거하고 빈 문단
    n_blanks개를 새로 합성 삽입한다 — 빈 문단 템플릿은 anchor 문단 자체를
    복제(같은 paraPrIDRef/styleIDRef, 빈 run)해 만들므로 구조적으로 실제
    빈 문단과 동일하다. 라이브 파일의 현재 tidy 상태와 무관하게 항상 정확히
    n_blanks개의 연속 빈 문단을 확보해 결정론적으로 테스트한다."""
    dst = tmp_path / "fixture.hwpx"
    import shutil
    shutil.copyfile(FIXTURE, dst)
    xml = _section_xml(dst)
    paras = tidy_hwpx._find_paragraphs(xml)
    idx = next(i for i, (_s, _e, p) in enumerate(paras) if anchor in tidy_hwpx._para_text(p))
    anchor_start, _anchor_end, anchor_xml = paras[idx]

    # 기존에 앵커 바로 앞에 있는 연속 빈 문단 구간을 찾아 제거(스팬 계산).
    j = idx - 1
    while j >= 0 and tidy_hwpx._is_empty_para(paras[j][2]):
        j -= 1
    strip_start = paras[j + 1][0] if j + 1 < idx else anchor_start

    import re
    open_m = re.match(r'<' + tidy_hwpx.NS + r':p\b([^>]*)>', anchor_xml)
    prefix = open_m.group(0).split(":")[0][1:]
    pr_attrs = open_m.group(1)
    blank_template = (f'<{prefix}:p{pr_attrs}>'
                      f'<{prefix}:run charPrIDRef="0"/></{prefix}:p>')
    blanks = blank_template * n_blanks
    new_xml = xml[:strip_start] + blanks + xml[anchor_start:]
    _write_section(dst, new_xml)
    return dst


def test_removes_blanks_before_anchor_keeping_one(tmp_path):
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 18)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)
    assert result["ok"] is True
    assert result["removed"][ANCHOR] == 17  # 18 consecutive blanks -> keep 1 -> remove 17

    xml = _section_xml(out)
    paras = tidy_hwpx._find_paragraphs(xml)
    idx = next(i for i, (_s, _e, p) in enumerate(paras) if ANCHOR in tidy_hwpx._para_text(p))
    j = idx - 1
    empties = 0
    while j >= 0 and tidy_hwpx._is_empty_para(paras[j][2]):
        empties += 1
        j -= 1
    assert empties == 1


# ---------------------------------------------------------------------------
# Rule 1: keep_map — per-anchor keep_n override (form-native blanks_before)
# ---------------------------------------------------------------------------

def test_keep_map_overrides_default_keep_for_matched_anchor(tmp_path):
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 18)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out,
                                  keep_map={ANCHOR: 5})
    assert result["ok"] is True
    assert result["removed"][ANCHOR] == 13  # 18 blanks -> keep 5 -> remove 13

    xml = _section_xml(out)
    paras = tidy_hwpx._find_paragraphs(xml)
    idx = next(i for i, (_s, _e, p) in enumerate(paras) if ANCHOR in tidy_hwpx._para_text(p))
    j = idx - 1
    empties = 0
    while j >= 0 and tidy_hwpx._is_empty_para(paras[j][2]):
        empties += 1
        j -= 1
    assert empties == 5


def test_keep_map_missing_anchor_falls_back_to_default_keep(tmp_path):
    """keep_map에 없는 anchor는 기존 --keep 기본값을 그대로 쓴다(하위호환)."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 18)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out,
                                  keep_map={"다른앵커": 9})
    assert result["ok"] is True
    assert result["removed"][ANCHOR] == 17  # keep_map에 없음 -> keep=1 그대로


def test_keep_map_none_behaves_like_before(tmp_path):
    """keep_map=None(기본값)이면 전체 keep 값 하나만 적용(구동작 그대로)."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 18)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)
    assert result["ok"] is True
    assert result["removed"][ANCHOR] == 17


def test_keep_map_never_trims_below_form_baseline_when_current_blanks_fewer(tmp_path):
    """Rule 1 명세: 현재 빈 문단 수 <= keep_n이면 아무것도 하지 않는다(양식
    baseline 아래로는 절대 안 지운다). 3개만 있는데 keep_n=10이면 0개 삭제."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 3)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out,
                                  keep_map={ANCHOR: 10})
    assert result["ok"] is True
    assert result["removed"][ANCHOR] == 0

    xml = _section_xml(out)
    paras = tidy_hwpx._find_paragraphs(xml)
    idx = next(i for i, (_s, _e, p) in enumerate(paras) if ANCHOR in tidy_hwpx._para_text(p))
    j = idx - 1
    empties = 0
    while j >= 0 and tidy_hwpx._is_empty_para(paras[j][2]):
        empties += 1
        j -= 1
    assert empties == 3  # 그대로 보존


def test_keep_map_cli_json_arg(tmp_path):
    """CLI --keep-map JSON이 API keep_map과 동일하게 동작해야 한다."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 18)
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    keep_map_json = json.dumps({ANCHOR: 4}, ensure_ascii=False)
    proc = subprocess.run(
        [sys.executable, script, str(src), "--before", ANCHOR,
         "--keep-map", keep_map_json, "--out", str(out)],
        capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["removed"][ANCHOR] == 14  # 18 -> keep 4 -> remove 14


def test_keep_map_cli_bad_json_dies(tmp_path):
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 3)
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    proc = subprocess.run(
        [sys.executable, script, str(src), "--before", ANCHOR,
         "--keep-map", "{not valid json", "--out", str(out)],
        capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 2
    assert not out.exists()


def test_nonempty_paragraphs_untouched(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)

    xml_before = _section_xml(src)
    xml_after = _section_xml(out)
    texts_before = [tidy_hwpx._para_text(p) for _s, _e, p in tidy_hwpx._find_paragraphs(xml_before)
                    if tidy_hwpx._para_text(p).strip()]
    texts_after = [tidy_hwpx._para_text(p) for _s, _e, p in tidy_hwpx._find_paragraphs(xml_after)
                   if tidy_hwpx._para_text(p).strip()]
    assert texts_before == texts_after


def test_ambiguous_anchor_refused(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    with pytest.raises(SystemExit) as ei:
        tidy_hwpx.tidy_hwpx(src, ["통과"], [], keep=1, out_path=out)  # appears 5x in table
    assert ei.value.code == 1
    assert not out.exists()


def test_missing_anchor_refused(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    with pytest.raises(SystemExit) as ei:
        tidy_hwpx.tidy_hwpx(src, ["NOT_A_REAL_ANCHOR_XYZ"], [], keep=1, out_path=out)
    assert ei.value.code == 1
    assert not out.exists()


def test_table_cell_internals_untouched(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)

    def nested_para_texts(xml):
        stack, pos, texts = [], 0, []
        while pos < len(xml):
            m = tidy_hwpx.TAG_RE.search(xml, pos)
            if not m:
                break
            is_close, prefix, local, selfclose = m.groups()
            if selfclose:
                pos = m.end()
                continue
            if not is_close:
                stack.append((prefix, local, m.start()))
            elif stack:
                _op, ol, ostart = stack.pop()
                if ol == "p" and any(s[1] == "p" for s in stack):
                    texts.append(tidy_hwpx._para_text(xml[ostart:m.end()]))
            pos = m.end()
        return texts

    before = nested_para_texts(_section_xml(src))
    after = nested_para_texts(_section_xml(out))
    assert before == after


def test_paragraph_count_decreases_by_exactly_removed(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)

    n_before = len(tidy_hwpx._find_paragraphs(_section_xml(src)))
    n_after = len(tidy_hwpx._find_paragraphs(_section_xml(out)))
    assert n_before - n_after == sum(result["removed"].values())


def test_only_section_xml_differs_in_zip(tmp_path):
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 3)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.tidy_hwpx(src, [ANCHOR], [], keep=1, out_path=out)

    with zipfile.ZipFile(src) as z1, zipfile.ZipFile(out) as z2:
        names1, names2 = set(z1.namelist()), set(z2.namelist())
        assert names1 == names2
        diffs = [n for n in names1 if z1.read(n) != z2.read(n)]
        assert diffs == ["Contents/section0.xml"]


# ---------------------------------------------------------------------------
# --keep-with-next (table caption orphan fix)
# ---------------------------------------------------------------------------

def _header_defs(path):
    with zipfile.ZipFile(path) as z:
        header = z.read("Contents/header.xml").decode("utf-8")
    return tidy_hwpx._parapr_defs_by_id(header)


def _copy_fixture_with_keep_with_next_reset(tmp_path, prefixes):
    """FIXTURE를 tmp로 복사한 뒤, prefixes로 시작하는 문단들의 paraPrIDRef를
    강제로 id="0"(keepWithNext="0" 기본 def)으로 되돌린 사본을 만든다.

    라이브 FIXTURE는 fill_report 재빌드로 --keep-with-next가 이미 적용돼
    있을 수 있어(캡션이 이미 keepWithNext=1) 패치 카운트에 결정론적으로
    의존하는 테스트가 fixture 드리프트에 흔들린다. test_para_formats.py의
    '합성 손상 사본'과 동일한 전략으로 항상 미패치 상태에서 시작한다."""
    import shutil
    dst = tmp_path / "fixture.hwpx"
    shutil.copyfile(FIXTURE, dst)
    xml = _section_xml(dst)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    new_xml = xml
    for (p_start, p_end, p_xml, open_end, attrs) in sorted(paras, key=lambda e: e[0], reverse=True):
        text = tidy_hwpx._para_text(p_xml).strip()
        if not any(text.startswith(p) for p in prefixes):
            continue
        open_tag_len = open_end - p_start
        old_open_tag = p_xml[:open_tag_len]
        new_open_tag = tidy_hwpx.re.sub(
            r'(\bparaPrIDRef\s*=\s*")\d+(")', r'\g<1>0\2', old_open_tag, count=1)
        new_p_xml = new_open_tag + p_xml[open_tag_len:]
        new_xml = new_xml[:p_start] + new_p_xml + new_xml[p_end:]
    _write_section(dst, new_xml)
    return dst


def test_keep_with_next_patches_all_matching_prefixes(tmp_path):
    src = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1.", "표 2."])
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.apply_keep_with_next(src, ["표 1.", "표 2."], out_path=out)
    assert result["ok"] is True
    assert len(result["patched"]) == 2
    prefixes_hit = {p["prefix"] for p in result["patched"]}
    assert prefixes_hit == {"표 1.", "표 2."}

    defs = _header_defs(out)
    for entry in result["patched"]:
        new_id = entry["paraPrIDRef"]["to"]
        assert new_id in defs
        kwn_m = tidy_hwpx.re.search(
            r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", defs[new_id][2])
        assert tidy_hwpx._attr_value(kwn_m.group(1), "keepWithNext") == "1"


def test_keep_with_next_only_matched_paragraphs_repointed(tmp_path):
    src = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1."])
    out = tmp_path / "out.hwpx"
    xml_before = _section_xml(src)
    result = tidy_hwpx.apply_keep_with_next(src, ["표 1."], out_path=out)
    assert result["ok"] is True

    xml_after = _section_xml(out)
    paras_before = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml_before)
    paras_after = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml_after)
    assert len(paras_before) == len(paras_after)

    changed = []
    for (b, a) in zip(paras_before, paras_after):
        b_ref = tidy_hwpx._attr_value(b[4], "paraPrIDRef")
        a_ref = tidy_hwpx._attr_value(a[4], "paraPrIDRef")
        if b_ref != a_ref:
            changed.append(tidy_hwpx._para_text(a[2]).strip())
    assert len(changed) == 1
    assert changed[0].startswith("표 1.")


def test_keep_with_next_shares_clone_for_same_source_parapr(tmp_path):
    src = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1.", "표 2."])
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.apply_keep_with_next(src, ["표 1.", "표 2."], out_path=out)
    assert result["ok"] is True
    ids_to = {p["paraPrIDRef"]["to"] for p in result["patched"]}
    froms = {p["paraPrIDRef"]["from"] for p in result["patched"]}
    if len(froms) == 1:
        # 두 캡션이 원래 같은 paraPr def를 가리켰다면 clone도 재사용돼야 함.
        assert len(ids_to) == 1


def test_keep_with_next_missing_prefix_refused(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    with pytest.raises(SystemExit) as ei:
        tidy_hwpx.apply_keep_with_next(src, ["NOT_A_REAL_CAPTION_PREFIX_XYZ"], out_path=out)
    assert ei.value.code == 1
    assert not out.exists()


def test_keep_with_next_nonmatching_text_untouched(tmp_path):
    src = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1."])
    out = tmp_path / "out.hwpx"
    tidy_hwpx.apply_keep_with_next(src, ["표 1."], out_path=out)

    texts_before = [tidy_hwpx._para_text(p) for _s, _e, p in
                    tidy_hwpx._find_paragraphs(_section_xml(src))
                    if tidy_hwpx._para_text(p).strip()]
    texts_after = [tidy_hwpx._para_text(p) for _s, _e, p in
                   tidy_hwpx._find_paragraphs(_section_xml(out))
                   if tidy_hwpx._para_text(p).strip()]
    assert texts_before == texts_after  # 텍스트 내용은 절대 안 바뀜


def test_keep_with_next_idempotent_on_already_patched(tmp_path):
    src = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1."])
    out1 = tmp_path / "out1.hwpx"
    result1 = tidy_hwpx.apply_keep_with_next(src, ["표 1."], out_path=out1)
    assert len(result1["patched"]) == 1  # 리셋된 사본이라 첫 적용은 반드시 patch함
    out2 = tmp_path / "out2.hwpx"
    # 이미 keepWithNext=1인 문단을 다시 매치하면 patched가 비어야 함(anomaly 아님).
    result = tidy_hwpx.apply_keep_with_next(out1, ["표 1."], out_path=out2)
    assert result["ok"] is True
    assert result["patched"] == []


def _reset_keep_with_next_in_place(path, prefixes):
    """path의 section0.xml에서 prefixes 매치 문단의 paraPrIDRef를 id="0"으로
    되돌려 파일을 그 자리에서 덮어쓴다(별도 사본 생성 없이 합성 준비물 위에
    바로 적용하기 위한 헬퍼 — _copy_fixture_with_keep_with_next_reset과 동일
    로직, 대상 경로만 다름)."""
    xml = _section_xml(path)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    new_xml = xml
    for (p_start, p_end, p_xml, open_end, attrs) in sorted(paras, key=lambda e: e[0], reverse=True):
        text = tidy_hwpx._para_text(p_xml).strip()
        if not any(text.startswith(p) for p in prefixes):
            continue
        open_tag_len = open_end - p_start
        old_open_tag = p_xml[:open_tag_len]
        new_open_tag = tidy_hwpx.re.sub(
            r'(\bparaPrIDRef\s*=\s*")\d+(")', r'\g<1>0\2', old_open_tag, count=1)
        new_p_xml = new_open_tag + p_xml[open_tag_len:]
        new_xml = new_xml[:p_start] + new_p_xml + new_xml[p_end:]
    _write_section(path, new_xml)


def test_keep_with_next_cli_combines_with_before_after(tmp_path):
    """CLI 배선: --before/--after tidy와 --keep-with-next를 같은 호출에 섞으면
    둘 다 적용되고 결과 JSON에 removed+patched 키가 모두 있어야 함."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 3)
    # 합성 빈 문단 삽입은 표 캡션 paraPrIDRef를 안 건드리므로, 라이브 fixture가
    # 이미 keepWithNext=1로 재빌드돼 있으면 patched가 0이 될 수 있다 — 리셋.
    _reset_keep_with_next_in_place(src, ["표 1."])
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    proc = subprocess.run(
        [sys.executable, script, str(src), "--before", ANCHOR,
         "--keep-with-next", "표 1.", "--out", str(out)],
        capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert "removed" in payload
    assert "patched" in payload
    assert len(payload["patched"]) == 1


# ---------------------------------------------------------------------------
# --typeset-defaults (widowOrphan everywhere + keepWithNext on headings/captions)
# ---------------------------------------------------------------------------

TYPESET_ANCHORS = ["Ⅰ. 서 론"]
TYPESET_CAPTION_PREFIXES = ["표 ", "[그림"]


def _breaksetting_attrs(defs, pid):
    m = tidy_hwpx.re.search(
        r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", defs[pid][2])
    assert m is not None
    return {
        "widowOrphan": tidy_hwpx._attr_value(m.group(1), "widowOrphan"),
        "keepWithNext": tidy_hwpx._attr_value(m.group(1), "keepWithNext"),
    }


def test_typeset_defaults_sets_widow_orphan_on_all_top_level_paragraphs(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.apply_typeset_defaults(
        src, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES, out_path=out)
    assert result["ok"] is True
    assert len(result["patched"]) > 0
    assert all(r["widow_orphan"] is True for r in result["patched"])

    defs = _header_defs(out)
    xml = _section_xml(out)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    for (_s, _e, _px, _oe, attrs) in paras:
        pid = tidy_hwpx._attr_value(attrs, "paraPrIDRef")
        assert pid in defs
        assert _breaksetting_attrs(defs, pid)["widowOrphan"] == "1"


def test_typeset_defaults_heading_and_caption_get_keep_with_next_plain_body_does_not(tmp_path):
    """Rule 2: 캡션이 객체 '아래'로 이동한 뒤에는 keepWithNext가 캡션 문단이
    아니라 그 앞의 객체(그림/표) 문단에 걸려야 한다. 이 fixture의 그림들은
    이미 신규 레이아웃(객체 -> 캡션)이라 그림 객체 문단으로 검증한다 —
    표 1./표 2.는 이 라이브 fixture가 구형 레이아웃(캡션 -> 표)으로 만들어진
    잔재라 객체 뒤에 캡션이 오지 않으므로 여기선 검증 대상에서 제외한다."""
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.apply_typeset_defaults(
        src, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES, out_path=out)

    defs = _header_defs(out)
    xml = _section_xml(out)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)

    def kwn_for_text_starting_with(prefix):
        for (_s, _e, px, _oe, attrs) in paras:
            text = tidy_hwpx._para_text(px).strip()
            if text.startswith(prefix):
                pid = tidy_hwpx._attr_value(attrs, "paraPrIDRef")
                return _breaksetting_attrs(defs, pid)["keepWithNext"], text
        return None, None

    kwn, text = kwn_for_text_starting_with("Ⅰ. 서 론")
    assert text is not None
    assert kwn == "1"

    # 캡션 문단 자신은 더 이상 keepWithNext를 받지 않는다(Rule 2).
    kwn, text = kwn_for_text_starting_with("표 1.")
    assert text is not None
    assert kwn != "1"

    # 그림(캡션 바로 앞) 객체 문단이 대신 keepWithNext=1을 받는다.
    for (_s, _e, px, _oe, attrs) in paras:
        text = tidy_hwpx._para_text(px).strip()
        if text.startswith("[그림 1]"):
            # 캡션 문단 자신은 여전히 대상이 아니어야 함.
            pid = tidy_hwpx._attr_value(attrs, "paraPrIDRef")
            assert _breaksetting_attrs(defs, pid)["keepWithNext"] != "1"
            break
    else:
        pytest.fail("[그림 1] caption not found in fixture")

    object_before_fig1 = None
    for i, (_s, _e, px, _oe, attrs) in enumerate(paras):
        text = tidy_hwpx._para_text(px).strip()
        if text.startswith("[그림 1]") and i > 0:
            object_before_fig1 = paras[i - 1]
            break
    assert object_before_fig1 is not None
    _s, _e, obj_px, _oe, obj_attrs = object_before_fig1
    assert tidy_hwpx._contains_object(obj_px)
    obj_pid = tidy_hwpx._attr_value(obj_attrs, "paraPrIDRef")
    assert _breaksetting_attrs(defs, obj_pid)["keepWithNext"] == "1"

    # plain body paragraph (not heading, not caption, not object) — widowOrphan
    # yes, keepWithNext untouched.
    plain_hit = None
    for (_s, _e, px, _oe, attrs) in paras:
        text = tidy_hwpx._para_text(px).strip()
        if text and not text.startswith("표 ") and not text.startswith("[그림") \
                and not any(text == a or text.startswith(a) for a in TYPESET_ANCHORS) \
                and not tidy_hwpx._contains_object(px):
            pid = tidy_hwpx._attr_value(attrs, "paraPrIDRef")
            b = _breaksetting_attrs(defs, pid)
            if b["widowOrphan"] == "1":
                plain_hit = (text, b)
                break
    assert plain_hit is not None
    _text, b = plain_hit
    assert b["widowOrphan"] == "1"
    assert b["keepWithNext"] != "1"


def test_typeset_defaults_table_nested_paragraphs_untouched(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.apply_typeset_defaults(
        src, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES, out_path=out)

    def nested_para_pr_refs(xml):
        """표 셀 등에 중첩된 <hp:p>의 paraPrIDRef 목록(최상위 문단 제외)."""
        stack, pos, refs = [], 0, []
        while pos < len(xml):
            m = tidy_hwpx.TAG_RE.search(xml, pos)
            if not m:
                break
            is_close, prefix, local, selfclose = m.groups()
            if selfclose:
                pos = m.end()
                continue
            if not is_close:
                stack.append((prefix, local, m.start()))
            elif stack:
                _op, ol, ostart = stack.pop()
                if ol == "p" and any(s[1] == "p" for s in stack):
                    p_xml = xml[ostart:m.end()]
                    om = tidy_hwpx.P_OPEN_RE.match(p_xml)
                    refs.append(tidy_hwpx._attr_value(om.group(2), "paraPrIDRef") if om else None)
            pos = m.end()
        return refs

    before = nested_para_pr_refs(_section_xml(src))
    after = nested_para_pr_refs(_section_xml(out))
    assert before == after  # nested-in-table paragraphs keep their original paraPrIDRef


def test_typeset_defaults_idempotent_byte_identical(tmp_path):
    """run twice, compare bytes: 두 번째 실행은 아무것도 바꿀 게 없어(patched
    빈 리스트) out_path를 새로 쓰지 않는다(apply_keep_with_next와 동일 관례) —
    그래서 첫 실행 결과물을 그대로 복사해 두 번째 호출에 넣고, 결과 파일이
    복사본과 byte-identical한지(=아무것도 안 바뀜) 확인한다."""
    import shutil
    src = _copy_fixture(tmp_path)
    out1 = tmp_path / "out1.hwpx"
    tidy_hwpx.apply_typeset_defaults(
        src, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES, out_path=out1)

    out2 = tmp_path / "out2.hwpx"
    shutil.copyfile(out1, out2)
    result2 = tidy_hwpx.apply_typeset_defaults(
        out2, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES, out_path=out2)
    assert result2["ok"] is True
    assert result2["patched"] == []  # second run: nothing left to change

    with zipfile.ZipFile(out1) as z1, zipfile.ZipFile(out2) as z2:
        names1, names2 = set(z1.namelist()), set(z2.namelist())
        assert names1 == names2
        for n in names1:
            assert z1.read(n) == z2.read(n)


def test_typeset_defaults_dry_run_writes_nothing(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    src_bytes_before = src.read_bytes()
    result = tidy_hwpx.apply_typeset_defaults(
        src, TYPESET_ANCHORS, caption_prefixes=TYPESET_CAPTION_PREFIXES,
        out_path=out, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert len(result["patched"]) > 0
    for r in result["patched"]:
        assert "para_idx" in r
        assert "text_head" in r
        assert "widow_orphan" in r
        assert "keep_with_next" in r
    assert not out.exists()
    assert src.read_bytes() == src_bytes_before  # source untouched too


def test_typeset_defaults_caption_prefix_requires_delimiter_not_substring(tmp_path):
    """회귀: "표 " 프리픽스가 "표본을..." 같은 무관한 본문 문단(그냥 "표"로
    시작)을 캡션으로 오탐하면 안 된다 — 프리픽스의 trailing space는 의미
    있는 구분자이므로 매칭 전에 지워지면 안 된다."""
    text = "표본을 다룰 때 널리 알려진 결과로 나이퀴스트 표본화 정리가 있다."
    assert tidy_hwpx._is_heading_or_caption(text, [], ["표 ", "[그림"]) is False
    assert tidy_hwpx._is_heading_or_caption("표 1. 실험 설계", [], ["표 ", "[그림"]) is True


def test_typeset_defaults_cli_run_twice_byte_identical(tmp_path):
    """CLI 레벨 idempotence: 같은 --out 경로에 --typeset-defaults를 두 번
    연속 실행하면(두 번째 실행은 첫 실행의 출력을 입력으로 재사용) 파일이
    byte-identical해야 한다."""
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    common = [sys.executable, script, "--typeset-defaults",
              "--caption-prefixes", "표 ,[그림"]
    proc1 = subprocess.run(common + [str(src), "--out", str(out)],
                            capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc1.returncode == 0, proc1.stderr.decode("utf-8", "replace")
    first_bytes = out.read_bytes()

    proc2 = subprocess.run(common + [str(out), "--out", str(out)],
                            capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc2.returncode == 0, proc2.stderr.decode("utf-8", "replace")
    payload2 = json.loads(proc2.stdout.decode("utf-8"))
    assert payload2["typeset_defaults"] == []
    assert out.read_bytes() == first_bytes


def test_typeset_defaults_default_caption_prefixes(tmp_path):
    """caption_prefixes를 생략하면 모듈 기본값("표 ", "[그림")이 쓰인다.

    Rule 2: 캡션 문단 자신은 keep_with_next를 받지 않는다(patched에는 남되
    keep_with_next=False) — 대신 그 앞 객체(그림) 문단이 keep_with_next=True로
    patched된다. 이 fixture의 그림은 이미 신규(객체 -> 캡션) 레이아웃이라
    빈 text_head("") 항목으로 patched에 나타난다."""
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.apply_typeset_defaults(src, TYPESET_ANCHORS, out_path=out)
    assert result["ok"] is True
    caption_hits = [r for r in result["patched"] if r["text_head"].startswith("표 ")
                    or r["text_head"].startswith("[그림")]
    assert caption_hits
    assert all(r["keep_with_next"] is False for r in caption_hits)
    # 빈 text_head(객체 문단, 캡션 텍스트 없음) 중 keep_with_next=True인 항목이
    # 있어야 한다(그림 객체가 다음 캡션과 묶임).
    object_hits = [r for r in result["patched"] if r["text_head"] == "" and r["keep_with_next"]]
    assert object_hits


def test_typeset_defaults_cli_dry_run(tmp_path):
    src = _copy_fixture(tmp_path)
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    proc = subprocess.run(
        [sys.executable, script, str(src), "--typeset-defaults",
         "--caption-prefixes", "표 ,[그림", "--dry-run", "--out", str(out)],
        capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert "typeset_defaults" in payload
    assert len(payload["typeset_defaults"]) > 0
    assert not out.exists()


def test_typeset_defaults_cli_composes_with_before_and_keep_with_next(tmp_path):
    """CLI 배선: --before + --keep-with-next + --typeset-defaults를 한 호출에
    섞으면 세 결과 키(removed/patched/typeset_defaults)가 모두 나오고, 마지막
    typeset_defaults 패스가 keep-with-next가 세팅한 keepWithNext=1을 보존한다."""
    src = _copy_fixture_with_synthetic_blanks(tmp_path, ANCHOR, 3)
    _reset_keep_with_next_in_place(src, ["표 1."])
    out = tmp_path / "out.hwpx"
    import subprocess
    script = os.path.join(ROOT, "scripts", "tidy_hwpx.py")
    proc = subprocess.run(
        [sys.executable, script, str(src), "--before", ANCHOR,
         "--keep-with-next", "표 1.", "--typeset-defaults",
         "--caption-prefixes", "표 ,[그림", "--out", str(out)],
        capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert "removed" in payload
    assert "patched" in payload
    assert "typeset_defaults" in payload

    defs = _header_defs(out)
    xml = _section_xml(out)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    for (_s, _e, px, _oe, attrs) in paras:
        text = tidy_hwpx._para_text(px).strip()
        if text.startswith("표 1."):
            pid = tidy_hwpx._attr_value(attrs, "paraPrIDRef")
            b = _breaksetting_attrs(defs, pid)
            assert b["widowOrphan"] == "1"
            assert b["keepWithNext"] == "1"


# ---------------------------------------------------------------------------
# Rule 2: object-anchor keepWithNext flip — fully synthetic hwpx (no live
# fixture dependency, exercises the TABLE case directly since the live
# fixture's tables predate the caption-below-object layout).
# ---------------------------------------------------------------------------

def _build_minimal_synthetic_hwpx(tmp_path, body_paras_xml):
    """paraPr id=0(align=JUSTIFY, 빈 breakSetting)/charPr id=0 하나씩만 있는
    최소 header.xml + 주어진 문단 XML 조각들을 이어붙인 section0.xml로 hwpx를
    만든다. apply_typeset_defaults가 요구하는 paraProperties 컨테이너
    (itemCnt 속성 포함)를 갖춘 유효한 최소 구조."""
    header = (
        '<hh:head><hh:refList><hh:fontfaces/><hh:borderFills/>'
        '<hh:charProperties itemCnt="1">'
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="0"/></hh:charPr>'
        '</hh:charProperties>'
        '<hh:paraProperties itemCnt="1">'
        '<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/>'
        '<hh:breakSetting/></hh:paraPr>'
        '</hh:paraProperties>'
        '</hh:refList></hh:head>'
    )
    section = "".join(body_paras_xml)
    path = tmp_path / "synthetic.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
    return path


def _p(text):
    return (f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
            f'<hp:t>{text}</hp:t></hp:run></hp:p>')


def _p_table():
    """표(hp:tbl)를 담은 top-level 문단(객체 문단, 텍스트 없음)."""
    return ('<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
            '<hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:subList>'
            '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
            '<hp:t>셀</hp:t></hp:run></hp:p>'
            '</hp:subList></hp:tc></hp:tr></hp:tbl>'
            '</hp:run></hp:p>')


def test_object_anchor_gets_keep_with_next_for_table_caption_below(tmp_path):
    """Rule 2 핵심 케이스: 표 문단 바로 다음이 캡션("표 1. ...")이면, 표
    문단(객체)이 keepWithNext=1을 받고 캡션 문단 자신은 받지 않는다."""
    paras = [_p("blank-before-placeholder"), _p_table(), _p("표 1. 결과 요약"),
             _p("blank-after-placeholder"), _p("본문 계속")]
    path = _build_minimal_synthetic_hwpx(tmp_path, paras)
    out = tmp_path / "out.hwpx"
    result = tidy_hwpx.apply_typeset_defaults(path, [], caption_prefixes=["표 "], out_path=out)
    assert result["ok"] is True

    defs = _header_defs(out)
    xml = _section_xml(out)
    top_paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)

    table_idx = next(i for i, (_s, _e, px, _oe, _a) in enumerate(top_paras)
                      if tidy_hwpx._contains_object(px))
    caption_idx = next(i for i, (_s, _e, px, _oe, _a) in enumerate(top_paras)
                        if tidy_hwpx._para_text(px).strip().startswith("표 1."))
    assert caption_idx == table_idx + 1  # 캡션이 표 바로 다음(사이 blank 없음)

    table_pid = tidy_hwpx._attr_value(top_paras[table_idx][4], "paraPrIDRef")
    caption_pid = tidy_hwpx._attr_value(top_paras[caption_idx][4], "paraPrIDRef")
    assert _breaksetting_attrs(defs, table_pid)["keepWithNext"] == "1"
    assert _breaksetting_attrs(defs, caption_pid)["keepWithNext"] != "1"


def test_object_without_following_caption_gets_no_keep_with_next(tmp_path):
    """표 다음 문단이 캡션이 아니면(예: 캡션 없는 표) 표 문단도 keepWithNext를
    강제로 받지 않는다 — object_wants_keep_with_next는 오직 '다음이 캡션'
    조건에서만 True."""
    paras = [_p_table(), _p("캡션 아님, 그냥 본문")]
    path = _build_minimal_synthetic_hwpx(tmp_path, paras)
    out = tmp_path / "out.hwpx"
    tidy_hwpx.apply_typeset_defaults(path, [], caption_prefixes=["표 "], out_path=out)

    defs = _header_defs(out)
    xml = _section_xml(out)
    top_paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    table_idx = next(i for i, (_s, _e, px, _oe, _a) in enumerate(top_paras)
                      if tidy_hwpx._contains_object(px))
    table_pid = tidy_hwpx._attr_value(top_paras[table_idx][4], "paraPrIDRef")
    assert _breaksetting_attrs(defs, table_pid)["keepWithNext"] != "1"


def test_object_wants_keep_with_next_helper_direct():
    """_object_wants_keep_with_next 순수 함수 단위 테스트: (is_object, text)
    튜플 리스트에서 '다음이 캡션인 객체' 인덱스만 뽑아야 한다."""
    paras_text = [
        (False, "blank"),
        (True, ""),               # index 1: object, next is caption -> want
        (True, "표 1. 캡션"),      # index 2: caption text (not object per se,
                                    #   but flagged is_object=True here to prove
                                    #   the function only looks at *next* para's
                                    #   text, not whether i itself looks like one)
        (False, "본문"),
    ]
    want = tidy_hwpx._object_wants_keep_with_next(paras_text, ["표 "])
    assert want == {1}


def test_is_caption_respects_prefix_trailing_space():
    assert tidy_hwpx._is_caption("표본을 다룬다", ["표 "]) is False
    assert tidy_hwpx._is_caption("표 1. 결과", ["표 "]) is True


def test_is_heading_matches_anchor_prefix_only():
    assert tidy_hwpx._is_heading("Ⅰ. 서 론", ["Ⅰ. 서 론"]) is True
    assert tidy_hwpx._is_heading("표 1. 결과", ["Ⅰ. 서 론"]) is False


def test_typeset_defaults_table_object_flip_idempotent(tmp_path):
    """두 번 실행해도 byte-identical(멱등) — object-anchor flip도 기존 idempotence
    보장을 깨지 않아야 한다."""
    import shutil
    paras = [_p_table(), _p("표 1. 결과")]
    path = _build_minimal_synthetic_hwpx(tmp_path, paras)
    out1 = tmp_path / "out1.hwpx"
    tidy_hwpx.apply_typeset_defaults(path, [], caption_prefixes=["표 "], out_path=out1)

    out2 = tmp_path / "out2.hwpx"
    shutil.copyfile(out1, out2)
    result2 = tidy_hwpx.apply_typeset_defaults(out2, [], caption_prefixes=["표 "], out_path=out2)
    assert result2["patched"] == []
    with zipfile.ZipFile(out1) as z1, zipfile.ZipFile(out2) as z2:
        for n in z1.namelist():
            assert z1.read(n) == z2.read(n)
