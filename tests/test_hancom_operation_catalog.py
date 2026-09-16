# -*- coding: utf-8 -*-
"""Deterministic test for Hancom operation catalog schema and invariants (M3).

Validates:
- Schema conformance and top-level commit pinning
- AST-extracted operation keys from preedit, COM, and XML backends without importing COM
- Absence of missing or extra operations
- Uniqueness of IDs
- Resolution of implementation paths and test nodes
- Evidence category bounds (cannot claim focused/native proof without tests)
- Separation of implemented operations from promised gaps
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Set

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SCHEMA_PATH = REPO_ROOT / "docs" / "hancom-operation-catalog.schema.json"
CATALOG_JSON_PATH = REPO_ROOT / "docs" / "hancom-operation-catalog.json"

EXPECTED_PRODUCT_COMMIT = "e53e99abc994cd5aa2780e5d184220dea8c03708"
EXPECTED_PLANNING_COMMIT = "609f834ce21e55f481604559f26a8d52aeeaf15f"

ALLOWED_EVIDENCE_CATEGORIES = {
    "source",
    "focused",
    "broad",
    "native_parity",
    "visual",
    "installed",
    "user",
}


def _extract_ast_keys(file_path: Path, var_name: str) -> Set[str]:
    """Extract string keys or elements from a named AST assignment without importing the module."""
    assert file_path.is_file(), f"Target source file not found: {file_path}"
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    for node in ast.walk(tree):
        val = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    val = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == var_name:
                val = node.value

        if val is not None:
            if isinstance(val, ast.Dict):
                return {
                    k.value if isinstance(k, ast.Constant) else k.s
                    for k in val.keys
                    if isinstance(k, (ast.Constant, ast.Str))
                }
            elif isinstance(val, ast.Set):
                return {
                    elt.value if isinstance(elt, ast.Constant) else elt.s
                    for elt in val.elts
                    if isinstance(elt, (ast.Constant, ast.Str))
                }
            elif isinstance(val, ast.Tuple):
                return {
                    elt.value if isinstance(elt, ast.Constant) else elt.s
                    for elt in val.elts
                    if isinstance(elt, (ast.Constant, ast.Str))
                }
            elif isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == "frozenset":
                if val.args and isinstance(val.args[0], ast.Set):
                    return {
                        elt.value if isinstance(elt, ast.Constant) else elt.s
                        for elt in val.args[0].elts
                        if isinstance(elt, (ast.Constant, ast.Str))
                    }
    return set()


def _get_ast_function_and_method_names(file_path: Path) -> Set[str]:
    """Return all function and method names defined in a python file."""
    assert file_path.is_file(), f"Target test file not found: {file_path}"
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    assert CATALOG_JSON_PATH.is_file(), f"Catalog file missing: {CATALOG_JSON_PATH}"
    data = json.loads(CATALOG_JSON_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Catalog root must be a JSON object"
    return data


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    assert CATALOG_SCHEMA_PATH.is_file(), f"Schema file missing: {CATALOG_SCHEMA_PATH}"
    data = json.loads(CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Schema root must be a JSON object"
    return data


def test_schema_file_is_valid_json_schema(schema):
    """Ensure the schema document itself defines a closed Draft 2020-12 schema."""
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.get("title") == "HancomOperationCatalog"
    assert schema.get("additionalProperties") is False
    assert "operations" in schema.get("required", [])
    assert "gaps" in schema.get("required", [])


def test_catalog_validates_against_json_schema(catalog, schema):
    """Validate catalog against schema using jsonschema if available, plus stdlib checks."""
    try:
        import jsonschema
        jsonschema.validate(instance=catalog, schema=schema)
    except ImportError:
        pass

    assert catalog["schema_version"] == "rigorloom/hancom-operation-catalog-v1"
    assert catalog["product_candidate_commit"] == EXPECTED_PRODUCT_COMMIT
    assert catalog["planning_contract_commit"] == EXPECTED_PLANNING_COMMIT
    assert isinstance(catalog["operations"], list)
    assert isinstance(catalog["gaps"], list)


def test_no_duplicate_ids(catalog):
    """Ensure all operation IDs and gap IDs are globally unique."""
    op_ids = [op["id"] for op in catalog["operations"]]
    assert len(op_ids) == len(set(op_ids)), f"Duplicate operation IDs found: {op_ids}"

    gap_ids = [gap["id"] for gap in catalog["gaps"]]
    assert len(gap_ids) == len(set(gap_ids)), f"Duplicate gap IDs found: {gap_ids}"

    intersection = set(op_ids) & set(gap_ids)
    assert not intersection, f"Overlap between operation and gap IDs: {intersection}"


def test_operation_keys_match_authoritative_ast_sources(catalog):
    """AST-extract authoritative operation keys from source without COM execution or import."""
    rt_plan_path = REPO_ROOT / "runtime" / "scripts" / "rt_plan.py"
    com_backend_path = REPO_ROOT / "engine" / "scripts" / "com_backend.py"
    xml_backend_path = REPO_ROOT / "engine" / "scripts" / "xml_backend.py"

    expected_preedit = _extract_ast_keys(rt_plan_path, "PREEDIT_OP_KINDS")
    expected_com = _extract_ast_keys(com_backend_path, "OPS")
    expected_xml = _extract_ast_keys(xml_backend_path, "SUPPORTED_OPS")

    assert len(expected_preedit) == 4, f"Unexpected preedit op count: {expected_preedit}"
    assert len(expected_com) == 24, f"Unexpected com op count: {expected_com}"  # page_numbers, set_header
    assert len(expected_xml) == 9, f"Unexpected xml op count: {expected_xml}"

    catalog_preedit = {
        op["operation_key"]
        for op in catalog["operations"]
        if op["backend"] == "preedit"
    }
    catalog_com = {
        op["operation_key"]
        for op in catalog["operations"]
        if op["backend"] == "com"
    }
    catalog_xml = {
        op["operation_key"]
        for op in catalog["operations"]
        if op["backend"] == "xml"
    }

    assert catalog_preedit == expected_preedit, (
        f"Preedit mismatch: missing={expected_preedit - catalog_preedit}, "
        f"extra={catalog_preedit - expected_preedit}"
    )
    assert catalog_com == expected_com, (
        f"COM mismatch: missing={expected_com - catalog_com}, "
        f"extra={catalog_com - expected_com}"
    )
    assert catalog_xml == expected_xml, (
        f"XML mismatch: missing={expected_xml - catalog_xml}, "
        f"extra={catalog_xml - expected_xml}"
    )

    total_ops = len(catalog["operations"])
    assert total_ops == 37, f"Expected exactly 37 operations, found {total_ops}"


def test_implementation_references_resolve_to_tracked_files(catalog):
    """Verify all implementation references point to existing tracked files and valid lines."""
    for op in catalog["operations"]:
        impl = op["implementation_reference"]
        file_path = REPO_ROOT / impl["path"]
        assert file_path.is_file(), (
            f"Operation {op['id']} implementation path does not exist: {impl['path']}"
        )
        content = file_path.read_text(encoding="utf-8").splitlines()
        line_no = impl["line"]
        assert 1 <= line_no <= len(content), (
            f"Operation {op['id']} line {line_no} out of range in {impl['path']}"
        )
        symbol = impl["symbol"]
        found_symbol = any(
            symbol in line
            for line in content[max(0, line_no - 5): min(len(content), line_no + 5)]
        )
        assert found_symbol, (
            f"Symbol {symbol} not found near line {line_no} in {impl['path']} for {op['id']}"
        )


def test_test_references_resolve_to_existing_test_nodes(catalog):
    """Verify test references exist and point to real test nodes in test files."""
    test_node_cache: dict[Path, Set[str]] = {}

    for op in catalog["operations"]:
        for test_ref in op["test_references"]:
            test_path = REPO_ROOT / test_ref["path"]
            assert test_path.is_file(), (
                f"Test path {test_ref['path']} does not exist for {op['id']}"
            )
            if test_path not in test_node_cache:
                test_node_cache[test_path] = _get_ast_function_and_method_names(test_path)

            node_name = test_ref["node"]
            assert node_name in test_node_cache[test_path], (
                f"Test node {node_name} not found in {test_ref['path']} for {op['id']}"
            )


def test_evidence_categories_and_claims_are_consistent(catalog):
    """Ensure evidence categories are valid and source inspection is never upgraded without tests."""
    for op in catalog["operations"]:
        category = op["strongest_evidence_category"]
        assert category in ALLOWED_EVIDENCE_CATEGORIES, (
            f"Invalid evidence category {category} for {op['id']}"
        )

        test_refs = op["test_references"]
        if not test_refs:
            assert category == "source", (
                f"Operation {op['id']} has no test references but claims evidence level {category}"
            )
        else:
            assert category in {"focused", "broad", "native_parity", "visual"}, (
                f"Operation {op['id']} has test references but claims {category}"
            )


def test_gaps_are_explicit_and_distinguish_source_vs_plan(catalog):
    """Verify that promised gaps distinguish plan promises from source constants."""
    gaps = catalog["gaps"]
    assert len(gaps) == 6, f"Expected exactly 6 gap entries, found {len(gaps)}"

    plan_gaps = [g for g in gaps if g["promise_type"] == "explicit_plan_promise"]
    source_gaps = [g for g in gaps if g["promise_type"] == "unimplemented_source_constant"]

    assert len(plan_gaps) == 5, f"Expected 5 plan-promised gaps, found {len(plan_gaps)}"
    assert len(source_gaps) == 1, f"Expected 1 source constant gap, found {len(source_gaps)}"

    for pg in plan_gaps:
        assert pg["planning_source"] is not None
        assert pg["planning_source"]["path"] == "docs/plans/rigorloom-master-execution-plan.md"
        assert pg["source_reference"] is None
        assert pg["status"] == "promised_absent"
        assert len(pg["minimum_closure_evidence"]) >= 1

    for sg in source_gaps:
        assert sg["planning_source"] is None
        assert sg["source_reference"] is not None
        src_path = REPO_ROOT / sg["source_reference"]["path"]
        assert src_path.is_file()
        assert sg["status"] == "unimplemented_constant"
        assert len(sg["minimum_closure_evidence"]) >= 1

    # Verify normalize_clones constant in rt_plan.py
    rt_plan_path = REPO_ROOT / "runtime" / "scripts" / "rt_plan.py"
    unimplemented = _extract_ast_keys(rt_plan_path, "PREEDIT_NOT_IMPLEMENTED")
    assert "normalize_clones" in unimplemented
    assert source_gaps[0]["source_reference"]["symbol"] == "PREEDIT_NOT_IMPLEMENTED"
