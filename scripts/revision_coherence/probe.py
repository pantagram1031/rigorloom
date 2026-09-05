#!/usr/bin/env python3
"""Execute production routing/mapping functions with controlled revision inputs.

This is a boundary probe, NOT a renderer, HWPX writer, or installed-app test.
Only selected AST function bodies are loaded; collaborators are deliberately
controlled. No product file is modified. Exit 1 means the contract is violated,
exit 2 means the probe could not execute. See the accompanying research record.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

GEOMETRY_FUNCTIONS = ("_norm_rect", "build_targets", "base_span", "map_spans")


def extract(path: Path, names: tuple[str, ...], class_name: str | None = None):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    nodes = tree.body
    if class_name:
        classes = [n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name]
        if len(classes) != 1:
            raise ValueError(f"expected one {class_name} in {path.name}")
        nodes = classes[0].body
    selected = []
    for name in names:
        matches = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == name]
        if len(matches) != 1:
            raise ValueError(f"expected one {name} in {path.name}; do not guess after refactor")
        selected.append(matches[0])
    fingerprints = {
        node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in selected
    }
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, str(path), "exec"), fingerprints


def profile(texts):
    # Minimal form_inspect shape. Ground truth is supplied independently of mapping.
    return {"anchor_records": [{"at_para": i, "text": t} for i, t in enumerate(texts)],
            "table_map": []}


def scene(texts):
    return [{"text": t, "bbox": [20, 20 + 40*i, 180, 40 + 40*i], "sizePt": 12}
            for i, t in enumerate(texts)]


class ProbeRpcError(Exception):
    pass


def run_runtime(root: Path, intervention: str = "none"):
    env = {"RpcError": ProbeRpcError}
    geometry, gh = extract(root / "runtime/scripts/rt_geometry.py", GEOMETRY_FUNCTIONS)
    exec(geometry, env)
    core, ch = extract(root / "runtime/scripts/rt_core.py", ("document_page_geometry",),
                       "RuntimeCore")
    exec(core, env)
    method = env["document_page_geometry"]
    if intervention in ("runtime-only", "coherent-guard", "public-guard"):
        # Counterfactual only: compile a changed routing method IN MEMORY.
        # The checkout and the renderer are never modified.
        source = ast.unparse(ast.parse((root / "runtime/scripts/rt_core.py").read_text()))
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RuntimeCore")
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name == "document_page_geometry")
        class BindSubject(ast.NodeTransformer):
            changed = 0
            def visit_Call(self, call):
                if isinstance(call.func, ast.Name) and call.func.id == "load_profile":
                    if any(k.arg == "subject" for k in call.keywords):
                        raise ValueError("routing already changed; rebase the intervention")
                    call.keywords.append(ast.keyword(arg="subject", value=ast.parse(
                        "candidate_artifact(session, self._bare_run_id(run_id))[0] "
                        "if run_id is not None else None", mode="eval").body))
                    self.changed += 1
                return self.generic_visit(call)
        binder = BindSubject()
        binder.visit(node)
        if binder.changed != 1:
            raise ValueError("counterfactual expected one profile read")
        modified = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(modified)
        exec(compile(modified, "counterfactual-routing", "exec"), env)
        method = env["document_page_geometry"]
    normalizer = lambda text: " ".join(text.split())
    cases = []
    scenes = {}

    def exercise(name, original, candidate, run_id, expectation, profile_error=False):
        source_path = Path("synthetic-source.hwpx")
        candidate_path = Path("synthetic-candidate.hwpx")
        calls = []
        session = SimpleNamespace(id="session-a", ensure_dirs=lambda: None,
                                  source=source_path, meta={"sourceSha256": "source-sha"})
        store = SimpleNamespace(get=lambda session_id: session)
        owner = SimpleNamespace(store=store, tools=object(), _geometry_cache={},
                                _bare_run_id=lambda value: value)

        def load_profile(tools, actual_session, **kwargs):
            subject = kwargs.get("subject")
            calls.append({"subject": "candidate" if subject == candidate_path else "source",
                          "tag": kwargs.get("tag")})
            if profile_error:
                raise ProbeRpcError("fixture profile unavailable")
            return profile(candidate if subject == candidate_path else original)

        def candidate_artifact(actual_session, requested_run):
            if requested_run != "candidate-a":
                raise ProbeRpcError("candidate unavailable")
            return candidate_path, {"candidate": {"sha256": "candidate-sha"}}

        def page_geometry(actual_session, *, page, run_id, profile, cache, tools):
            if run_id not in (None, "candidate-a"):
                raise ProbeRpcError("candidate unavailable")
            lines = scene(original if run_id is None else candidate)
            targets = {} if profile is None else env["build_targets"](profile, normalizer)[0]
            return {"available": True, "spans": env["map_spans"](
                lines, targets, normalizer, 600, 800)}

        env.update(load_profile=load_profile, candidate_artifact=candidate_artifact,
                   page_geometry=page_geometry)
        result = method(owner, "session-a", page=0, run_id=run_id)
        spans = result["spans"]
        passed = expectation(spans, calls)
        record = {"name": name, "contract_passed": bool(passed), "profile_reads": calls,
                  "spans": spans}
        cases.append(record)
        scenes[name] = spans

    exercise("source_unique_control", ["ALPHA", "BETA"], ["GAMMA", "BETA"], None,
             lambda s, c: s[0]["confidence"] == "unique" and s[0]["address"]["atPara"] == 0)
    exercise("source_duplicate_control", ["BETA", "BETA"], ["BETA", "BETA"], None,
             lambda s, c: all(x["confidence"] == "ambiguous" for x in s))
    exercise("candidate_profile_identity", ["ALPHA", "BETA"], ["GAMMA", "BETA"],
             "candidate-a", lambda s, c: c and c[0]["subject"] == "candidate")
    exercise("candidate_new_text_remains_addressable", ["ALPHA", "BETA"], ["GAMMA", "BETA"],
             "candidate-a", lambda s, c: s[0]["confidence"] == "unique"
             and s[0]["address"]["atPara"] == 0)
    exercise("candidate_collision_is_not_false_unique", ["ALPHA", "BETA"], ["BETA", "BETA"],
             "candidate-a", lambda s, c: all(x["confidence"] == "ambiguous" for x in s))
    exercise("candidate_removes_old_ambiguity", ["BETA", "BETA"], ["GAMMA", "BETA"],
             "candidate-a", lambda s, c: all(x["confidence"] == "unique" for x in s)
             and [x["address"]["atPara"] for x in s] == [0, 1])
    exercise("missing_profile_refuses_mapping_control", ["ALPHA"], ["GAMMA"], "candidate-a",
             lambda s, c: all(x["confidence"] == "unmapped" for x in s), profile_error=True)

    # A deliberate intervention on only the routed subject, not on the mapper.
    # This is a causal control, NOT an applied product fix.
    corrected_targets = env["build_targets"](profile(["BETA", "BETA"]), normalizer)[0]
    intervention = env["map_spans"](scene(["BETA", "BETA"]), corrected_targets,
                                     normalizer, 600, 800)
    cases.append({"name": "same_revision_mapper_intervention_control",
                  "contract_passed": all(s["confidence"] == "ambiguous" for s in intervention),
                  "spans": intervention})
    return {"function_ast_sha256": {**gh, **ch}, "cases": cases, "scenes": scenes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-label", default="working-tree (not attested)")
    parser.add_argument("--typescript", type=Path, help="TypeScript installation directory")
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--intervention", choices=("none", "runtime-only", "frontend-routing-only",
                                                   "coherent-guard", "public-guard"), default="none",
                        help="in-memory causal controls, NOT applied fixes")
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        runtime = run_runtime(root, args.intervention)
        report = {
            "schema": "rigorloom-revision-coherence-probe/v1",
            "source_label": args.source_label,
            "evidence_scope": "production function bodies; controlled collaborators; not GUI/E2E",
            "intervention": args.intervention,
            "runtime": runtime,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not args.runtime_only:
            helper = Path(__file__).with_name("probe_desktop.cjs")
            command = ["node", str(helper), str(root), str(args.out),
                       str(args.typescript.resolve()) if args.typescript else "",
                       args.intervention]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
            if completed.returncode:
                raise RuntimeError("desktop probe did not complete: " + completed.stderr[-1000:])
            report["desktop"] = json.loads(completed.stdout)
        else:
            report["desktop"] = {"state": "NOT RUN", "cases": []}
        all_cases = runtime["cases"] + report["desktop"]["cases"]
        report["summary"] = {
            "passed": sum(c["contract_passed"] for c in all_cases),
            "violations": sum(not c["contract_passed"] for c in all_cases),
            "desktop_executed": not args.runtime_only,
        }
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"]))
        for case in all_cases:
            print(("PASS " if case["contract_passed"] else "VIOLATION ") + case["name"])
        return 1 if report["summary"]["violations"] else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SyntaxError) as exc:
        print(f"PROBE NOT COMPLETED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
