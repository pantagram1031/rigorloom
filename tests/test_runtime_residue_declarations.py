# -*- coding: utf-8 -*-
"""RESIDUE-FINISH-03 — the Runtime finishing declaration.

Until this slice the Runtime ran the residue gate in report-final mode against
form fills: ``rt_engine.residue`` spawned ``check_residue.py --form-profile P
--artifact A`` with no keep list, no keep pattern and no fill map, so the
default keep pattern (numbered headings) kept nothing and every surviving form
label graded as residue. DIST-PAYLOAD-02 measured the consequence on a real
clean-room install — ``acceptance: false``, 25 ``form_residue`` findings, none
of them an unfilled field — and no plan derivable from ``inspect`` could have
passed, because ``inspect`` never showed the inventory the gate judges.

Three things close it, and this file is the contract for all three:

1. ``inspect --include forbidden`` projects the profile's own anchor records,
   removal targets and placeholders, with the paragraph addresses ``set_run``
   already takes. Additive: the default include set is unchanged.
2. A plan may carry ``declares`` — ``fillMap``/``keep``/``keepPattern``. It is
   bound to the ops: a declared value the plan does not write is refused at
   propose time, which is what stops a fill map from becoming a wildcard.
3. ``apply`` records the RESOLVED exemptions in the receipt and ``verify``
   re-uses them, so a later re-check grades the same document the same way
   without trusting a caller to re-supply the policy.

The keep derivation itself is NOT restated here or anywhere in the Runtime.
``visual_verify.derive_form_keep`` owns the formula
``(anchors ∪ placeholders) − consumed`` and the ambiguity refusal; the Runtime
spawns it. ``tests/test_keep_derivation_is_stated_once.py`` guards that.

The adversarial half of this file matters more than the positive half. A
declaration is an exemption mechanism, and an exemption mechanism that cannot
be shown to refuse anything is indistinguishable from a disabled gate. So:
a broad keep pattern, a declared value that was never written, a second
unfilled occurrence of a filled label, guide text, and an ambiguous key each
get a test that pins the refusal.
"""
from __future__ import annotations

import json
import shutil

import pytest

from _runtime_client import CORPUS_FORM, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_plan  # noqa: E402
from rt_codes import RpcError  # noqa: E402

#: PII-free filler: a blank government form plus a common noun.
VALUE = "검증"


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


def _session(root, source) -> str:
    result = run_cli(root, "open", "--path", str(source))
    assert result.code == 0, result.stdout
    return result.result["sessionId"]


def _forbidden(root, session) -> dict:
    result = run_cli(root, "inspect", "--session", session,
                     "--include", "forbidden")
    assert result.code == 0, result.stdout
    return result.result["forbidden"]


def _fill_ops(inventory, count):
    """Ops that fill the first ``count`` anchor paragraphs, keeping the label.

    A labeled field keeps its label as a prefix — that is what makes the key
    text survive INSIDE the value and why ``--fill-map`` exists at all. The
    addresses come from the inventory, never from a literal.
    """
    ops, fill_map = [], {}
    for entry in inventory["anchors"][:count]:
        written = f"{entry['text']} {VALUE}"
        ops.append({"kind": "set_run", "atPara": entry["atPara"],
                    "run": 0, "text": written})
        fill_map[entry["text"]] = written
    return ops, fill_map


def _propose(root, session, ops, declares=None, **kwargs):
    argv = ["propose", "--session", session]
    for op in ops:
        argv += ["--op", json.dumps(op, ensure_ascii=False)]
    if declares is not None:
        path = kwargs["tmp_path"] / "declares.json"
        path.write_text(json.dumps(declares, ensure_ascii=False),
                        encoding="utf-8")
        argv += ["--declares-file", str(path)]
    return run_cli(root, *argv)


