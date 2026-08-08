# -*- coding: utf-8 -*-
"""Corpus-backed regression for check_hr over the VERSIONED PAIR.

Four claims the synthetic fixtures cannot make:

1. Running the checker over the REAL blank forms — both revisions, in their
   untouched blank state, with and without a baseline — reports the expected
   *unfilled* shape and exits 0. It must not crash, and it must not fail a form
   nobody has filled.
2. The 2013 → 2025 drift documented in ``skill/references/hr_flow.md`` §5 is
   RE-DERIVED here rather than asserted from memory, so the table cannot rot
   silently. That includes the two dropped-rule premises (no paper-spec footer,
   no ``______`` blank runs) and the five absent 민원 structures.
3. The version fingerprints are strictly disjoint on the real forms: every
   marker occurs in its own revision and zero times in the other. Overlap would
   make every document read as ``template_version_mixed``.
4. A copy filled with the engine's own operations (``preedit replace``) passes
   every rule, and the still-catches variants — a deleted clause, a consumed
   legal sentence, a lost signature marker, a migrated revision, an invented
   account number — are all caught. The fill is produced here rather than
   committed, so both halves of the pipeline (engine fill → module gate) are
   exercised together.

The corpus originals are never written to: every step works on a copy under
``tmp_path`` and the tests assert the originals are byte-identical afterwards.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
_CORPUS = _REPO_ROOT / "tests" / "corpus" / "forms"
for _dir in (_MODULE_ROOT / "scripts", _REPO_ROOT / "engine" / "scripts",
             _REPO_ROOT / "pipeline" / "scripts", _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_hr as ch  # noqa: E402
import preedit  # noqa: E402

#: The family-⑦ versioned pair (docs/research/hwp-usage-landscape.md family ⑦;
#: tests/corpus/forms/manifest.json family "hr"). Cross-checked against the
#: manifest by test_the_pair_is_what_the_manifest_says_it_is.
HR_2013 = "moel-pyojun-geunrogyeyakseo-2013"
HR_2025 = "moel-pyojun-geunrogyeyakseo-2025"
HR_FORMS = (HR_2013, HR_2025)

#: What an agent filling the 2025 pack's 기간의 정함이 없는 경우 contract writes.
#: Keys are run texts / substrings from the form. 생년월일 and any account number
#: are ABSENT on purpose — the operator supplied none, so those seats stay empty
#: and check_hr must not complain about that.
#: The pack holds SIX variant contracts in one file and repeats these clause
#: labels across its variants, so every key below resolves to 3–5 places
#: (T41). Filling one contract means saying WHICH sheet — `at_para` addresses
#: the paragraph the way `--at-cell` addresses a cell, and the numbers come
#: straight out of the refusal payload (`context_before` includes the variant
#: title even when the immediately preceding clause is identical). The
#: unscoped spelling of this very map is what silently rewrote sibling
#: contracts; the `TestUnscopedFillOverwritesTheSiblingContracts` tests pin the
#: refusal, reproduced corruption, and surgical scoped edit.
_SHEET_1 = "표준근로계약서(기간의 정함이 없는 경우)"
FILL_MAP = {
    "(이하 “사업주”라 함)과(와) ": {
        "text": "한빛정밀 주식회사(이하 “사업주”라 함)과(와) ", "at_para": 2},
    "(이하 “근로자”라 함)은": {
        "text": "이서준(이하 “근로자”라 함)은", "at_para": 2},
    "1. 근로개시일 :      년   월   일부터": {
        "text": "1. 근로개시일 :  2026년 9월 1일부터", "at_para": 3},
    "2. 근 무 장 소 : ": {
        "text": "2. 근 무 장 소 : 경기도 화성시 동탄산단로 15", "at_para": 4},
    "3. 업무의 내용 : ": {
        "text": "3. 업무의 내용 : 정밀 이송 스테이지 조립 및 검사", "at_para": 5},
    "- 월(일, 시간)급 : ": {
        "text": "- 월(일, 시간)급 : 2,800,000 ", "at_para": 10},
    "      년      월      일": {
        "text": "     2026년   8월   20일", "at_para": 28},
    "사업체명 :                   (전화": {
        "text": "사업체명 : 한빛정밀 주식회사 (전화", "at_para": 29},
    "대 표 자 :                   (서명)": {
        "text": "대 표 자 : 김도현 (서명)", "at_para": 29},
    "(근로자) 주    소 :": {
        "text": "(근로자) 주    소 : 경기도 수원시 영통구 반달로 7", "at_para": 30},
    "성    명 :                   (서명)": {
        "text": "성    명 : 이서준 (서명)", "at_para": 30},
}

#: The same map with every scope stripped — the shape `hr_flow.md` used to
#: recommend, kept as a fixture because it is the thing being refused.
UNSCOPED_FILL_MAP = {key: value["text"] for key, value in FILL_MAP.items()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_form(slug: str) -> Path:
    path = _CORPUS / "converted" / f"{slug}.hwpx"
    if not path.is_file():
        pytest.skip(f"blank-form corpus is not available: {path}")
    return path


def raw_text(slug: str) -> str:
    """Every seat's text, as written — for asserting what a form does NOT have."""
    return ch.haystack(ch.document_model(corpus_form(slug)))


