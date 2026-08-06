# -*- coding: utf-8 -*-
"""Read-time schema validation for assembly/proof verdict files.

Shared-miss #5 (variant audit, B4 bonus finding): the proof-loop
verdict writer (``engine/scripts/fill_report.py``) can emit ``converged: true``
together with ``status: escalate_human`` — phase-1 convergence stays recorded
while the proof phase overlays an escalation status onto the same object.
The read-time rejection predates the Wave 2 absorb (the writer used to live
in the external hwp-master repo) and stays as defense in depth: any consumer of a verdict file (Stage 6
``submission_preflight`` is the fail-closed gate) must treat the pair as a
HARD finding, never as a converged result.

Stdlib only; import-safe from any checker.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

# Statuses that assert "a human must intervene" — logically incompatible
# with a converged:true record in the same verdict.
ESCALATION_STATUSES = frozenset({"escalate_human"})


def contradiction_findings(
    verdict: Mapping[str, Any] | None,
    *,
    at: str = "verdict",
) -> list[dict]:
    """Return HARD findings for self-contradictory verdict objects.

    The confirmed contradictory pair is ``converged: true`` +
    ``status: escalate_human``. Anything that is not a mapping produces no
    findings here (absence/shape errors are the caller's concern).
    """
    if not isinstance(verdict, Mapping):
        return []
    findings: list[dict] = []
    status = str(verdict.get("status") or "").strip().lower()
    if verdict.get("converged") is True and status in ESCALATION_STATUSES:
        findings.append({
            "code": "verdict_contradiction",
            "msg": (
                "verdict is self-contradictory: converged:true cannot "
                f"coexist with status:{status} — treat as NOT converged "
                "and escalate"
            ),
            "at": at,
        })
    return findings


def load_verdict(path: str | Path) -> Mapping[str, Any] | None:
    """Read a verdict JSON file; None when absent/unreadable/not an object."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_verdict_file(path: str | Path, *, at: str | None = None) -> list[dict]:
    """Load ``path`` and return contradiction findings (empty when absent)."""
    verdict = load_verdict(path)
    return contradiction_findings(verdict, at=at or str(path))