# --------------------------------------------------------------------------- #
# 1. the forbidden inventory reaches inspect
# --------------------------------------------------------------------------- #
class TestForbiddenInventory:
    def test_inspect_projects_the_profile_inventory(self, root, source):
        inventory = _forbidden(root, _session(root, source))
        assert inventory["anchors"], "no anchors projected"
        for entry in inventory["anchors"]:
            assert isinstance(entry["text"], str) and entry["text"]
            assert isinstance(entry["atPara"], int) and entry["atPara"] >= 0
            assert isinstance(entry["paraIdx"], int)
            assert entry["section"]
        assert isinstance(inventory["placeholders"], list)
        assert isinstance(inventory["removalTargets"], list)

    def test_the_inventory_matches_what_the_gate_will_judge(self, root, source):
        """Same counts as the profile, or an agent is planning against fiction."""
        inventory = _forbidden(root, _session(root, source))
        assert inventory["counts"]["anchors"] == len(inventory["anchors"])
        assert inventory["counts"]["placeholders"] == len(inventory["placeholders"])
        assert inventory["counts"]["removalTargets"] == len(
            inventory["removalTargets"])

    def test_removal_targets_are_marked_as_guide_not_furniture(self, root, source):
        """The distinction the keep derivation refuses to blur."""
        inventory = _forbidden(root, _session(root, source))
        for entry in inventory["removalTargets"]:
            assert entry["keepable"] is False
            assert entry["reason"], "a removal target with no reason"
        for entry in inventory["anchors"]:
            assert entry["keepable"] is True

    def test_forbidden_is_additive_and_not_in_the_default_include(self, root,
                                                                  source):
        session = _session(root, source)
        default = run_cli(root, "inspect", "--session", session)
        assert default.code == 0
        assert "forbidden" not in default.result
        assert {"summary", "graph", "regions"} <= set(default.result)

    def test_an_unknown_include_section_is_still_refused(self, root, source):
        session = _session(root, source)
        result = run_cli(root, "inspect", "--session", session,
                         "--include", "forbidden,nonsense")
        assert result.code == 2
        assert result.error["code"] == "invalid_params"


class TestErrorVocabulary:
    """The one new code, and the one place its exit status is decided."""

    def test_the_code_is_declared_in_the_closed_vocabulary(self):
        assert "ambiguous_fill_keys" in rt_codes.DOMAIN_CODES
        assert "ambiguous_fill_keys" in rt_codes.ERROR_CODES
        # The closed-set invariant transport tests already pin, restated here
        # so adding this member cannot quietly break it.
        assert rt_codes.TRANSPORT_CODES & rt_codes.DOMAIN_CODES == frozenset()

    def test_it_is_constructible_and_carries_its_structure(self):
        error = RpcError("ambiguous_fill_keys", "two claims",
                         keys=[{"key": "시행", "matched": [{"text": "a"},
                                                          {"text": "b"}]}])
        frame = error.to_frame_error()
        assert frame["code"] == "ambiguous_fill_keys"
        assert frame["data"]["keys"][0]["matched"], (
            "the refusal must name what the key claimed, not just that it did")

    def test_the_cli_maps_it_to_the_usage_exit_not_the_refusal_exit(self):
        """Exit 2, because the document was never judged."""
        import cli as runtime_cli

        assert "ambiguous_fill_keys" in runtime_cli.USAGE_CODES
        assert runtime_cli.USAGE_CODES >= {"invalid_params", "unknown_field"}