def raw_text_of(path) -> str:
    """The same view for a produced artifact rather than a corpus slug."""
    return ch.haystack(ch.document_model(path))


@pytest.fixture()
def blank_2025(tmp_path):
    """A working COPY of the 2025 pack (originals are never edited in place)."""
    source = corpus_form(HR_2025)
    target = tmp_path / source.name
    shutil.copy2(source, target)
    return target


class TestBlankCorpusForms:
    def test_the_pair_is_what_the_manifest_says_it_is(self):
        manifest = json.loads(
            (_CORPUS / "manifest.json").read_text(encoding="utf-8"))
        slugs = {row["slug"] for row in manifest["documents"]
                 if row.get("family") == "hr"}
        assert set(HR_FORMS) == slugs, (
            "the hr family in the corpus manifest changed — this module's rules "
            "were verified against exactly these two forms")

    @pytest.mark.parametrize("slug", HR_FORMS)
    def test_blank_form_passes_and_reports_the_unfilled_shape(self, slug):
        form = corpus_form(slug)
        before = _sha256(form)
        verdict, code = ch.check(form)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["marked_slots"] == 0
        assert verdict["document"]["party_seats_filled"] == 0
        assert verdict["document"]["unfilled_date_seats"] >= 1
        assert verdict["counts"]["seats"] >= 1
        reasons = {row["rule"]: row["reason"] for row in verdict["skipped"]}
        assert reasons["seat_unfilled"] == "document_state_blank"
        assert _sha256(form) == before, "the checker must not touch its input"

    @pytest.mark.parametrize("slug", HR_FORMS)
    def test_blank_form_under_a_baseline_of_itself_decides_everything(self,
                                                                     slug):
        form = corpus_form(slug)
        verdict, code = ch.check(form, baseline=form)
        assert code == 0, verdict["hard"]
        assert verdict["warn"] == []
        assert verdict["document"]["paragraphs_changed"] == 0
        # only the state-gated rule is left undecided
        assert [row["rule"] for row in verdict["skipped"]] == ["seat_unfilled"]

    @pytest.mark.parametrize("slug", HR_FORMS)
    def test_every_form_carries_all_seven_seat_families(self, slug):
        verdict, _code = ch.check(corpus_form(slug))
        assert set(verdict["document"]["families"]) == {
            "contract", "clause", "party", "statute", "signature", "slot",
            "identity"}

    @pytest.mark.parametrize("slug", HR_FORMS)
    def test_no_blank_form_contains_a_personal_number(self, slug):
        """The corpus privacy ruling says these are blank templates; both privacy
        rules agree, and that is what makes 'invented' meaningful."""
        vocabulary = ch.load_vocabulary()
        model = ch.document_model(corpus_form(slug))
        assert not [value for _at, text in ch.iter_seats(model)
                    for value in ch._findall_raw(vocabulary["rrn_re"], text)]
        long_runs = [value for _at, text in ch.iter_seats(model)
                     for value in ch._findall_raw(
                         vocabulary["personal_number_re"], text)
                     if sum(char.isdigit() for char in value)
                     >= vocabulary["personal_number_min_digits"]]
        assert long_runs == []

    @pytest.mark.parametrize("slug", HR_FORMS)
    def test_no_blank_form_reads_as_having_a_selection_mark(self, slug):
        """Printed parentheticals are everywhere in this family; a selection mark
        is not. If the narrow class saw one, no form would classify as blank."""
        vocabulary = ch.load_vocabulary()
        model = ch.document_model(corpus_form(slug))
        slots = ch.slot_counts(model, vocabulary)
        assert slots["glyph_marks"] == 0
        assert slots["occupied"] >= 30, "the broad class must see the printed ones"
        assert slots["unmarked"] >= 1


