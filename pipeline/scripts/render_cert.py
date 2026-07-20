#!/usr/bin/env python3
"""Document-scoped renderer measurement, certification, and eligibility checks.

The harness never invokes Hancom.  Corpus reference PDFs and their hashes are
immutable inputs produced by the operator's Windows reference facility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import feature_extract


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_DPI = 300
DEFAULT_RENDER_TIMEOUT = 240.0


def _json_bytes(payload) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def write_json(path: str | Path, payload: dict) -> None:
    """Atomically write canonical human-readable JSON with a final newline."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{target.name}.", suffix=".tmp",
        dir=target.parent, delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _result(ok: bool, reason_codes: list[str], **extra) -> dict:
    codes = list(dict.fromkeys(reason_codes))
    primary = codes[0] if codes else ("eligible" if ok else "unknown_failure")
    payload = {
        "ok": ok,
        "reason_code": primary,
        "reason": primary,
        "reason_codes": codes or [primary],
    }
    payload.update(extra)
    return payload


def _validate_feature_map(value, *, allow_none: bool = False) -> dict[str, int] | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, dict):
        raise ValueError("features must be an object of positive integer counts")
    normalized: dict[str, int] = {}
    for raw_tag, raw_count in value.items():
        tag = str(raw_tag)
        if not tag or isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
            raise ValueError("feature tags must have positive integer counts")
        normalized[tag] = raw_count
    return dict(sorted(normalized.items()))


def load_manifest(path: str | Path, *, require_ready: bool = True) -> dict:
    manifest_path = Path(path)
    payload = _read_json(manifest_path)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("corpus manifest must be a schema v1 object")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("corpus manifest documents must be an array")
    seen: set[str] = set()
    normalized = []
    for raw in documents:
        if not isinstance(raw, dict):
            raise ValueError("every corpus entry must be an object")
        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen:
            raise ValueError("corpus entry ids must be unique non-empty strings")
        seen.add(entry_id)
        if raw.get("split") not in {"train", "holdout"}:
            raise ValueError(f"corpus entry {entry_id} has an invalid split")
        if not isinstance(raw.get("document"), str) or not raw["document"]:
            raise ValueError(f"corpus entry {entry_id} has no document path")
        if not isinstance(raw.get("generator"), dict):
            raise ValueError(f"corpus entry {entry_id} has no generator record")
        features = _validate_feature_map(raw.get("features"), allow_none=True)
        reference = raw.get("reference_pdf")
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ValueError(f"corpus entry {entry_id} has no reference PDF record")
        digest = reference.get("sha256")
        hancom = raw.get("hancom_version")
        ready = (
            features is not None
            and isinstance(digest, str) and SHA256_RE.fullmatch(digest.lower())
            and isinstance(hancom, str) and bool(hancom.strip())
            and raw.get("status", "ready") == "ready"
        )
        if require_ready and not ready:
            raise ValueError(f"corpus entry {entry_id} is awaiting its Windows reference")
        entry = dict(raw)
        entry["features"] = features
        if isinstance(digest, str):
            entry["reference_pdf"] = dict(reference, sha256=digest.lower())
        normalized.append(entry)
    return {"schema_version": SCHEMA_VERSION, "documents": normalized}


# Word-anchor comparison intentionally retains the existing research comparer's
# metric: same-page words that occur exactly once, candidate coordinates scaled
# to the reference page dimensions, Euclidean centre-point displacement.
def _words_by_page(pdf) -> list[list[tuple]]:
    return [page.get_text("words") for page in pdf]


def _unique_words(words: list[tuple]) -> dict[str, tuple]:
    counts = Counter(word[4] for word in words)
    return {word[4]: word for word in words if counts[word[4]] == 1}


