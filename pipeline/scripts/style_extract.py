#!/usr/bin/env python3
"""Mine schema-valid DRAFT personalization packs from content.md files."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics

from checker_base import EXIT_HARD, EXIT_PASS, cli_main, usage_error, verdict_skeleton
from claim_extraction import find_body
from personalization_ctl import pack_schema, validate_instance


PROFILE_SCHEMA = "report-pipeline/personalization-v1"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def corpus_paths(inputs: list[str | Path]) -> list[Path]:
    paths = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            paths.extend(path.rglob("*.md"))
        else:
            paths.append(path)
    return sorted({path.resolve() for path in paths}, key=lambda path: str(path))


def profile_marker(out_dir: Path) -> Path | None:
    current = out_dir.resolve()
    for candidate in (current, *current.parents):
        marker = candidate / "manifest.json"
        if not marker.is_file():
            continue
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema") == PROFILE_SCHEMA:
            return marker
    return None


def prose_paragraphs(text: str) -> list[str]:
    body = find_body(text)
    result = []
    for paragraph in re.split(r"\n\s*\n", body):
        lines = [line.strip() for line in paragraph.splitlines()
                 if line.strip() and not line.lstrip().startswith(("#", "|", "<!--"))]
        value = " ".join(lines)
        if value:
            result.append(value)
    return result


def ending_distribution(paragraphs: list[str]) -> dict[str, int]:
    result = Counter()
    for paragraph in paragraphs:
        for sentence in re.findall(r"[^.!?。！？]+[.!?。！？]?", paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            punctuation = sentence[-1] if sentence[-1] in ".!?。！？" else ""
            stem = sentence[:-1].rstrip() if punctuation else sentence
            if punctuation in "?？":
                result["question"] += 1
            elif punctuation in "!！":
                result["exclamation"] += 1
            elif stem.endswith("다"):
                result["declarative_da"] += 1
            elif stem.endswith("요"):
                result["polite_yo"] += 1
            elif stem.endswith(("함", "음")):
                result["nominal"] += 1
            else:
                result["other"] += 1
    return dict(sorted(result.items()))


def repeated_tics(paragraphs: list[str]) -> list[dict]:
    counts = Counter()
    for paragraph in paragraphs:
        tokens = re.findall(r"[A-Za-z가-힣][A-Za-z가-힣0-9_-]+", paragraph.casefold())
        for size in (2, 3):
            counts.update(" ".join(tokens[index:index + size])
                          for index in range(len(tokens) - size + 1))
    candidates = [(phrase, count) for phrase, count in counts.items() if count >= 3]
    candidates.sort(key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [{"phrase": phrase, "count": count} for phrase, count in candidates[:8]]


def section_orders(texts: list[str]) -> list[list[str]]:
    orders = []
    for text in texts:
        names = []
        for line in text.splitlines():
            match = re.match(r"^##\s+SECTION:\s*(.+?)\s*$", line)
            if not match:
                match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                names.append(match.group(1))
        orders.append(names)
    return orders


def build_packs(paths: list[Path]) -> dict[str, dict]:
    texts = [path.read_text(encoding="utf-8") for path in paths]
    paragraphs = [paragraph for text in texts for paragraph in prose_paragraphs(text)]
    lengths = [len(paragraph) for paragraph in paragraphs]
    endings = ending_distribution(paragraphs)
    tics = repeated_tics(paragraphs)
    provenance = {"corpus": [{"path": str(path), "sha256": sha_file(path)}
                             for path in paths]}
    default_ending = max(endings, key=lambda key: (endings[key], key)) if endings else "other"
    banned = []
    for tic in tics:
        regex = re.escape(tic["phrase"]).replace(r"\ ", r"\s+")
        banned.append({
            "id": "repeated-tic-" + hashlib.sha256(
                tic["phrase"].encode("utf-8")).hexdigest()[:10],
            "regex": regex,
            "severity": "warn",
            "description": f"Draft candidate repeated {tic['count']} times in corpus.",
        })
    length_stats = {
        "count": len(lengths),
        "min": min(lengths) if lengths else 0,
        "max": max(lengths) if lengths else 0,
        "mean": round(statistics.fmean(lengths), 2) if lengths else 0,
        "median": statistics.median(lengths) if lengths else 0,
    }
    prose = {
        "schema": "report-pipeline/preference-pack/prose_rules-v1",
        "pack_type": "prose_rules",
        "name": "taste-mine-draft",
        "version": 1,
        "draft": True,
        "provenance": provenance,
        "banned_patterns": banned,
        "signature_phrases": [],
        "endings_policy": {
            "default_style": default_ending,
            "per_doc_type": {},
            "observed_distribution": endings,
        },
        "advisory_notes": [
            "Candidates require operator review before registration.",
            "Repeated phrases are signals, not automatically prohibited prose.",
        ],
        "mining_stats": {
            "paragraph_length_chars": length_stats,
            "sentence_endings": endings,
            "repeated_tics": tics,
        },
    }
    orders = section_orders(texts)
    order_counts = Counter(tuple(order) for order in orders if order)
    preferred = list(sorted(order_counts.items(),
                            key=lambda item: (-item[1], item[0]))[0][0]
                     if order_counts else [])
    heading_counts = Counter(name for order in orders for name in order)
    structure = {
        "schema": "report-pipeline/preference-pack/report_structure-v1",
        "pack_type": "report_structure",
        "name": "taste-mine-draft",
        "version": 1,
        "draft": True,
        "provenance": provenance,
        "title_format": "{topic}",
        "section_policies": {
            "observed_orders": [
                {"sections": list(order), "count": count}
                for order, count in sorted(order_counts.items(),
                                           key=lambda item: (-item[1], item[0]))
            ],
            "heading_name_frequencies": dict(sorted(heading_counts.items())),
        },
        "citation_style": {"sources": "any", "in_text": "narrative"},
        "preferred_sections": preferred,
    }
    return {"prose_rules": prose, "report_structure": structure}


def mine(inputs: list[str | Path], out_dir: str | Path) -> tuple[dict, int]:
    paths, out_dir = corpus_paths(inputs), Path(out_dir)
    if not paths or any(path.suffix.lower() != ".md" or not path.is_file()
                        for path in paths):
        return usage_error(out_dir, "style_extract",
                           "corpus must contain one or more existing .md files")
    marker = profile_marker(out_dir)
    if marker is not None:
        return usage_error(
            out_dir, "style_extract",
            f"refusing to write drafts inside personalization profile root: {marker}")
    try:
        packs = build_packs(paths)
    except (OSError, UnicodeError) as exc:
        return usage_error(out_dir, "style_extract", f"corpus unreadable: {exc}")
    hard, errors_by_pack = [], {}
    for pack_type, pack in packs.items():
        errors = validate_instance(pack, pack_schema(pack_type))
        if errors:
            errors_by_pack[pack_type] = errors
            hard.append({"code": "style_pack_schema_invalid",
                         "msg": f"{pack_type} draft failed schema validation",
                         "at": errors})
    outputs = {}
    if not hard:
        out_dir.mkdir(parents=True, exist_ok=True)
        for pack_type, pack in packs.items():
            target = out_dir / f"{pack_type}.draft.json"
            target.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
            outputs[pack_type] = str(target.resolve())
    verdict = verdict_skeleton(
        str(out_dir.resolve()), "style_extract", hard=hard,
        extra={"drafts": outputs, "corpus_files": [str(path) for path in paths],
               "manual_install_required": True,
               "schema_errors": errors_by_pack})
    return verdict, EXIT_HARD if hard else EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("mine DRAFT packs from content.md files; never writes into "
                     "a profile root; review and install manually"))
    parser.add_argument("inputs", nargs="+", help="content.md files or directories")
    parser.add_argument("--out-dir", required=True,
                        help="draft-only output directory outside any profile root")
    return parser


def main(argv=None) -> int:
    return cli_main(build_parser(), lambda args: mine(args.inputs, args.out_dir),
                    argv, create_out_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