class TestMeasuredVersionDrift:
    """Every number in skill/references/hr_flow.md §5, re-derived."""

    @staticmethod
    def measure(slug):
        vocabulary = ch.load_vocabulary()
        model = ch.document_model(corpus_form(slug))
        blocks = ch.clause_blocks(model, vocabulary)
        return {
            "banners": len(ch.contract_titles(model, vocabulary)),
            "blocks": len(blocks),
            "clauses": [len(block) for block in blocks],
            "numbers": [[row["number"] for row in block] for block in blocks],
            "signatures": ch.signature_marker_count(model, vocabulary),
            "articles": ch.statute_articles(model, vocabulary),
            "terms": ch.statute_terms(model, vocabulary),
            "slots": ch.slot_counts(model, vocabulary),
            "party_blocks": len(ch.party_blocks(model, vocabulary)),
            "identity": {label: len(seats) for label, seats
                         in ch.identity_seats(model, vocabulary).items()},
            "version": ch.template_version(model, vocabulary)["version"],
        }

    def test_banner_counts_match_and_the_sets_do_not(self):
        vocabulary = ch.load_vocabulary()
        titles = {slug: [row["title"] for row in ch.contract_titles(
            ch.document_model(corpus_form(slug)), vocabulary)]
            for slug in HR_FORMS}
        assert len(titles[HR_2013]) == 6
        assert len(titles[HR_2025]) == 6
        assert set(titles[HR_2013]) != set(titles[HR_2025])
        # 2025 splits the base contract in two; 2013 ships the bilingual sheet
        assert sum(1 for t in titles[HR_2025] if "기간의 정함이" in t) == 2
        assert any("Standard Labor Contract" in t for t in titles[HR_2013])
        assert not any("Standard Labor Contract" in t for t in titles[HR_2025])

    def test_clause_block_and_clause_counts(self):
        assert self.measure(HR_2013)["clauses"] == [9, 10, 9, 8]
        assert self.measure(HR_2025)["clauses"] == [11, 11, 12, 11, 10]

    def test_the_2013_short_time_sheet_is_legitimately_non_contiguous(self):
        """Its clause 7 is written mid-paragraph, so the PRISTINE form runs
        1,2,3,4,5,6,8,9. This is why clause_renumbered reads the inventory from
        the baseline instead of asserting 1..N."""
        numbers = self.measure(HR_2013)["numbers"]
        assert numbers[3] == [1, 2, 3, 4, 5, 6, 8, 9]
        assert all(seq == list(range(1, len(seq) + 1))
                   for seq in self.measure(HR_2025)["numbers"])

    def test_signature_marker_counts_are_equal_across_the_pair(self):
        assert self.measure(HR_2013)["signatures"] == 11
        assert self.measure(HR_2025)["signatures"] == 11

    def test_the_2025_revision_removed_every_rrn_seat(self):
        """The clearest privacy signal in the pair, and the reason the identity
        vocabulary carries both labels."""
        text13, text25 = raw_text(HR_2013), raw_text(HR_2025)
        assert ch._squeeze(text13).count("주민등록번호") == 3
        assert ch._squeeze(text25).count("주민등록번호") == 0
        assert ch._squeeze(text25).count("생년월일") == 2

    def test_the_account_and_allowance_wording_changed(self):
        text13, text25 = ch._squeeze(raw_text(HR_2013)), ch._squeeze(
            raw_text(HR_2025))
        assert text13.count("예금통장에입금") == 5 and text25.count(
            "예금통장에입금") == 0
        assert text25.count("계좌에입금") == 5 and text13.count("계좌에입금") == 0
        assert text13.count("기타급여(제수당등)") == 3
        assert text25.count("그밖의수당(약정수당)") == 5

    def test_article_citations_lost_je63jo_with_the_bilingual_sheet(self):
        assert self.measure(HR_2013)["articles"] == ["제17조", "제63조", "제67조"]
        assert self.measure(HR_2025)["articles"] == ["제17조", "제67조"]

    def test_both_forms_cite_the_labour_standards_act_and_only_2025_the_wider_term(
            self):
        assert "근로기준법" in self.measure(HR_2013)["terms"]
        assert "근로기준법" in self.measure(HR_2025)["terms"]
        assert "근로관계법령" not in self.measure(HR_2013)["terms"]
        assert self.measure(HR_2025)["terms"]["근로관계법령"] == 5

    def test_option_slots_exist_in_both_so_the_rule_holds_for_both(self):
        assert self.measure(HR_2013)["slots"]["total"] == 118
        assert self.measure(HR_2025)["slots"]["total"] == 102

    def test_each_revision_fingerprints_as_itself(self):
        assert self.measure(HR_2013)["version"] == "v2013"
        assert self.measure(HR_2025)["version"] == "v2025"

    def test_the_version_markers_are_strictly_disjoint_on_the_real_forms(self):
        """A marker that leaked into the other revision would make every
        document read as template_version_mixed."""
        vocabulary = ch.load_vocabulary()
        texts = {slug: ch._squeeze(raw_text(slug)) for slug in HR_FORMS}
        owner = {"v2013": HR_2013, "v2025": HR_2025}
        for name, slug in owner.items():
            other = HR_2025 if slug == HR_2013 else HR_2013
            for marker in ch._markers(vocabulary, name):
                key = ch._squeeze(marker)
                assert texts[slug].count(key) > 0, (name, marker)
                assert texts[other].count(key) == 0, (name, marker)

    def test_migrating_one_revision_onto_the_other_is_caught(self):
        verdict, code = ch.check(corpus_form(HR_2013),
                                 baseline=corpus_form(HR_2025))
        assert code == 3
        assert "template_version_changed" in {row["code"]
                                              for row in verdict["hard"]}