def _centre(word: tuple, x_scale: float, y_scale: float) -> tuple[float, float]:
    return (
        ((word[0] + word[2]) / 2.0) * x_scale,
        ((word[1] + word[3]) / 2.0) * y_scale,
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _compare_word_anchors(reference, candidate, dpi: int) -> dict:
    ref_words = _words_by_page(reference)
    cand_words = _words_by_page(candidate)
    distances: list[float] = []
    for page_index in range(min(reference.page_count, candidate.page_count)):
        ref_page = reference[page_index]
        cand_page = candidate[page_index]
        ref_unique = _unique_words(ref_words[page_index])
        cand_unique = _unique_words(cand_words[page_index])
        x_scale = ref_page.rect.width / cand_page.rect.width
        y_scale = ref_page.rect.height / cand_page.rect.height
        for token in sorted(ref_unique.keys() & cand_unique.keys()):
            ref_xy = _centre(ref_unique[token], 1.0, 1.0)
            cand_xy = _centre(cand_unique[token], x_scale, y_scale)
            distances.append(math.hypot(cand_xy[0] - ref_xy[0], cand_xy[1] - ref_xy[1]))
    scale = dpi / 72.0
    maximum = max(distances, default=None)
    return {
        "matched_unique_words": len(distances),
        "dpi": dpi,
        "normalization": "candidate coordinates scaled to reference page dimensions",
        "max_displacement_px": round(maximum * scale, 2) if maximum is not None else None,
        "p95_displacement_px": round(_percentile(distances, 0.95) * scale, 2)
        if distances else None,
        "median_displacement_px": round(_percentile(distances, 0.50) * scale, 2)
        if distances else None,
    }


def _pixmap_samples(page, dpi: int) -> bytes:
    import fitz
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    return bytes(page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False).samples)


def _compare_rasters(reference, candidate, dpi: int) -> dict:
    changed = 0
    total = 0
    page_records = []
    maximum_pages = max(reference.page_count, candidate.page_count)
    for page_index in range(maximum_pages):
        ref_samples = _pixmap_samples(reference[page_index], dpi) \
            if page_index < reference.page_count else b""
        cand_samples = _pixmap_samples(candidate[page_index], dpi) \
            if page_index < candidate.page_count else b""
        overlap = min(len(ref_samples), len(cand_samples))
        page_changed = sum(
            left != right for left, right in zip(ref_samples[:overlap], cand_samples[:overlap])
        ) + abs(len(ref_samples) - len(cand_samples))
        page_total = max(len(ref_samples), len(cand_samples))
        changed += page_changed
        total += page_total
        page_records.append({
            "page": page_index + 1,
            "changed_channels": page_changed,
            "total_channels": page_total,
            "changed_channel_ratio": round(page_changed / page_total, 12)
            if page_total else 0.0,
        })
    return {
        "dpi": dpi,
        "changed_channels": changed,
        "total_channels": total,
        "changed_channel_ratio": round(changed / total, 12) if total else 0.0,
        "pages": page_records,
    }


def compare_pdf_metrics(reference_pdf: str | Path, candidate_pdf: str | Path, *, dpi: int = DEFAULT_DPI) -> dict:
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for renderer certification") from exc
    with fitz.open(reference_pdf) as reference, fitz.open(candidate_pdf) as candidate:
        page_count = {
            "reference": reference.page_count,
            "candidate": candidate.page_count,
            "exact": reference.page_count == candidate.page_count,
        }
        word_anchor = _compare_word_anchors(reference, candidate, dpi)
        raster = _compare_rasters(reference, candidate, dpi)
    return {"page_count": page_count, "word_anchor": word_anchor, "raster": raster}