# --------------------------------------------------------------------------- #
# 2. the declaration is bound to the plan's own ops
# --------------------------------------------------------------------------- #
class TestDeclarationBinding:
    def test_a_declared_value_the_plan_never_writes_is_refused(self, root,
                                                               source, tmp_path):
        """The vector that would turn a fill map into a wildcard.

        Declaring ``{"수신": "수신"}`` would put a value span over the form's
        own label and attribute the label to itself. Nothing was written, so
        nothing may be declared.
        """
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, _ = _fill_ops(inventory, 2)
        label = inventory["anchors"][0]["text"]
        result = _propose(root, session, ops,
                          declares={"fillMap": {label: label}},
                          tmp_path=tmp_path)
        assert result.code == 2, result.stdout
        assert result.error["code"] == "invalid_params"
        assert "does not write" in result.error["message"]
        assert result.error["data"]["value"] == label

    def test_a_declaration_matching_the_ops_is_accepted(self, root, source,
                                                        tmp_path):
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, fill_map = _fill_ops(inventory, 2)
        result = _propose(root, session, ops, declares={"fillMap": fill_map},
                          tmp_path=tmp_path)
        assert result.code == 0, result.stdout
        declares = result.result["plan"]["declares"]
        assert declares["fillMap"] == fill_map

    def test_declares_does_not_change_opsHash(self, root, source, tmp_path):
        """opsHash covers {backend, boundSha256, ops}. Parity must survive."""
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, fill_map = _fill_ops(inventory, 2)
        plain = _propose(root, session, ops, tmp_path=tmp_path)
        declared = _propose(root, session, ops, declares={"fillMap": fill_map},
                            tmp_path=tmp_path)
        assert plain.code == 0 and declared.code == 0
        assert (plain.result["plan"]["opsHash"]
                == declared.result["plan"]["opsHash"])
        assert (plain.result["plan"]["planHash"]
                != declared.result["plan"]["planHash"]), (
            "planHash must move: an approval binds the whole plan")

    def test_an_unknown_declares_field_is_refused(self, root, source, tmp_path):
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, _ = _fill_ops(inventory, 1)
        result = _propose(root, session, ops,
                          declares={"fillMap": {}, "keepEverything": True},
                          tmp_path=tmp_path)
        assert result.code == 2
        assert result.error["code"] == "unknown_field"

    def test_a_blanket_keep_pattern_is_refused(self, root, source, tmp_path):
        """A pattern that keeps everything leaves the gate nothing to judge."""
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, fill_map = _fill_ops(inventory, 1)
        for pattern in (".*", "", "^", ".?", "(?s).*"):
            result = _propose(root, session, ops,
                              declares={"fillMap": fill_map,
                                        "keepPattern": pattern},
                              tmp_path=tmp_path)
            assert result.code == 2, f"{pattern!r} was accepted: {result.stdout}"
            assert result.error["code"] == "invalid_params"

    def test_a_keep_entry_is_a_whole_inventory_entry_not_a_prefix(
            self, root, source, tmp_path):
        """``check_residue`` matches a keep against the ENTIRE entry.

        A prefix keeps nothing and fails silently (operations.md). Silence is
        the defect, so the Runtime refuses it out loud.
        """
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, fill_map = _fill_ops(inventory, 1)
        prefix = inventory["anchors"][0]["text"][:1]
        result = _propose(root, session, ops,
                          declares={"fillMap": fill_map, "keep": [prefix]},
                          tmp_path=tmp_path)
        assert result.code == 2, result.stdout
        assert result.error["code"] == "invalid_params"

    def test_an_invalid_regex_is_a_usage_error_not_a_crash(self, root, source,
                                                           tmp_path):
        session = _session(root, source)
        inventory = _forbidden(root, session)
        ops, fill_map = _fill_ops(inventory, 1)
        result = _propose(root, session, ops,
                          declares={"fillMap": fill_map, "keepPattern": "([a"},
                          tmp_path=tmp_path)
        assert result.code == 2
        assert result.error["code"] == "invalid_params"


# --------------------------------------------------------------------------- #
# 3. unit-level binding rules (no subprocess)
# --------------------------------------------------------------------------- #
class TestNormaliseDeclares:
    def _ops(self):
        return [{"opId": "op-1", "kind": "set_run",
                 "params": {"atPara": 3, "run": 0, "text": "수신 검증"}}]

    def test_none_stays_none(self):
        assert rt_plan.normalise_declares(None, self._ops()) is None

    def test_written_values_are_accepted(self):
        out = rt_plan.normalise_declares({"fillMap": {"수신": "수신 검증"}},
                                         self._ops())
        assert out["fillMap"] == {"수신": "수신 검증"}

    def test_unwritten_value_raises_invalid_params(self):
        with pytest.raises(RpcError) as excinfo:
            rt_plan.normalise_declares({"fillMap": {"수신": "수신"}}, self._ops())
        assert excinfo.value.code == "invalid_params"

    def test_a_scoped_value_is_bound_to_the_ops_too(self):
        """``{"text": V, "other_occurrences": …}`` must bind on V, not skip."""
        with pytest.raises(RpcError) as excinfo:
            rt_plan.normalise_declares(
                {"fillMap": {"수신": {"text": "never written",
                                     "other_occurrences": "form_text"}}},
                self._ops())
        assert excinfo.value.code == "invalid_params"
        ok = rt_plan.normalise_declares(
            {"fillMap": {"수신": {"text": "수신 검증",
                                 "other_occurrences": "form_text"}}},
            self._ops())
        assert ok["fillMap"]["수신"]["other_occurrences"] == "form_text"

    def test_an_unknown_scope_value_is_refused(self):
        with pytest.raises(RpcError) as excinfo:
            rt_plan.normalise_declares(
                {"fillMap": {"수신": {"text": "수신 검증",
                                     "other_occurrences": "whatever"}}},
                self._ops())
        assert excinfo.value.code == "invalid_params"

    def test_an_empty_declaration_is_refused(self):
        with pytest.raises(RpcError) as excinfo:
            rt_plan.normalise_declares({}, self._ops())
        assert excinfo.value.code == "invalid_params"


