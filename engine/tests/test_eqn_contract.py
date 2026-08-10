"""T92 equation-language contract regressions.

These tests deliberately exercise the boundary between LaTeX conversion and
the HwpEqn script accepted by the backends.  A failed conversion must remain
rejected; it must never degrade into a different, apparently valid script.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_report as br  # noqa: E402
import com_backend as cb  # noqa: E402
import xml_backend as xb  # noqa: E402
from eqn import (  # noqa: E402
    HWPEQN_CONTRACT,
    HWPEQN_MAX_BYTES,
    HWPEQN_MAX_DEPTH,
    LATEX_MAX_DEPTH,
    base_pt_to_hwpunit,
    count_hweqn_identifier,
    hwpeqn_sanity_check,
    latex_to_hwpeqn,
    validate_equation_operation,
)


def _converted_is_rejected(source):
    script, _warnings = latex_to_hwpeqn(source)
    ok, _reason = hwpeqn_sanity_check(script)
    assert not ok, (source, script)


def test_contract_is_versioned():
    assert HWPEQN_CONTRACT == "rigorloom/hwpeqn/v1"


@pytest.mark.parametrize("source", [r"\foo{x}", r"\begin{gathered}x\end{gathered}"])
def test_unknown_command_and_unsupported_environment_do_not_degrade(source):
    _converted_is_rejected(source)


@pytest.mark.parametrize("source", [
    r"\pmfoo", r"\alphafoo", r"\sinus{x}", r"\infinite{x}",
    r"\rightarrowtail{x}", r"\logarithm{x}",
])
def test_command_prefix_spoof_is_not_partially_replaced(source):
    script, _warnings = latex_to_hwpeqn(source)
    assert "\\" in script
    ok, _reason = hwpeqn_sanity_check(script)
    assert not ok


@pytest.mark.parametrize("source", [r"\frac{x}", r"\sqrt", r"\vec"])
def test_required_latex_arguments_are_closed(source):
    _converted_is_rejected(source)


@pytest.mark.parametrize("source", [r"a \\ b", "x={y", '"unclosed'])
def test_malformed_script_is_rejected(source):
    ok, _reason = hwpeqn_sanity_check(source)
    assert not ok


def test_xml_backend_uses_same_equation_contract():
    assert not xb.balanced_equation_script(r"\foo{x}")
    assert not xb.balanced_equation_script('"unclosed')


@pytest.mark.parametrize("script", [None, True, False, "", "   ", "{}", '""', '" "', "over"])
def test_lexical_vacuous_inputs_are_rejected(script):
    ok, _reason = hwpeqn_sanity_check(script)
    assert not ok


@pytest.mark.parametrize("script", ["a]", "a}", "a\x00b", "a\nb", "a\tb"])
def test_lexical_envelope_rejects_controls_and_unmatched_closers(script):
    ok, _reason = hwpeqn_sanity_check(script)
    assert not ok


def test_lexical_envelope_is_bounded():
    ok, _reason = hwpeqn_sanity_check("x" * (HWPEQN_MAX_BYTES + 1))
    assert not ok
    nested = "{" * (HWPEQN_MAX_DEPTH + 1) + "x" + "}" * (HWPEQN_MAX_DEPTH + 1)
    ok, _reason = hwpeqn_sanity_check(nested)
    assert not ok


def test_latex_depth_budget_tracks_max_nesting_not_total_flat_groups():
    flat = "".join("{x}" for _ in range(LATEX_MAX_DEPTH + 1))
    script, warnings = latex_to_hwpeqn(flat)
    assert warnings == []
    assert hwpeqn_sanity_check(script)[0]
    nested = "{" * (LATEX_MAX_DEPTH + 1) + "x" + "}" * (LATEX_MAX_DEPTH + 1)
    script, warnings = latex_to_hwpeqn(nested)
    assert warnings == ["too_deep"]
    assert not hwpeqn_sanity_check(script)[0]


def test_latex_depth_scan_handles_text_and_escaped_delimiters():
    text = r"\text{" + ("{" * (LATEX_MAX_DEPTH + 1)) + "x" + (
        "}" * (LATEX_MAX_DEPTH + 1)) + "}"
    script, warnings = latex_to_hwpeqn(text)
    assert warnings == []
    assert hwpeqn_sanity_check(script)[0]
    script, warnings = latex_to_hwpeqn(r"\{")
    assert isinstance(script, str)
    assert not validate_equation_operation(
        {"op": "insert_equation", "latex": r"\{"})[2]


def test_raw_words_and_quoted_literals_are_not_substring_blacklisted():
    for script in ("mathbb", "mathbbq", '"mathbb"', "clover", "overx"):
        ok, reason = hwpeqn_sanity_check(script)
        assert ok, (script, reason)


@pytest.mark.parametrize("token", [
    "aleph", "angstrom", "att", "base", "benzene", "centigrade",
    "dagger", "ddagger", "diamond", "fahrenheit", "hleft", "hund",
    "identical", "imag", "image", "imath", "iso", "jmath", "laplace",
    "liter", "lll", "lslant", "mho", "models", "msangle", "prec",
    "reimage", "rslant", "rtangle", "sangle", "succ", "thou", "top",
    "triangle", "triangled", "varsigma", "vdash", "well", "wp", "xor",
])
def test_latex_origin_refuses_additional_native_identifier_vocabulary(token):
    for raw in (token, token.upper(), token.title()):
        script, warnings = latex_to_hwpeqn(raw)
        assert warnings, (raw, script)
        _script, _warnings, ok, _reason = validate_equation_operation(
            {"op": "insert_equation", "latex": raw})
        assert not ok


def test_direct_hwpeqn_keeps_native_punctuation_surface():
    for script in ("x#y", "x`y", '"x#y"'):
        _script, _warnings, ok, reason = validate_equation_operation(
            {"op": "insert_equation", "hwpeqn": script})
        assert ok, (script, reason)


def test_latex_command_origin_may_generate_hweqn_backtick_spacing():
    script, warnings = latex_to_hwpeqn(r"x\,y")
    assert warnings == []
    assert "`" in script
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [r"x\to y", r"x\pm y", r"x\neq y",
                                     r"x\equiv y"])
def test_latex_operator_commands_are_allowed_when_origin_is_explicit(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings == [], (source, script)
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source, expected", [
    (r"\propto", "propto"),
    (r"\odot", "odot"),
    (r"\oplus", "oplus"),
    (r"\otimes", "otimes"),
])
def test_latex_operator_outputs_use_ascii_native_tokens(source, expected):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings == []
    assert expected in script
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [r"\nabla", r"\cup"])
def test_unproven_latex_operator_mappings_are_terminal_refusals(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings
    assert "\\" in script
    assert not hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [
    "alpha", "sin x", "int x dx", "x over y", "left(x right)",
    "sqrt x", "sum x", "in x", "exists x", "lim x", "frac{x}{y}",
    "rm x", "it x", "bold x", "size x", "color x", "pile x",
    "lpile x", "cpile x", "rpile x", "atop x", "choose x",
])
def test_latex_bare_hweqn_reserved_tokens_are_not_origin_ambiguous(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings, (source, script)
    _script, _warnings, ok, _reason = validate_equation_operation(
        {"op": "insert_equation", "latex": source})
    assert not ok


@pytest.mark.parametrize("word", [
    "acute", "grave", "check", "arch", "dyad", "det", "gcd", "mod",
    "cosec", "lg", "Lim", "Exp", "arc", "coth", "ODINT", "OTINT",
    "UNION", "INTER", "BIGG", "BINOM", "NOT", "REL", "BUILDREL",
    "SMALL", "SMALLUNION", "SMALLINTER", "SUB", "SUP", "COL", "LCOL",
    "RCOL", "rmbold", "if", "for", "and", "or", "hom", "ker", "deg",
    "arg", "dim", "Pr",
    "COPROD", "SQCAP", "SQCUP", "OMINUS", "OSLASH", "VEE", "WEDGE",
    "OWNS", "UPLUS", "DIVIDE", "BIGCIRC", "DOTEQ", "CONG", "ASYMP",
    "DSUM", "LNOT", "hookleft", "hookright", "udarrow", "UDARROW", "VERT",
    "SQSUBSET", "SQSUPSET", "SQSUBSETEQ", "SQSUPSETEQ", "SQEQUAL",
])
def test_latex_reserved_vocabulary_is_ascii_casefolded(word):
    for source in (word, word.upper(), word.title()):
        script, warnings = latex_to_hwpeqn(source)
        assert warnings, (source, script)
        _script, _warnings, ok, _reason = validate_equation_operation(
            {"op": "insert_equation", "latex": source})
        assert not ok


def test_latex_ordinary_variable_words_remain_available():
    for source in ("mv", "dx", "K"):
        script, warnings = latex_to_hwpeqn(source)
        assert warnings == [], (source, warnings, script)
        _script, _warnings, ok, reason = validate_equation_operation(
            {"op": "insert_equation", "latex": source})
        assert ok, (source, reason)


@pytest.mark.parametrize("source", [
    r"\alpha", r"\sin x", r"\int x\,dx", r"\frac{x}{y}",
])
def test_latex_commands_are_allowed_when_their_origin_is_explicit(source):
    script, warnings = latex_to_hwpeqn(source)
    assert not warnings, (source, warnings, script)
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [
    "x%SECRET", "x#y", "x&y", "x`y", 'x"y', "x'", "x''", "x~y",
    "x->y", "x<-y", "x<->y", "x=>y", "x<=>y", "x+-y", "x-+y",
    "x<=y", "x>=y", "x!=y", "x==y",
])
def test_latex_origin_rejects_raw_hweqn_punctuation(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings, (source, script)
    _script, _warnings, ok, _reason = validate_equation_operation(
        {"op": "insert_equation", "latex": source})
    assert not ok


def test_latex_matrix_ampersand_is_allowed_only_in_supported_environment():
    script, warnings = latex_to_hwpeqn(r"\begin{pmatrix}a&b\\c&d\end{pmatrix}")
    assert not warnings, (warnings, script)
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [
    r"\begin{pmatrix}a&b\\c&d&e\end{pmatrix}",
    r"\begin{pmatrix}a&b\\c\end{pmatrix}",
    r"\begin{pmatrix}a&&b\\c&&d\end{pmatrix}",
    r"\begin{cases}x&1\\y\end{cases}",
    r"\begin{pmatrix}a&\begin{bmatrix}b&c\end{bmatrix}\\d&e\end{pmatrix}",
])
def test_latex_matrix_subset_refuses_nested_or_nonrectangular_shapes(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings, (source, script)
    _script, _warnings, ok, _reason = validate_equation_operation(
        {"op": "insert_equation", "latex": source})
    assert not ok


def test_latex_text_keeps_reserved_word_opaque():
    script, warnings = latex_to_hwpeqn(r"\text{alpha sin}")
    assert not warnings, (warnings, script)
    assert script == '"alpha sin"'
    assert hwpeqn_sanity_check(script)[0]


def test_latex_text_keeps_apostrophe_and_tilde_opaque():
    script, warnings = latex_to_hwpeqn(r"\text{it's ~ spacing}")
    assert warnings == []
    assert script == '"it\'s ~ spacing"'
    assert hwpeqn_sanity_check(script)[0]


def test_text_literals_are_opaque_to_structural_normalization():
    script, warnings = latex_to_hwpeqn(r"\text{x^2 and a _ b}")
    assert script == '"x^2 and a _ b"'
    assert warnings == []


def test_text_literal_quote_or_latex_is_refused_without_raw_warning():
    for source in (r"\text{a\"b}", r"\text{\sin x}"):
        script, warnings = latex_to_hwpeqn(source)
        assert warnings
        assert "\\" not in "".join(warnings)
        ok, _reason = hwpeqn_sanity_check(script)
        assert not ok


@pytest.mark.parametrize("source", ["α + β", "한글", "日本語"])
def test_non_ascii_identifier_input_is_bounded_without_scanner_crash(source):
    script, warnings = latex_to_hwpeqn(source)
    assert isinstance(script, str)
    assert all("\\" not in warning for warning in warnings)


@pytest.mark.parametrize("run_length", [1, 3, 4, 5, 6])
def test_matrix_row_separator_requires_exactly_two_backslashes(run_length):
    source = "\\begin{pmatrix}a&b%s c&d\\end{pmatrix}" % ("\\" * run_length)
    script, warnings = latex_to_hwpeqn(source)
    ok, _reason = hwpeqn_sanity_check(script)
    assert not ok


def test_matrix_row_separator_exactly_two_backslashes_is_allowed():
    source = r"\begin{pmatrix}a&b\\c&d\end{pmatrix}"
    script, warnings = latex_to_hwpeqn(source)
    assert "#" in script
    assert warnings == []
    assert hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", [
    r"\begin{pmatrix}{a\\b}&c\\d&e\end{pmatrix}",
    r"\begin{pmatrix}\text{a\\b}&c\\d&e\end{pmatrix}",
    r"\begin{pmatrix}\text{a&b}&c\\d&e\end{pmatrix}",
    r"\begin{pmatrix}\sqrt[a&b]{x}&c\\d&e\end{pmatrix}",
    r"\begin{pmatrix}[a&b]&c\\d&e\end{pmatrix}",
])
def test_matrix_separators_and_ampersands_must_be_top_level(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings, (source, script)
    assert not hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", ["\x00", "\x01Q0\x02", "\x00PROTECTED0\x00"])
def test_control_and_internal_sentinel_collisions_are_refused(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings
    assert not hwpeqn_sanity_check(script)[0]


@pytest.mark.parametrize("source", ["^\\", "_\\", "x^\\", "x_\\"])
def test_trailing_backslash_script_atoms_are_bounded_refusals(source):
    script, warnings = latex_to_hwpeqn(source)
    assert isinstance(script, str)
    assert warnings or not hwpeqn_sanity_check(script)[0]
    assert not hwpeqn_sanity_check(script)[0]


def test_build_report_requires_exactly_one_equation_source():
    base = {"anchor": "Anchor", "blocks": [{"kind": "eq", "display": False}]}
    for block in (
        {**base, "blocks": [{"kind": "eq", "display": False,
                              "latex": None, "hwpeqn": None}]},
        {**base, "blocks": [{"kind": "eq", "display": False,
                              "latex": "x", "hwpeqn": "x"}]},
    ):
        with pytest.raises(SystemExit):
            br.build_ops({}, [block], ".")


@pytest.mark.parametrize("op", [
    {"op": "insert_equation"},
    {"op": "insert_equation", "latex": "x", "hwpeqn": "x"},
    {"op": "insert_equation", "hwpeqn": r"\foo{x}"},
    {"op": "edit_equation", "index": -1, "hwpeqn": "x"},
    {"op": "edit_equation", "index": True, "hwpeqn": "x"},
    {"op": "edit_equation", "index": "0", "hwpeqn": "x"},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 0},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 0.9},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 0.99},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 0.005},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 1.05},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": None},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": float("nan")},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": 10 ** 10000},
    {"op": "insert_equation", "hwpeqn": "x", "base_pt": True},
    {"op": "insert_equation", "hwpeqn": "x", "display": 1},
    {"op": "insert_equation", "hwpeqn": "x", "font": "OtherFont"},
    {"op": "insert_equation", "hwpeqn": "x", "font": 1},
])
def test_com_rejects_invalid_equation_before_document_open(op):
    with pytest.raises(SystemExit):
        cb._validate_ops([op])


def test_xml_and_com_share_latex_only_acceptance_surface():
    op = {"op": "insert_equation", "latex": r"\frac{1}{2}"}
    assert cb._validate_ops([op]) == [op]
    script, _warnings, ok, _reason = __import__("eqn").resolve_equation_input(op)
    assert ok and script and xb.balanced_equation_script(script)


def test_equation_operation_validator_is_shared_and_closed():
    for op in ({"op": "insert_equation", "latex": r"\frac{1}{2}"},
               {"op": "insert_equation", "hwpeqn": "x"}):
        _script, _warnings, ok, reason = validate_equation_operation(op)
        assert ok, reason


@pytest.mark.parametrize("op", [
    {"op": "insert_equation", "hwpeqn": "x", "display": False,
     "font": "HancomEQN", "unexpected": 1},
    {"op": "edit_equation", "hwpeqn": "x", "index": 0,
     "font": "HancomEQN"},
])
def test_equation_operation_rejects_unknown_or_cross_operation_keys(op):
    _script, _warnings, ok, reason = validate_equation_operation(op)
    assert not ok
    assert reason == "unknown_key"


@pytest.mark.parametrize("value, expected", [
    (1.0, 100), (10.0, 1000), (100.0, 10000),
])
def test_base_pt_quantization_is_shared_decimal_half_up(value, expected):
    assert base_pt_to_hwpunit(value) == expected


@pytest.mark.parametrize("value", [0.9, 0.99, 0.005, 1.05, 10.005])
def test_base_pt_quantization_rejects_below_minimum_or_off_quantum(value):
    with pytest.raises(ValueError):
        base_pt_to_hwpunit(value)


@pytest.mark.parametrize("value", [100.001, 1000])
def test_base_pt_conservative_max_is_one_hundred_points(value):
    with pytest.raises(ValueError):
        base_pt_to_hwpunit(value)


def test_base_pt_missing_defaults_to_ten_points_but_explicit_null_refuses():
    assert base_pt_to_hwpunit() == 1000
    _script, _warnings, ok, reason = validate_equation_operation(
        {"op": "insert_equation", "hwpeqn": "x", "base_pt": None})
    assert not ok and reason == "base_pt"


def test_native_identifier_count_is_bounded_and_quote_aware():
    assert count_hweqn_identifier("clover leftover", "over") == 0
    assert count_hweqn_identifier("{x} over {y}", "over") == 1
    assert count_hweqn_identifier('"over" over', "over") == 1


def test_cheatsheet_uses_native_prime_token_not_raw_apostrophe():
    cheatsheet = (Path(ROOT) / "references" / "hwpeqn_cheatsheet.md").read_text(
        encoding="utf-8")
    assert "f^{prime}(x)" in cheatsheet
    assert "f'(x)" not in cheatsheet
    assert "`propto`" in cheatsheet


def test_cli_refuses_invalid_conversion_without_echoing_source_or_script():
    eqn_path = os.path.join(ROOT, "scripts", "eqn.py")
    result = subprocess.run(
        [sys.executable, eqn_path, r"\foo{SECRET_EQUATION}"],
        capture_output=True, text=True)
    assert result.returncode == 3
    assert "SECRET_EQUATION" not in result.stdout
    assert "\\foo" not in result.stdout


def test_cli_valid_conversion_is_successful():
    eqn_path = os.path.join(ROOT, "scripts", "eqn.py")
    result = subprocess.run(
        [sys.executable, eqn_path, r"\frac{1}{2}"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_cli_unicode_output_reconfigures_cp949_stdio_without_traceback():
    eqn_path = os.path.join(ROOT, "scripts", "eqn.py")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp949"
    result = subprocess.run(
        [sys.executable, eqn_path, r"\oplus"],
        capture_output=True, env=env)
    assert result.returncode == 0
    output = result.stdout.decode("utf-8")
    assert "traceback" not in output.lower()
    assert '"ok": true' in output
    assert '"oplus"' in output


def test_cli_usage_is_exit_two_and_privacy_safe():
    eqn_path = os.path.join(ROOT, "scripts", "eqn.py")
    result = subprocess.run([sys.executable, eqn_path],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert '"error": "usage"' in result.stdout
    assert '"hwpeqn":' not in result.stdout


def test_build_report_rejects_direct_hwpeqn_before_emitting_ops():
    sections = [{
        "anchor": "Anchor",
        "blocks": [{"kind": "eq", "display": False,
                    "latex": None, "hwpeqn": r"\foo{x}"}],
    }]
    with pytest.raises(SystemExit):
        br.build_ops({}, sections, ".")