def pdf_page_count(path: str | Path) -> int:
    """Reopen a runtime candidate and return a positive page count."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to verify a certified PDF") from exc
    with fitz.open(path) as document:
        if document.page_count <= 0:
            raise ValueError("certified PDF contains no pages")
        return document.page_count


def _probe_renderer_version(binary: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if completed.returncode != 0:
        return None
    blob = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return next((line.strip() for line in blob.splitlines() if line.strip()), None)


def resolve_renderer(
    renderer_id: str,
    *,
    renderer_binary: str | Path | None = None,
    renderer_argv: list[str] | None = None,
    renderer_version: str | None = None,
) -> dict:
    token = re.sub(r"[^A-Za-z0-9]", "_", renderer_id).upper()
    configured = renderer_binary or os.environ.get(f"RENDER_CERT_{token}_BIN")
    if renderer_id in {"rhwp", "rhwp_pdf"}:
        configured = configured or os.environ.get("RHWP_BIN") or shutil.which("rhwp")
    elif renderer_id in {"soffice", "soffice_local"}:
        configured = configured or os.environ.get("SOFFICE_BIN") or shutil.which("soffice")
    else:
        configured = configured or shutil.which(renderer_id)
    if not configured:
        raise ValueError(f"renderer binary not found for {renderer_id}")
    binary = Path(configured).expanduser().resolve()
    if not binary.is_file():
        raise ValueError(f"renderer binary is missing: {binary}")
    if renderer_argv is None:
        if renderer_id in {"rhwp", "rhwp_pdf"}:
            renderer_argv = [str(binary), "export-pdf", "{in}", "-o", "{out}"]
        elif renderer_id in {"soffice", "soffice_local"}:
            renderer_argv = [
                str(binary), "--headless", "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", "{outdir}", "{in}",
            ]
        else:
            renderer_argv = [str(binary), "{in}", "{out}"]
    version = renderer_version or _probe_renderer_version(binary)
    if not version:
        raise ValueError(f"renderer version probe failed: {binary}")
    return {
        "id": renderer_id,
        "version": version,
        "binary_path": str(binary),
        "binary_sha256": _sha256_file(binary),
        "argv": [str(item) for item in renderer_argv],
    }


def _render_command(argv: list[str], document: Path, candidate: Path) -> list[str]:
    return [
        item.replace("{in}", str(document)).replace("{out}", str(candidate))
        .replace("{outdir}", str(candidate.parent))
        for item in argv
    ]


def measure_corpus(
    renderer_id: str,
    corpus: str | Path,
    *,
    work_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    renderer_binary: str | Path | None = None,
    renderer_argv: list[str] | None = None,
    renderer_version: str | None = None,
    render_callback: Callable[[dict, Path, Path], object] | None = None,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
) -> dict:
    manifest_path = Path(corpus).resolve()
    manifest = load_manifest(manifest_path, require_ready=True)
    renderer = resolve_renderer(
        renderer_id, renderer_binary=renderer_binary, renderer_argv=renderer_argv,
        renderer_version=renderer_version,
    )
    root = Path(work_dir).resolve() if work_dir else manifest_path.parent / ".render-cert-work" / renderer_id
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    hancom_versions = sorted({entry["hancom_version"] for entry in manifest["documents"]})
    if len(hancom_versions) != 1:
        raise ValueError("a certification manifest must pin exactly one Hancom version")

    for entry in manifest["documents"]:
        record = {
            "id": entry["id"], "split": entry["split"],
            "features": entry["features"], "ok": False, "reason_codes": [],
        }
        document = (manifest_path.parent / entry["document"]).resolve()
        reference = (manifest_path.parent / entry["reference_pdf"]["path"]).resolve()
        candidate_dir = root / entry["id"]
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate = candidate_dir / "candidate.pdf"
        try:
            if not document.is_file():
                raise ValueError("document_missing")
            if not reference.is_file():
                raise ValueError("reference_pdf_missing")
            if _sha256_file(reference) != entry["reference_pdf"]["sha256"]:
                raise ValueError("reference_pdf_hash_mismatch")
            actual_features = feature_extract.extract_feature_counts(document)
            if actual_features != entry["features"]:
                raise ValueError("manifest_feature_mismatch")
            if render_callback is not None:
                callback_output = render_callback(entry, document, candidate)
                if callback_output is not None:
                    callback_path = Path(callback_output)
                    if callback_path.resolve() != candidate.resolve():
                        shutil.copyfile(callback_path, candidate)
                completed_record = {"exit_code": 0, "command": ["mocked-render-callback"]}
            else:
                command = _render_command(renderer["argv"], document, candidate)
                completed = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout,
                )
                completed_record = {
                    "command": command,
                    "exit_code": completed.returncode,
                    "stdout": (completed.stdout or "")[-16000:],
                    "stderr": (completed.stderr or "")[-16000:],
                }
                if completed.returncode != 0:
                    raise ValueError("renderer_nonzero")
                generated = candidate_dir / f"{document.stem}.pdf"
                if not candidate.is_file() and generated.is_file():
                    generated.replace(candidate)
            if not candidate.is_file():
                raise ValueError("renderer_output_missing")
            record.update({
                "ok": True,
                "document": str(document),
                "document_sha256": _sha256_file(document),
                "reference_pdf": str(reference),
                "reference_pdf_sha256": _sha256_file(reference),
                "candidate_pdf": str(candidate),
                "candidate_pdf_sha256": _sha256_file(candidate),
                "renderer_run": completed_record,
                "metrics": compare_pdf_metrics(reference, candidate, dpi=dpi),
            })
        except subprocess.TimeoutExpired:
            record["reason_codes"].append("renderer_timeout")
        except (OSError, RuntimeError, ValueError) as exc:
            code = str(exc)
            record["reason_codes"].append(code if re.fullmatch(r"[a-z0-9_]+", code) else "measurement_failed")
            record["error"] = str(exc)
        entries.append(record)

    return {
        "schema_version": SCHEMA_VERSION,
        "renderer": renderer,
        "corpus": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256_file(manifest_path),
            "hancom_version": hancom_versions[0],
        },
        "dpi": dpi,
        "documents": entries,
    }


def _validate_thresholds(thresholds) -> dict:
    required = {"page_count_exact", "word_anchor_px", "raster_changed_channel_ratio"}
    if not isinstance(thresholds, dict) or not required.issubset(thresholds):
        raise ValueError("thresholds require page_count_exact, word_anchor_px, and raster_changed_channel_ratio")
    if thresholds["page_count_exact"] is not True:
        raise ValueError("page_count_exact must be true")
    normalized = {"page_count_exact": True}
    for key in ("word_anchor_px", "raster_changed_channel_ratio"):
        value = thresholds[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"threshold {key} must be a non-negative number")
        normalized[key] = float(value)
    if "min_matched_unique_words" in thresholds:
        value = thresholds["min_matched_unique_words"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("min_matched_unique_words must be a non-negative integer")
        normalized["min_matched_unique_words"] = value
    return normalized


def _document_passes(record: dict, thresholds: dict) -> bool:
    if record.get("ok") is False or record.get("reason_codes"):
        return False
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return False
    try:
        page_ok = metrics["page_count"]["exact"] is True
        anchor = metrics["word_anchor"]["max_displacement_px"]
        matched = metrics["word_anchor"]["matched_unique_words"]
        raster = metrics["raster"]["changed_channel_ratio"]
        return (
            page_ok
            and isinstance(anchor, (int, float)) and anchor <= thresholds["word_anchor_px"]
            and isinstance(raster, (int, float)) and raster <= thresholds["raster_changed_channel_ratio"]
            and matched >= thresholds.get("min_matched_unique_words", 0)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _split_stats(records: list[dict], thresholds: dict) -> dict:
    passed = [record for record in records if _document_passes(record, thresholds)]
    failed = [record for record in records if not _document_passes(record, thresholds)]
    anchors = [
        record["metrics"]["word_anchor"]["max_displacement_px"]
        for record in records if isinstance(record.get("metrics"), dict)
        and isinstance(record["metrics"].get("word_anchor", {}).get("max_displacement_px"), (int, float))
    ]
    rasters = [
        record["metrics"]["raster"]["changed_channel_ratio"]
        for record in records if isinstance(record.get("metrics"), dict)
        and isinstance(record["metrics"].get("raster", {}).get("changed_channel_ratio"), (int, float))
    ]
    return {
        "total": len(records), "passed": len(passed), "failed": len(failed),
        "document_ids": [record.get("id") for record in records],
        "failed_ids": [record.get("id") for record in failed],
        "max_word_anchor_px": max(anchors, default=None),
        "max_raster_changed_channel_ratio": max(rasters, default=None),
    }


def _certificate_digest(certificate: dict) -> str:
    body = dict(certificate)
    body.pop("certificate_sha256", None)
    return _sha256_payload(body)


def issue_certificate(
    measurements: dict | str | Path,
    thresholds: dict,
    *,
    issued_at: str | None = None,
) -> dict:
    measured = _read_json(measurements) if isinstance(measurements, (str, Path)) else measurements
    if not isinstance(measured, dict) or measured.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("measurements must be a schema v1 object")
    renderer = measured.get("renderer")
    corpus = measured.get("corpus")
    documents = measured.get("documents")
    if not isinstance(renderer, dict) or not isinstance(corpus, dict) or not isinstance(documents, list):
        raise ValueError("measurements are missing renderer, corpus, or documents")
    threshold_values = _validate_thresholds(thresholds)
    for record in documents:
        if not isinstance(record, dict) or record.get("split") not in {"train", "holdout"}:
            raise ValueError("measurement document records must declare train/holdout")
        record["features"] = _validate_feature_map(record.get("features"))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in documents:
        grouped[json.dumps(record["features"], sort_keys=True, separators=(",", ":"))].append(record)
    failed_holdout_features = [
        record["features"] for record in documents
        if record["split"] == "holdout"
        and not _document_passes(record, threshold_values)
    ]
    envelope = []
    for key in sorted(grouped):
        group = grouped[key]
        train = [record for record in group if record["split"] == "train"]
        holdout = [record for record in group if record["split"] == "holdout"]
        group_features = json.loads(key)
        covers_failed_holdout = any(
            all(
                tag in group_features and count <= group_features[tag]
                for tag, count in failed.items()
            )
            for failed in failed_holdout_features
        )
        if (train and holdout
                and not any(tag.startswith("unknown:") for tag in group_features)
                and not covers_failed_holdout
                and all(_document_passes(record, threshold_values) for record in group)):
            envelope.append({
                "features": group_features,
                "train_document_ids": [record.get("id") for record in train],
                "holdout_document_ids": [record.get("id") for record in holdout],
            })

    train_records = [record for record in documents if record["split"] == "train"]
    holdout_records = [record for record in documents if record["split"] == "holdout"]
    if not holdout_records:
        raise ValueError("certification requires at least one holdout document")
    certificate = {
        "schema_version": SCHEMA_VERSION,
        "renderer_id": renderer.get("id"),
        "renderer_version": renderer.get("version"),
        "renderer_binary_path": renderer.get("binary_path"),
        "renderer_binary_hash": renderer.get("binary_sha256"),
        "renderer_argv": renderer.get("argv"),
        "hancom_version": corpus.get("hancom_version"),
        "corpus_manifest_path": corpus.get("manifest_path"),
        "corpus_manifest_hash": corpus.get("manifest_sha256"),
        "measurement_hash": _sha256_payload(measured),
        "thresholds": threshold_values,
        "envelope": envelope,
        "train_stats": _split_stats(train_records, threshold_values),
        "holdout_stats": _split_stats(holdout_records, threshold_values),
        "issued_at": issued_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    required_strings = (
        "renderer_id", "renderer_version", "renderer_binary_path", "renderer_binary_hash",
        "hancom_version", "corpus_manifest_path", "corpus_manifest_hash",
    )
    if any(not isinstance(certificate[key], str) or not certificate[key] for key in required_strings):
        raise ValueError("measurements do not contain complete renderer/corpus provenance")
    if not isinstance(certificate["renderer_argv"], list) or not certificate["renderer_argv"]:
        raise ValueError("measurements do not contain a renderer argv template")
    certificate["certificate_sha256"] = _certificate_digest(certificate)
    return certificate


def _resolve_recorded_path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def verify_certificate(
    certificate: dict | str | Path,
    *,
    renderer_binary: str | Path | None = None,
    renderer_version: str | None = None,
) -> dict:
    source_path = Path(certificate).resolve() if isinstance(certificate, (str, Path)) else None
    base = source_path.parent if source_path else Path.cwd()
    try:
        cert = _read_json(source_path) if source_path else certificate
    except FileNotFoundError:
        return _result(False, ["certificate_missing"])
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _result(False, ["certificate_invalid_json"])
    if not isinstance(cert, dict):
        return _result(False, ["certificate_schema_invalid"])
    expected_self_hash = cert.get("certificate_sha256")
    if not isinstance(expected_self_hash, str) or _certificate_digest(cert) != expected_self_hash:
        return _result(False, ["certificate_hash_mismatch"])

    required = (
        "renderer_id", "renderer_version", "renderer_binary_path", "renderer_binary_hash",
        "renderer_argv", "hancom_version", "corpus_manifest_path",
        "corpus_manifest_hash", "thresholds", "envelope", "issued_at",
    )
    if cert.get("schema_version") != SCHEMA_VERSION or any(key not in cert for key in required):
        return _result(False, ["certificate_schema_invalid"])
    try:
        _validate_thresholds(cert["thresholds"])
        if not isinstance(cert["envelope"], list):
            raise ValueError
        for entry in cert["envelope"]:
            features = entry.get("features") if isinstance(entry, dict) else None
            _validate_feature_map(features)
            if any(tag.startswith("unknown:") for tag in features):
                raise ValueError
        if not isinstance(cert["renderer_argv"], list) or not cert["renderer_argv"]:
            raise ValueError
        if not SHA256_RE.fullmatch(str(cert["renderer_binary_hash"])):
            raise ValueError
        if not SHA256_RE.fullmatch(str(cert["corpus_manifest_hash"])):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return _result(False, ["certificate_schema_invalid"])

    try:
        manifest_path = _resolve_recorded_path(cert["corpus_manifest_path"], base)
    except (OSError, TypeError, ValueError):
        return _result(False, ["manifest_missing"])
    if not manifest_path.is_file():
        return _result(False, ["manifest_missing"])
    if _sha256_file(manifest_path) != cert["corpus_manifest_hash"]:
        return _result(False, ["manifest_hash_mismatch"])
    try:
        manifest = load_manifest(manifest_path, require_ready=True)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _result(False, ["manifest_invalid"])
    hancom_versions = {entry["hancom_version"] for entry in manifest["documents"]}
    if hancom_versions != {cert["hancom_version"]}:
        return _result(False, ["hancom_version_mismatch"])

    try:
        binary = Path(renderer_binary).expanduser().resolve() if renderer_binary is not None \
            else _resolve_recorded_path(cert["renderer_binary_path"], base)
    except (OSError, TypeError, ValueError):
        return _result(False, ["renderer_binary_missing"])
    if not binary.is_file():
        return _result(False, ["renderer_binary_missing"])
    if _sha256_file(binary) != cert["renderer_binary_hash"]:
        return _result(False, ["renderer_binary_hash_mismatch"])
    live_version = renderer_version if renderer_version is not None else _probe_renderer_version(binary)
    if live_version is None:
        return _result(False, ["renderer_probe_failed"])
    if str(live_version).strip() != str(cert["renderer_version"]).strip():
        return _result(False, ["renderer_version_mismatch"])
    return _result(
        True, ["certificate_valid"], certificate=cert,
        certificate_path=str(source_path) if source_path else None,
        manifest_path=str(manifest_path), renderer_binary=str(binary),
        renderer_version=str(live_version).strip(),
    )


def _inside_envelope(features: dict[str, int], envelope: list[dict]) -> bool:
    for entry in envelope:
        maximum = entry.get("features", {})
        if all(tag in maximum and count <= maximum[tag] for tag, count in features.items()):
            return True
    return False


def check_document(
    document: str | Path,
    certificate: dict | str | Path,
    *,
    renderer_binary: str | Path | None = None,
    renderer_version: str | None = None,
) -> dict:
    verification = verify_certificate(
        certificate, renderer_binary=renderer_binary, renderer_version=renderer_version
    )
    if verification.get("ok") is not True:
        return {
            **verification,
            "eligible": False,
            "document": str(Path(document)),
        }
    try:
        features = feature_extract.extract_feature_counts(document)
    except (OSError, ValueError):
        return {
            **_result(False, ["document_unreadable"]),
            "eligible": False, "document": str(Path(document)),
        }
    unknown = sorted(tag for tag in features if tag.startswith("unknown:"))
    if unknown:
        return {
            **_result(False, ["unknown_feature"]),
            "eligible": False, "document": str(Path(document)),
            "features": features, "unknown_features": unknown,
        }
    certificate_payload = verification["certificate"]
    if not _inside_envelope(features, certificate_payload["envelope"]):
        return {
            **_result(False, ["envelope_mismatch"]),
            "eligible": False, "document": str(Path(document)),
            "features": features,
        }
    return {
        **_result(True, ["eligible"]),
        "eligible": True, "document": str(Path(document).resolve()),
        "features": features,
        "certificate_sha256": certificate_payload["certificate_sha256"],
        "renderer_id": certificate_payload["renderer_id"],
        "renderer_version": certificate_payload["renderer_version"],
        "hancom_version": certificate_payload["hancom_version"],
    }


def _threshold_args(args) -> dict:
    if args.thresholds:
        candidate = Path(args.thresholds)
        if candidate.is_file():
            return _read_json(candidate)
        return json.loads(args.thresholds)
    if args.word_anchor_px is None or args.raster_changed_channel_ratio is None:
        raise ValueError("certify requires --thresholds or both metric threshold options")
    return {
        "page_count_exact": True,
        "word_anchor_px": args.word_anchor_px,
        "raster_changed_channel_ratio": args.raster_changed_channel_ratio,
        **({"min_matched_unique_words": args.min_matched_unique_words}
           if args.min_matched_unique_words is not None else {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    measure_parser = subparsers.add_parser("measure")
    measure_parser.add_argument("--renderer", required=True)
    measure_parser.add_argument("--corpus", required=True)
    measure_parser.add_argument("--out")
    measure_parser.add_argument("--work-dir")
    measure_parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    measure_parser.add_argument("--renderer-binary")
    measure_parser.add_argument("--renderer-version")
    measure_parser.add_argument("--renderer-command",
                                help="shell-like argv template using {in}, {out}, {outdir}")
    measure_parser.add_argument("--timeout", type=float, default=DEFAULT_RENDER_TIMEOUT)

    certify_parser = subparsers.add_parser("certify")
    certify_parser.add_argument("measurements_pos", nargs="?")
    certify_parser.add_argument("--measurements")
    certify_parser.add_argument("--thresholds", help="JSON file or inline JSON object")
    certify_parser.add_argument("--word-anchor-px", type=float)
    certify_parser.add_argument("--raster-changed-channel-ratio", type=float)
    certify_parser.add_argument("--min-matched-unique-words", type=int)
    certify_parser.add_argument("--issued-at")
    certify_parser.add_argument("--out")

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("document")
    check_parser.add_argument("certificate")
    check_parser.add_argument("--renderer-binary")
    check_parser.add_argument("--renderer-version")
    check_parser.add_argument("--out")

    args = parser.parse_args(argv)
    try:
        if args.command == "measure":
            renderer_argv = shlex.split(args.renderer_command) if args.renderer_command else None
            payload = measure_corpus(
                args.renderer, args.corpus, work_dir=args.work_dir, dpi=args.dpi,
                renderer_binary=args.renderer_binary, renderer_argv=renderer_argv,
                renderer_version=args.renderer_version,
                timeout=args.timeout,
            )
            code = 0 if all(record.get("ok") for record in payload["documents"]) else 3
        elif args.command == "certify":
            measurement_path = args.measurements or args.measurements_pos
            if not measurement_path:
                raise ValueError("certify requires a measurements JSON path")
            payload = issue_certificate(
                measurement_path, _threshold_args(args), issued_at=args.issued_at
            )
            code = 0
        else:
            payload = check_document(
                args.document, args.certificate,
                renderer_binary=args.renderer_binary,
                renderer_version=args.renderer_version,
            )
            code = 0 if payload["eligible"] else 3
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        payload = _result(False, ["operation_failed"], error=str(exc))
        code = 3
    if getattr(args, "out", None):
        write_json(args.out, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