class TestDroppedRulePremises:
    """The candidate rules that the corpus does NOT support, pinned so nobody
    re-adds them on the strength of the family's reputation."""

    def test_the_underscore_blank_run_premise_does_not_hold(self):
        """'______' underline runs are not this family's fill target: 2013 has
        exactly ONE (the bilingual sheet's date line) and 2025 has none. The
        blanks are runs of SPACES; the underline is a charPr property."""
        assert len(re.findall(r"_{3,}", raw_text(HR_2013))) == 1
        assert re.findall(r"_{3,}", raw_text(HR_2025)) == []

    def test_no_paper_spec_footer_rule_can_be_stated_for_this_family(self):
        """민원 has a 210mm×297mm preservation rule. Here 2013 carries the footer
        once (on the bilingual page only) and 2025 not at all."""
        assert len(re.findall(r"210\s*(?:mm|㎜)", raw_text(HR_2013))) == 1
        assert re.findall(r"210\s*(?:mm|㎜)", raw_text(HR_2025)) == []

    @pytest.mark.parametrize("absent", [
        "별지", "귀하", "접수번호", "처리기간", "유의사항", "수수료", "제출서류"])
    def test_the_minwon_structures_are_absent_from_both_revisions(self, absent):
        """A 근로계약서 is a private two-party instrument: no 별지서식 header, no
        receiving office, no addressee, no printed guide blocks. That is the
        structural reason this module shares no rule with minwon beyond the
        privacy pattern."""
        for slug in HR_FORMS:
            assert absent not in ch._squeeze(raw_text(slug)), slug

    def test_the_seal_box_is_absent_from_both_revisions(self):
        """'직인' appears in both forms only inside '취직인허증'. There is no seal
        placement to preserve, so no seal rule was written."""
        for slug in HR_FORMS:
            squeezed = ch._squeeze(raw_text(slug))
            assert squeezed.count("직인") == squeezed.count("취직인허증")

    def test_no_form_declares_a_check_instruction_so_no_selection_rule_exists(
            self):
        """minwon's checkbox_selection_absent is anchored on a form declaring its
        own '[ ]에 √표를 합니다'. Neither revision declares anything of the kind,
        so unmarked slots are reported under seat_unfilled, never failed."""
        for slug in HR_FORMS:
            assert "√" not in raw_text(slug)


