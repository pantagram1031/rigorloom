'''Synthetic tests for the deterministic Stage 6 saeteuk consistency check.'''
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'pipeline' / 'scripts' / 'check_saeteuk.py'
_spec = importlib.util.spec_from_file_location('check_saeteuk', SCRIPT)
check_saeteuk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_saeteuk)
sys.path.insert(0, str(SCRIPT.parent))
import submission_preflight  # noqa: E402


def _write_workspace(tmp_path: Path, body: str | None, saeteuk: str | None) -> Path:
    workspace = tmp_path / 'report-synthetic'
    if body is not None:
        bundle = workspace / 'bundle'
        bundle.mkdir(parents=True)
        (bundle / 'content.md').write_text(body, encoding='utf-8')
    if saeteuk is not None:
        target = workspace / '_saeteuk'
        target.mkdir(parents=True)
        (target / 'record.txt').write_text(saeteuk, encoding='utf-8')
    return workspace


def _codes(verdict: dict, severity: str) -> set[str]:
    return {finding['code'] for finding in verdict[severity]}


def test_no_saeteuk_is_noop_pass_with_zero_findings(tmp_path):
    workspace = _write_workspace(tmp_path, body=None, saeteuk=None)

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['ok'] is True
    assert verdict['verdict'] == 'pass'
    assert verdict['hard'] == []
    assert verdict['warn'] == []
    assert verdict['counts'] == {'hard': 0, 'warn': 0}
    assert verdict['saeteuk_files'] == []


def test_markdown_saeteuk_artifact_is_discovered(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Latency = 20 ms.\n',
        saeteuk=None,
    )
    target = workspace / '_saeteuk'
    target.mkdir()
    (target / 'record.md').write_text('Latency = 10 ms.\n', encoding='utf-8')

    verdict, code = check_saeteuk.check(workspace)

    assert code == 3
    assert verdict['saeteuk_files'] == ['_saeteuk/record.md']
    assert _codes(verdict, 'hard') == {'saeteuk_number_contradiction'}


def test_existing_empty_local_saeteuk_warns_missing_and_ignores_parent(tmp_path):
    parent_artifact = tmp_path / '_saeteuk'
    parent_artifact.mkdir()
    (parent_artifact / 'other-report.txt').write_text(
        'Latency = 10 ms.\n', encoding='utf-8'
    )
    workspace = _write_workspace(
        tmp_path,
        body='Latency = 20 ms.\n',
        saeteuk=None,
    )
    (workspace / '_saeteuk').mkdir()

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert _codes(verdict, 'warn') == {'saeteuk_missing'}
    assert verdict['saeteuk_files'] == []