# --------------------------------------------------------------------------- #
# 4. the finished flow, and every way it must still refuse
# --------------------------------------------------------------------------- #
def _drive(root, source, tmp_path, ops, declares):
    """propose -> validate -> request-approval -> approve -> apply."""
    session = _session(root, source)
    proposed = _propose(root, session, ops, declares=declares, tmp_path=tmp_path)
    assert proposed.code == 0, proposed.stdout
    plan = proposed.result["plan"]
    assert run_cli(root, "validate", "--plan", plan["planId"]).code == 0
    approval = run_cli(root, "request-approval", "--plan",
                       plan["planId"]).result["approval"]
    approved = run_cli(root, "approve", "--approval", approval["approvalId"],
                       "--plan", plan["planId"],
                       "--plan-hash", plan["planHash"])
    assert approved.code == 0, approved.stdout
    applied = run_cli(root, "apply", "--plan", plan["planId"],
                      "--approval", approval["approvalId"])
    return session, plan, applied


class TestFinishedFlow:
    def test_a_fully_declared_fill_reaches_acceptance(self, root, source,
                                                      tmp_path):
        """The positive case: every anchor either filled or legitimately kept."""
        session_id = _session(root, source)
        inventory = _forbidden(root, source and session_id)
        ops, fill_map = _fill_ops(inventory, 3)
        session, _plan, applied = _drive(root, source, tmp_path, ops,
                                         {"fillMap": fill_map})
        assert applied.code == 0, applied.stdout
        checks = applied.result["candidate"]["checks"]
        assert checks["ranAll"] is True, checks
        assert checks["acceptance"] is True, checks
        assert checks["checks"][0]["state"] == "ran"

    def test_the_receipt_records_the_applied_exemptions(self, root, source,
                                                        tmp_path):
        """Auditable: what was exempted, and on whose authority."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        ops, fill_map = _fill_ops(inventory, 3)
        session, _plan, applied = _drive(root, source, tmp_path, ops,
                                         {"fillMap": fill_map})
        assert applied.code == 0, applied.stdout
        run_id = applied.result["candidate"]["runId"]
        receipt = run_cli(root, "receipt", "--session", session,
                          "--run", run_id)
        assert receipt.code == 0, receipt.stdout
        exemptions = receipt.result["receipt"]["exemptions"]
        assert exemptions["source"] == "plan.declares"
        assert exemptions["planHash"]
        assert exemptions["derivedKeep"], "no derived keep list recorded"
        assert exemptions["consumed"], "nothing recorded as consumed"
        assert "unfilled" in exemptions
        assert exemptions["derivation"] == "visual_verify.derive_form_keep"

    def test_verify_reuses_the_receipt_bound_declaration(self, root, source,
                                                         tmp_path):
        """A later re-check grades the same way without re-supplying policy."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        ops, fill_map = _fill_ops(inventory, 3)
        session, _plan, applied = _drive(root, source, tmp_path, ops,
                                         {"fillMap": fill_map})
        run_id = applied.result["candidate"]["runId"]
        verified = run_cli(root, "verify", "--session", session, "--run", run_id)
        assert verified.code == 0, verified.stdout
        assert verified.result["checks"]["acceptance"] is True
        assert verified.result["checks"]["exemptions"]["source"] == "plan.declares"

    def test_an_undeclared_plan_still_grades_strictly(self, root, source,
                                                      tmp_path):
        """No declaration means exactly the pre-existing behaviour."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        ops, _ = _fill_ops(inventory, 3)
        session, _plan, applied = _drive(root, source, tmp_path, ops, None)
        assert applied.code == 0, applied.stdout
        checks = applied.result["candidate"]["checks"]
        assert checks["ranAll"] is True
        assert checks["acceptance"] is False, (
            "an undeclared form fill must still be graded as a report final")
        assert checks.get("exemptions") is None


class TestAdversarial:
    """Each test here is a way the exemption could have become a free pass."""

    def test_a_second_unfilled_occurrence_still_hards(self, root, source,
                                                     tmp_path):
        """Per-occurrence attribution, not global suppression.

        The label is filled at ONE of the addresses it occupies and left alone
        at the others. The filled occurrence is attributed to its value's span;
        the rest are still residue, each with its offset. If attribution were
        global — "this string is declared, stop looking for it" — this test
        would go green on a document that is two thirds unfilled.

        ``other_occurrences: "seats"`` is here because the only anchor this
        corpus form repeats is also a substring of other entries, so the key is
        ambiguous and the gate refuses to guess. ``seats`` is the documented
        answer that means "the rest are empty slots, and they HARD" — which is
        precisely the property under test, said out loud by the caller.
        """
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        repeated = _repeated_anchor(inventory)
        if repeated is None:
            pytest.skip("this corpus form has no anchor text at two addresses")
        first, second = repeated
        assert first["atPara"] != second["atPara"]
        written = f"{first['text']} {VALUE}"
        ops = [{"kind": "set_run", "atPara": first["atPara"], "run": 0,
                "text": written}]
        session, _plan, applied = _drive(
            root, source, tmp_path, ops,
            {"fillMap": {first["text"]: {"text": written,
                                         "other_occurrences": "seats"}}})
        assert applied.code == 0, applied.stdout
        checks = applied.result["candidate"]["checks"]
        assert checks["acceptance"] is False, (
            "every occurrence of the declared label was exempted; attribution "
            "is supposed to be per occurrence")
        rows = checks["checks"][0]["hard"]
        assert rows, "the unfilled occurrences produced no finding"
        assert any(row.get("at_offsets") for row in rows)
        assert checks["exemptions"]["source"] == "plan.declares"

    def test_guide_text_is_never_exempted(self, root, source, tmp_path):
        """Instruction prose cannot be laundered through a fill map."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        if not inventory["removalTargets"]:
            pytest.skip("this corpus form declares no removal target")
        guide = inventory["removalTargets"][0]
        written = f"{guide['text']} {VALUE}"
        ops = [{"kind": "set_run", "atPara": guide["atPara"], "run": 0,
                "text": written}]
        result = _propose(root, _session(root, source), ops,
                          declares={"fillMap": {guide["text"]: written},
                                    "keep": [guide["text"]]},
                          tmp_path=tmp_path)
        assert result.code == 2, result.stdout
        assert result.error["code"] == "invalid_params"
        assert "guide" in result.error["message"].lower()

    def test_an_ambiguous_fill_key_is_refused_with_its_own_code(self, root,
                                                                source,
                                                                tmp_path):
        """One key claiming two inventory strings: exit 2, ambiguous_fill_keys."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        pair = _substring_pair(inventory)
        if pair is None:
            pytest.skip("this corpus form has no nested anchor pair")
        shorter, _longer = pair
        written = f"{shorter} {VALUE}"
        anchor = next(entry for entry in inventory["anchors"]
                      if entry["text"] == shorter)
        ops = [{"kind": "set_run", "atPara": anchor["atPara"], "run": 0,
                "text": written}]
        _session_id, _plan, applied = _drive(root, source, tmp_path, ops,
                                             {"fillMap": {shorter: written}})
        # Exit 2, not 3: the document was never judged, so this is a usage
        # error at the adapter boundary and not a gate refusal.
        assert applied.code == 2, applied.stdout
        assert applied.error["code"] == "ambiguous_fill_keys"
        keys = applied.error["data"]["keys"]
        assert keys, "the refusal names no key"
        assert keys[0]["matched"], "the refusal does not say what the key claimed"
        assert len(keys[0]["matched"]) > 1

    def test_a_declaration_cannot_be_swapped_after_approval(self, root, source,
                                                            tmp_path):
        """The exemptions are the approved plan's, not a later caller's."""
        session_id = _session(root, source)
        inventory = _forbidden(root, session_id)
        ops, fill_map = _fill_ops(inventory, 2)
        proposed = _propose(root, session_id, ops,
                            declares={"fillMap": fill_map}, tmp_path=tmp_path)
        assert proposed.code == 0
        plan = proposed.result["plan"]
        approval = run_cli(root, "request-approval", "--plan",
                           plan["planId"]).result["approval"]
        # Approving a DIFFERENT hash than the plan carries is already refused;
        # this pins that the declaration is inside the hashed body.
        tampered = plan["planHash"][:-1] + ("0" if plan["planHash"][-1] != "0"
                                            else "1")
        refused = run_cli(root, "approve", "--approval", approval["approvalId"],
                          "--plan", plan["planId"], "--plan-hash", tampered)
        assert refused.code == 3
        assert refused.error["code"] == "approval_binding_mismatch"


def _repeated_anchor(inventory):
    """Two inventory entries carrying the SAME text at different addresses."""
    by_text: dict[str, list] = {}
    for entry in inventory["anchors"]:
        by_text.setdefault(entry["text"], []).append(entry)
    for entries in by_text.values():
        if len(entries) >= 2:
            return entries[0], entries[1]
    return None


def _substring_pair(inventory):
    """(shorter, longer) where the shorter is contained in the longer.

    ``derive_form_keep`` matches a key against the inventory by normalized
    substring in EITHER direction, so such a pair makes one key claim two
    strings — the ambiguity the gate refuses rather than guesses about.
    """
    texts = sorted({entry["text"] for entry in inventory["anchors"]},
                   key=len)
    for index, shorter in enumerate(texts):
        if len(shorter) < 2:
            continue
        for longer in texts[index + 1:]:
            if shorter in longer:
                return shorter, longer
    return None