class TestUnscopedFillOverwritesTheSiblingContracts:
    """T41, both directions, on the real 2025 pack.

    Before: the `--map` path `hr_flow.md` recommended writes ONE employer's
    terms onto all five sibling contracts, and no offline gate catches it — the
    clause label survives as a prefix, so `clause_block_lost`,
    `clause_lost` and `clause_text_consumed` all pass on a corrupted document.
    After: the same map is refused, and the refusal says which sheets.
    """

    def test_the_documented_unscoped_map_corrupted_every_sibling_sheet(
            self, tmp_path, blank_2025):
        """Reproduced with the ambiguity check bypassed — this is what shipped."""
        out = tmp_path / "corrupt.hwpx"
        result = preedit.replace_placeholders(
            blank_2025, out,
            {key: {"text": value, "all_occurrences": True}
             for key, value in UNSCOPED_FILL_MAP.items()},
            on_zero_hits="error")
        # one employer's 근무장소 now printed on five contracts
        assert result["hits"]["2. 근 무 장 소 : "] == 5
        assert raw_text_of(out).count("경기도 화성시 동탄산단로 15") == 5
        # and every structural rule of this module still passes on it
        verdict, code = ch.check(out, baseline=blank_2025)
        assert code == 0, verdict["hard"]
        assert verdict["hard"] == []

    def test_the_unscoped_map_is_now_refused_and_names_the_sheets(
            self, tmp_path, blank_2025):
        out = tmp_path / "refused.hwpx"
        with pytest.raises(preedit.AmbiguousReplaceKeyError) as excinfo:
            preedit.replace_placeholders(blank_2025, out, UNSCOPED_FILL_MAP,
                                         on_zero_hits="error")
        exc = excinfo.value
        assert exc.exit_code == 2
        assert not out.exists()
        # every one of the eleven documented keys is ambiguous on this pack
        assert len(exc.keys) == len(UNSCOPED_FILL_MAP)
        row = next(r for r in exc.keys if r["key"] == "2. 근 무 장 소 : ")
        assert [o["at_para"] for o in row["occurrences"]] == [4, 35, 67, 130,
                                                             163]
        # The immediate previous paragraph is clause 1 on every sheet, so it
        # cannot distinguish them. Recent context must carry the variant title.
        assert row["occurrences"][0]["preceded_by"].startswith("1. 근로개시일")
        assert _SHEET_1 in row["occurrences"][0]["context_before"]
        assert _SHEET_1 in str(exc)           # message stays actionable too

    def test_the_scoped_map_touches_one_sheet_only(self, tmp_path, blank_2025):
        out = tmp_path / "scoped.hwpx"
        result = preedit.replace_placeholders(blank_2025, out, FILL_MAP,
                                             on_zero_hits="error")
        assert result["hits"]["2. 근 무 장 소 : "] == 1
        assert result["occurrences"]["2. 근 무 장 소 : "] == 5
        text = raw_text_of(out)
        assert text.count("경기도 화성시 동탄산단로 15") == 1
        # the other four sheets still print the blank clause skeleton
        assert text.count("근 무 장 소") == 5


