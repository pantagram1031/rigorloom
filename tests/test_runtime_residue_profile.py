# -*- coding: utf-8 -*-
"""S9: a session is judged against its real form, not a scan of a finished copy.

open --form-profile / --form binds a blank-form inventory. Residue and
inspect forbidden use that binding; the self-derived path is unchanged.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from _runtime_client import REPO_ROOT, RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

from rt_engine import EngineTools  # noqa: E402
from rt_session import sha256_file  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
ODF_MANIFEST = "urn:oasis:names:opendocument:xmlns:manifest:1.0"

HEADING = "1. 연구설계"
# Longer than form_inspect's 40-char bracket-wrap so these are NOT anchors;
# instruction keywords still make them guide/removal targets.
GUIDE = ("본문 칸에는 탐구의 과정과 결과를 빠짐없이 작성하십시오. "
         "빈 칸을 남기지 않습니다.")
PLACEHOLDER = "[제목]"
BODY = "교육용 2.5D"
PROSE = ("교실에서 소리가 퍼지는 방식을 여러 위치에서 측정하고 "
         "그 과정을 기술한다.")
FILLED_TITLE = "교실 음향 측정"
REPLACED = "교육용 2.5D(S9)"

XML_BACKEND = REPO_ROOT / "engine" / "scripts" / "xml_backend.py"


def make_hwpx(path: Path, paragraphs: list[str]) -> Path:
    header = f'''<hh:head xmlns:hh="{HH}"><hh:refList>
<hh:paraProperties itemCnt="2">
<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/></hh:paraPr>
<hh:paraPr id="1"><hh:align horizontal="CENTER"/></hh:paraPr>
</hh:paraProperties><hh:charProperties itemCnt="3">
<hh:charPr id="0" height="1000"/><hh:charPr id="1" height="900"><hh:bold/></hh:charPr>
<hh:charPr id="2" height="900"/>
</hh:charProperties>
<hh:borderFills itemCnt="1"><hh:borderFill id="0"/></hh:borderFills>
</hh:refList></hh:head>'''.encode()
    secpr = (f'<hp:secPr><hp:pagePr width="60000" height="84000">'
             f'<hp:margin left="4000" right="5000" top="5000" bottom="5000" '
             f'header="0" footer="0" gutter="1000"/></hp:pagePr></hp:secPr>')
    parts = []
    for index, text in enumerate(paragraphs):
        run = f'<hp:run charPrIDRef="0">'
        if index == 0:
            run += secpr
        run += f'<hp:t>{text}</hp:t></hp:run>'
        parts.append(f'<hp:p id="{10 + index}" paraPrIDRef="0">{run}</hp:p>')
    section = f'<hp:sec xmlns:hp="{HP}">{"".join(parts)}</hp:sec>'.encode()
    content_hpf = f'''<opf:package xmlns:opf="{OPF}"><opf:manifest>
<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
</opf:manifest></opf:package>'''.encode()
    manifest = f'''<manifest:manifest xmlns:manifest="{ODF_MANIFEST}">
<manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>
</manifest:manifest>'''.encode()
    members = {
        "mimetype": b"application/hwp+zip",
        "Contents/header.xml": header,
        "Contents/section0.xml": section,
        "Contents/content.hpf": content_hpf,
        "META-INF/manifest.xml": manifest,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


BLANK_PARAS = [HEADING, GUIDE, PLACEHOLDER]
FINISHED_PARAS = [HEADING, PROSE, FILLED_TITLE, BODY]
DIRTY_PARAS = [HEADING, GUIDE, FILLED_TITLE, BODY]


@pytest.fixture()
def forms(tmp_path):
    blank = make_hwpx(tmp_path / "blank.hwpx", BLANK_PARAS)
    finished = make_hwpx(tmp_path / "finished.hwpx", FINISHED_PARAS)
    dirty = make_hwpx(tmp_path / "dirty.hwpx", DIRTY_PARAS)
    profile = tmp_path / "blank_profile.json"
    EngineTools().profile(blank, profile)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    assert len(GUIDE) > 40 and len(PROSE) > 40
    guide_texts = [g.get("text") for g in payload.get("guide_text") or []
                   if isinstance(g, dict)]
    assert GUIDE in guide_texts, payload.get("guide_text")
    removal_texts = []
    guides = {g.get("para_idx"): g for g in payload.get("guide_text") or []
              if isinstance(g, dict)}
    for target in payload.get("removal_targets") or []:
        if isinstance(target, dict):
            entry = guides.get(target.get("para_idx")) or {}
            removal_texts.append(entry.get("text"))
    assert GUIDE in removal_texts, (payload.get("removal_targets"), guide_texts)
    return {"blank": blank, "finished": finished, "dirty": dirty,
            "profile": profile, "payload": payload}


def _open(root, path, **flags):
    argv = ["open", "--path", str(path)]
    if flags.get("form_profile"):
        argv += ["--form-profile", str(flags["form_profile"])]
    if flags.get("form"):
        argv += ["--form", str(flags["form"])]
    result = run_cli(root, *argv)
    assert result.code == 0, result.stdout + result.stderr
    return result.result


def _forbidden(root, session):
    result = run_cli(root, "inspect", "--session", session, "--include", "forbidden")
    assert result.code == 0, result.stdout + result.stderr
    return result.result["forbidden"]


def _texts(entries):
    return [entry["text"] for entry in entries if isinstance(entry.get("text"), str)]


def _drive_xml_replace(root, session):
    op = json.dumps({"kind": "replace_all", "find": BODY, "replace": REPLACED},
                    ensure_ascii=False)
    plan = run_cli(root, "propose", "--session", session, "--backend", "xml",
                   "--op", op)
    assert plan.code == 0, plan.stdout + plan.stderr
    payload = plan.result["plan"]
    run_cli(root, "validate", "--plan", payload["planId"])
    approval = run_cli(root, "request-approval",
                       "--plan", payload["planId"]).result["approval"]
    approved = run_cli(root, "approve", "--approval", approval["approvalId"],
                       "--plan", payload["planId"],
                       "--plan-hash", payload["planHash"],
                       "--approver", "s9-test")
    assert approved.code == 0, approved.stdout
    applied = run_cli(root, "apply", "--plan", payload["planId"],
                      "--approval", approval["approvalId"])
    assert applied.code == 0, applied.stdout + applied.stderr
    return applied.result, payload, approval


# --------------------------------------------------------------------------- #
# open binding
# --------------------------------------------------------------------------- #

def test_open_form_profile_stores_the_binding(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["finished"], form_profile=forms["profile"])
    digest, _ = sha256_file(forms["profile"])
    assert opened["formProfile"]["bound"] is True
    assert opened["formProfile"]["sha256"] == digest
    assert opened["formProfile"]["origin"] == forms["profile"].name
    assert opened["formProfile"]["kind"] == "profile"
    assert "originPath" not in opened["formProfile"]
    session_dir = next((root / "sessions").iterdir())
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["formProfile"]["sha256"] == digest
    assert meta["formProfile"]["originPath"] == str(forms["profile"])


def test_open_form_derives_the_profile(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["finished"], form=forms["blank"])
    assert opened["formProfile"]["bound"] is True
    assert opened["formProfile"]["kind"] == "form"
    assert len(opened["formProfile"]["sha256"]) == 64
    forbidden = _forbidden(root, opened["sessionId"])
    assert forbidden["residue"]["profileSource"] == "bound_form"
    assert GUIDE in _texts(forbidden["removalTargets"])
    assert PROSE not in _texts(forbidden["removalTargets"])


def test_a_profile_without_form_hash_is_refused(tmp_path, forms):
    root = tmp_path / "root"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"anchors": ["x"]}), encoding="utf-8")
    result = run_cli(root, "open", "--path", str(forms["finished"]),
                     "--form-profile", str(bad))
    assert result.code == 2
    assert result.error["code"] == "invalid_params"


def test_form_and_form_profile_together_are_refused(tmp_path, forms):
    root = tmp_path / "root"
    result = run_cli(root, "open", "--path", str(forms["finished"]),
                     "--form-profile", str(forms["profile"]),
                     "--form", str(forms["blank"]))
    assert result.code == 2


def test_jsonl_open_accepts_form_profile(tmp_path, forms):
    digest, _ = sha256_file(forms["profile"])
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        opened = client.ok("workspace/openPath", {
            "path": str(forms["finished"]),
            "formProfile": str(forms["profile"]),
        })
        assert opened["formProfile"]["sha256"] == digest
        forbidden = client.ok("document/inspect", {
            "sessionId": opened["sessionId"],
            "include": ["forbidden"],
        })["forbidden"]
        assert forbidden["residue"]["profileSource"] == "bound_form"


# --------------------------------------------------------------------------- #
# inspect forbidden
# --------------------------------------------------------------------------- #

def test_bound_form_uses_blank_anchors_not_finished_prose(tmp_path, forms):
    root = tmp_path / "root"
    bound = _open(root, forms["finished"], form_profile=forms["profile"])
    inventory = _forbidden(root, bound["sessionId"])
    assert inventory["residue"]["profileSource"] == "bound_form"
    assert inventory["residue"]["sha256"] == bound["formProfile"]["sha256"]
    assert GUIDE in _texts(inventory["removalTargets"])
    assert PROSE not in _texts(inventory["removalTargets"])
    assert PLACEHOLDER in _texts(inventory["placeholders"]) or PLACEHOLDER in _texts(
        inventory["anchors"])


def test_self_derived_flags_finished_prose_as_removal(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["finished"])
    assert "formProfile" not in opened
    inventory = _forbidden(root, opened["sessionId"])
    assert inventory["residue"]["profileSource"] == "self_derived"
    assert inventory["residue"]["sha256"]
    assert PROSE in _texts(inventory["removalTargets"])
    assert GUIDE not in _texts(inventory["removalTargets"])
    assert "heuristic" in inventory["residue"].get("note", "")


# --------------------------------------------------------------------------- #
# apply receipts
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not XML_BACKEND.is_file(), reason="xml_backend.py not found")
def test_bound_apply_accepts_when_the_guide_is_gone(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["finished"], form_profile=forms["profile"])
    applied, _, _ = _drive_xml_replace(root, opened["sessionId"])
    checks = applied["candidate"]["checks"]
    assert checks["ranAll"] is True, checks
    assert checks["acceptance"] is True, checks
    receipt = run_cli(root, "receipt", "--session", opened["sessionId"],
                      "--run", applied["candidate"]["runId"]).result["receipt"]
    residue = receipt["residue"]
    assert residue["profileSource"] == "bound_form"
    assert residue["sha256"] == opened["formProfile"]["sha256"]
    assert "originPath" not in residue
    assert str(forms["profile"]) not in json.dumps(receipt, ensure_ascii=False)


@pytest.mark.skipif(not XML_BACKEND.is_file(), reason="xml_backend.py not found")
def test_bound_apply_fails_when_a_guide_sentence_survives(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["dirty"], form_profile=forms["profile"])
    applied, _, _ = _drive_xml_replace(root, opened["sessionId"])
    checks = applied["candidate"]["checks"]
    assert checks["ranAll"] is True
    assert checks["acceptance"] is False, (
        "leaving the bound form's guide in the candidate must still fail residue")
    receipt = run_cli(root, "receipt", "--session", opened["sessionId"],
                      "--run", applied["candidate"]["runId"]).result["receipt"]
    assert receipt["residue"]["profileSource"] == "bound_form"
    row = checks["checks"][0]
    hard = row.get("hard") or []
    assert hard, row


@pytest.mark.skipif(not XML_BACKEND.is_file(), reason="xml_backend.py not found")
def test_self_derived_apply_still_carries_profile_source(tmp_path, forms):
    root = tmp_path / "root"
    opened = _open(root, forms["finished"])
    applied, _, _ = _drive_xml_replace(root, opened["sessionId"])
    receipt = run_cli(root, "receipt", "--session", opened["sessionId"],
                      "--run", applied["candidate"]["runId"]).result["receipt"]
    assert receipt["residue"]["profileSource"] == "self_derived"
    assert "heuristic" in receipt["residue"].get("note", "")
    # The opened document's own prose is a removal target, so the gate bites.
    assert applied["candidate"]["checks"]["acceptance"] is False
