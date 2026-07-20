#!/usr/bin/env python3
"""Emit portable Windows-reference handoffs; never invoke the Windows side."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def emit_windows_reference_stub(
    corpus_dir: str | Path,
    *,
    entry_id: str,
    split: str,
    document_name: str,
    reference_pdf_name: str,
    template_ref: str,
    ops: list[dict],
) -> dict:
    root = Path(corpus_dir)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", entry_id):
        raise ValueError("entry id must be a safe filename token")
    if split not in {"train", "holdout"}:
        raise ValueError("split must be train or holdout")
    if not isinstance(ops, list) or not all(isinstance(item, dict) for item in ops):
        raise ValueError("ops must be a list of JSON objects")

    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": 1, "documents": []}
    documents = manifest.get("documents")
    if manifest.get("schema_version") != 1 or not isinstance(documents, list):
        raise ValueError("manifest.json is not a render-cert schema v1 manifest")
    if any(item.get("id") == entry_id for item in documents if isinstance(item, dict)):
        raise ValueError(f"manifest entry already exists: {entry_id}")

    ops_rel = Path("ops") / f"{entry_id}.ops.json"
    _write(root / ops_rel, ops)
    entry = {
        "id": entry_id,
        "split": split,
        "document": (Path("documents") / document_name).as_posix(),
        "generator": {
            "type": "windows-com-ops",
            "ops": ops_rel.as_posix(),
            "template_ref": template_ref,
            "requires_windows_reference": True,
        },
        "features": None,
        "reference_pdf": {
            "path": (Path("references") / reference_pdf_name).as_posix(),
            "sha256": None,
        },
        "hancom_version": None,
        "status": "awaiting_windows_reference",
    }
    documents.append(entry)
    documents.sort(key=lambda item: item["id"])
    _write(manifest_path, manifest)
    return entry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", default=str(Path(__file__).parent))
    parser.add_argument("--id", required=True)
    parser.add_argument("--split", required=True, choices=["train", "holdout"])
    parser.add_argument("--document", required=True)
    parser.add_argument("--reference-pdf", required=True)
    parser.add_argument("--template-ref", required=True)
    parser.add_argument("--ops-json", required=True)
    args = parser.parse_args(argv)
    ops = json.loads(Path(args.ops_json).read_text(encoding="utf-8"))
    entry = emit_windows_reference_stub(
        args.corpus_dir,
        entry_id=args.id,
        split=args.split,
        document_name=args.document,
        reference_pdf_name=args.reference_pdf,
        template_ref=args.template_ref,
        ops=ops,
    )
    print(json.dumps({
        "ok": True,
        "status": "STOP_AWAITING_WINDOWS_REFERENCE",
        "entry": entry,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