class TestSyntheticallyFilledCorpusForm:
    @pytest.fixture()
    def filled(self, tmp_path, blank_2025):
        out = tmp_path / "filled.hwpx"
        result = preedit.replace_placeholders(blank_2025, out, FILL_MAP,
                                              on_zero_hits="error")
        assert result["ok"] and all(result["hits"].values()), result["hits"]
        return out

    @pytest.fixture()
    def fill_map_file(self, tmp_path):
        path = tmp_path / "fill.json"
        path.write_text(json.dumps(FILL_MAP, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_filled_copy_passes_every_rule(self, filled, blank_2025,
                                           fill_map_file):
        verdict, code = ch.check(filled, baseline=blank_2025,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert verdict["hard"] == []
        # unfilled seats remain in the sheets the prompt did not ask for, and
        # that is a REPORT, not a failure
        assert [row["code"] for row in verdict["warn"]] == ["seat_unfilled"]

    def test_a_baseline_leaves_nothing_undecided_on_the_real_form(
            self, filled, blank_2025):
        without, _code = ch.check(filled)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) == 12, sorted(undecided)
        with_baseline, _code = ch.check(filled, baseline=blank_2025)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_the_fill_left_the_identity_seats_empty(self, filled, blank_2025,
                                                    fill_map_file):
        """FILL_MAP supplies no 생년월일 and the checker is content: an empty
        identity seat is the correct output, not a finding."""
        verdict, _code = ch.check(filled, baseline=blank_2025,
                                  fill_map=fill_map_file)
        assert "identity_seat_autofilled" not in {row["code"]
                                                  for row in verdict["hard"]}
        assert any(row.get("seat") == "rrn"
                   and row["state"] == "none_undeclared"
                   for row in verdict["seats"])

    def test_the_clause_skeleton_and_the_citations_survived(self, filled,
                                                            blank_2025):
        verdict, _code = ch.check(filled, baseline=blank_2025)
        blocks = [row for row in verdict["seats"]
                  if row.get("seat") == "clause_block"]
        assert len(blocks) == 5
        assert all(row["state"] == "intact" for row in blocks)
        statute = next(row for row in verdict["seats"]
                       if row.get("seat") == "statute")
        assert statute["state"] == "verbatim"
        assert statute["articles"] == ["제17조", "제67조"]

    def test_the_fill_kept_every_variant_and_both_party_blocks(self, filled,
                                                               blank_2025):
        verdict, _code = ch.check(filled, baseline=blank_2025)
        assert len({row["title"] for row in verdict["seats"]
                    if row.get("seat") == "contract_variant"}) == 6
        assert any(row.get("seat") == "party_pair"
                   and row["state"] == "both_filled"
                   for row in verdict["seats"])

    def test_marking_and_writing_kept_the_slot_count(self, filled, blank_2025):
        vocabulary = ch.load_vocabulary()
        before = ch.slot_counts(ch.document_model(blank_2025), vocabulary)
        after = ch.slot_counts(ch.document_model(filled), vocabulary)
        assert after["total"] >= before["total"]

    @pytest.mark.parametrize("victim,expected", [
        ("  - 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함",
         "clause_text_consumed"),
        ("(근로기준법 제17조 이행)", "statute_reference_lost"),
        ("11. 그 밖의 사항", "clause_lost"),
    ])
    def test_still_catches_a_deletion_in_the_real_form(self, tmp_path,
                                                       blank_2025, victim,
                                                       expected):
        broken = tmp_path / "broken.hwpx"
        # deleting the clause from EVERY sheet is the damage under test, so it
        # is declared as such rather than happening by default (T41)
        result = preedit.replace_placeholders(
            blank_2025, broken,
            {victim: {"text": " ", "all_occurrences": True}},
            on_zero_hits="error")
        assert result["hits"][victim] >= 1
        verdict, code = ch.check(broken, baseline=blank_2025)
        assert code == 3
        assert expected in {row["code"] for row in verdict["hard"]}

    def test_still_catches_an_invented_account_number_in_the_real_form(
            self, tmp_path, blank_2025):
        broken = tmp_path / "broken.hwpx"
        preedit.replace_placeholders(
            blank_2025, broken,
            {"(근로자) 주    소 :": {
                "text": "(근로자) 계좌 : 110-234-567890 주    소 :",
                "at_para": 30}},
            on_zero_hits="error")
        verdict, code = ch.check(broken)
        assert code == 3
        assert "personal_number_invented" in {row["code"]
                                              for row in verdict["hard"]}

    def test_the_corpus_originals_are_byte_identical_afterwards(self):
        manifest = json.loads(
            (_CORPUS / "manifest.json").read_text(encoding="utf-8"))
        pinned = {row["path"]: row["sha256"] for row in manifest["documents"]
                  if row.get("family") == "hr" and row.get("sha256")}
        assert pinned
        for relative, digest in pinned.items():
            path = _CORPUS / relative
            if not path.is_file():
                pytest.skip(f"corpus member absent: {relative}")
            assert _sha256(path) == digest, relative