def test_parent_saeteuk_is_never_imported_without_local_directory(tmp_path):
    parent_artifact = tmp_path / '_saeteuk'
    parent_artifact.mkdir()
    (parent_artifact / 'report-a.txt').write_text(
        'Temperature = 100 C.\n', encoding='utf-8'
    )
    workspace = _write_workspace(
        tmp_path,
        body='Temperature = 20 C.\n',
        saeteuk=None,
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert verdict['warn'] == []
    assert verdict['saeteuk_files'] == []


def test_matching_numbers_pass(tmp_path):
    subject = 'Oscillation ' + 'amplitude'
    workspace = _write_workspace(
        tmp_path,
        body=f'# Result\n{subject} = 12.0 cm.\n',
        saeteuk=f'{subject} = 12.0 cm.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert verdict['warn'] == []
    assert verdict['checked_numbers'] == 1


def test_same_context_numeric_contradiction_is_hard(tmp_path):
    subject = 'Oscillation ' + 'amplitude'
    workspace = _write_workspace(
        tmp_path,
        body=f'# Result\n{subject} = 15.0 cm.\n',
        saeteuk=f'{subject} = 12.0 cm.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 3
    assert verdict['ok'] is False
    assert _codes(verdict, 'hard') == {'saeteuk_number_contradiction'}
    finding = verdict['hard'][0]
    assert finding['subject'] == subject.casefold()
    assert finding['saeteuk_value'] == 12.0
    assert finding['body_value'] == 15.0


def test_generic_quantity_subject_contradiction_is_warn(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Temperature = 15.0 °C.\n',
        saeteuk='Temperature = 12.0 °C.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['ok'] is True
    assert verdict['hard'] == []
    assert _codes(verdict, 'warn') == {'saeteuk_possible_contradiction'}


def test_specific_quantity_subject_contradiction_stays_hard(tmp_path):
    subject = 'Sample A temperature'
    workspace = _write_workspace(
        tmp_path,
        body=f'{subject} = 15.0 °C.\n',
        saeteuk=f'{subject} = 12.0 °C.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 3
    assert _codes(verdict, 'hard') == {'saeteuk_number_contradiction'}
    assert verdict['warn'] == []


def test_repeated_identical_binding_still_detects_contradiction(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Latency = 20 ms.\n',
        saeteuk='Latency = 10 ms.\nLatency = 10 ms.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 3
    assert _codes(verdict, 'hard') == {'saeteuk_number_contradiction'}


def test_multiple_distinct_values_on_either_side_are_ambiguous_warn(tmp_path):
    cases = (
        (
            'Latency = 10 ms.\n',
            'Latency = 10 ms.\nLatency = 11 ms.\n',
        ),
        (
            'Latency = 10 ms.\nLatency = 11 ms.\n',
            'Latency = 10 ms.\n',
        ),
    )
    for index, (body, saeteuk) in enumerate(cases):
        case_root = tmp_path / f'case-{index}'
        case_root.mkdir()
        workspace = _write_workspace(case_root, body=body, saeteuk=saeteuk)

        verdict, code = check_saeteuk.check(workspace)

        assert code == 0
        assert verdict['hard'] == []
        assert 'saeteuk_ambiguous' in _codes(verdict, 'warn')


def test_same_value_and_unit_with_different_subject_is_unsupported(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Success rate = 5%.\n',
        saeteuk='Failure rate = 5%.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert 'saeteuk_unsupported' in _codes(verdict, 'warn')


def test_precision_aware_absolute_tolerance_accepts_rounding_near_zero(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Latency = 0.004 ms.\n',
        saeteuk='Latency = 0 ms.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert verdict['warn'] == []


def test_case_sensitive_si_prefixes_are_scaled_before_comparison(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Voltage = 1000000000 mV.\n',
        saeteuk='Voltage = 1 MV.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert verdict['warn'] == []


def test_different_case_sensitive_base_symbols_never_hard_compare(tmp_path):
    workspace = _write_workspace(
        tmp_path,
        body='Voltage = 1 MA.\n',
        saeteuk='Voltage = 1 MV.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert 'saeteuk_unsupported' in _codes(verdict, 'warn')


def test_non_finite_numbers_are_dropped_and_cli_emits_strict_json(tmp_path):
    overflow = '1e' + '309'
    workspace = _write_workspace(
        tmp_path,
        body='X = 1e308 ms.\n',
        saeteuk=f'X = {overflow} ms.\n',
    )

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(workspace)],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'Infinity' not in proc.stdout
    assert 'NaN' not in proc.stdout
    json.loads(proc.stdout)


def test_unsupported_named_claim_is_warn(tmp_path):
    named_place = 'Aur' + 'ora Observatory'
    workspace = _write_workspace(
        tmp_path,
        body='# Discussion\nThe apparatus was calibrated before each run.\n',
        saeteuk=f'Measurements were compared with {named_place}.\n',
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict['hard'] == []
    assert _codes(verdict, 'warn') == {'saeteuk_unsupported'}
    assert verdict['warn'][0]['kind'] == 'entity'
    assert verdict['warn'][0]['claim'] == named_place


def test_stage_6_gate_composes_saeteuk_checker(tmp_path):
    stages = (ROOT / 'pipeline' / 'references' / 'stages.yaml').read_text(
        encoding='utf-8'
    )
    preflight = (
        ROOT / 'pipeline' / 'scripts' / 'submission_preflight.py'
    ).read_text(encoding='utf-8')
    playbook = (
        ROOT / 'pipeline' / 'references' / 'playbooks' / 'stage-6.md'
    ).read_text(encoding='utf-8')

    assert '{id: ' + chr(34) + '6' + chr(34) in stages
    assert '{PIPELINE_SCRIPTS}/submission_preflight.py' in stages
    assert 'check_saeteuk.check(ws)' in preflight
    assert 'check_saeteuk' in playbook
    assert 'exit 2' in playbook
    assert 'UTF-8' in playbook
    parent_fallback = 'parent ' + chr(96) + '_saeteuk/' + chr(96) + ' fallback'
    assert parent_fallback not in playbook

    subject = 'Oscillation ' + 'amplitude'
    workspace = _write_workspace(
        tmp_path,
        body=f'{subject} = 15.0 cm.\n',
        saeteuk=f'{subject} = 12.0 cm.\n',
    )
    output = workspace / 'output'
    output.mkdir()
    (workspace / 'PIPELINE.md').write_text(
        'canonical_output: output/submission.hwpx\n', encoding='utf-8'
    )
    (workspace / 'request.yaml').write_text(
        'output_filename: submission.hwpx\nrequired_fields: []\n',
        encoding='utf-8',
    )
    (output / 'verdict_v06.json').write_text(
        json.dumps({'proof_grade': 'advisory'}), encoding='utf-8'
    )
    with zipfile.ZipFile(output / 'submission.hwpx', 'w') as archive:
        archive.writestr('Contents/section0.xml', '<doc><p>synthetic</p></doc>')

    verdict, code = submission_preflight.check(workspace)

    assert code == 3
    assert any(
        item.get('source') == 'check_saeteuk'
        and item.get('code') == 'saeteuk_number_contradiction'
        for item in verdict['hard']
    )
