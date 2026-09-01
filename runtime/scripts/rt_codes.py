#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Runtime's closed refusal vocabulary and its hard limits.

One module, one set, one test (``tests/test_runtime_transport.py``): the same
discipline ``document_evidence.BACKEND_IDS`` (engine/scripts/document_evidence.py:32)
and ``checker_base.RULE_STATES`` (pipeline/scripts/checker_base.py:41) already
apply to their vocabularies. A code that is not in ``ERROR_CODES`` cannot be
emitted — ``RpcError`` asserts membership at construction, so a typo is a crash
in a test rather than a code a client has to guess about.

Correction to docs/runtime-protocol-v0.md §5.1: the design said the receipt
codes ``receipt_duplicate_key`` / ``receipt_nonfinite_value``
(engine/scripts/document_evidence.py:1952, :1962) would be "reused verbatim"
for the transport. They are not, and should not be: those codes name a
*receipt* and carry ``path: output/proof/backend/receipt.json``. A duplicate
member in a request frame is not a receipt defect. The transport therefore
uses ``duplicate_key`` / ``nonfinite_number`` for frames and keeps the
``receipt_*`` spelling for the receipt-reading path, where it is true.

Exit codes stay the repository's three (pipeline/scripts/checker_base.py:13-16).
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

PROTOCOL_VERSION = "0"
#: Recorded in every receipt. Bump when the *behaviour* of an applied plan
#: changes, not when a docstring does.
IMPL_VERSION = "0.1.0"

RECEIPT_SCHEMA = "rigorloom/runtime-candidate/v0"
PLAN_SCHEMA = "rigorloom/runtime-plan/v0"

# --- limits -----------------------------------------------------------------
#: One protocol frame, excluding its terminating newline. Sibling value:
#: ``renderer_runtime_v2.MAX_RECEIPT_BYTES`` (pipeline/scripts/renderer_runtime_v2.py:63).
MAX_FRAME_BYTES = 1 * 1024 * 1024
#: A ``document/readRegion`` result. Exceeding it REFUSES; it never truncates
#: silently — ``text_preview`` already learned that lesson and reports
#: ``truncated: true`` (engine/scripts/form_inspect.py:32-35).
MAX_REGION_BYTES = 256 * 1024
#: Source document ceiling. Same value as ``hwp_ingress.MAX_INPUT_BYTES``
#: (pipeline/scripts/hwp_ingress.py:40).
MAX_SOURCE_BYTES = 256 * 1024 * 1024
#: hwpx zip sanity, same values as pipeline/scripts/hwp_ingress.py:41-46.
MAX_ZIP_MEMBERS = 1024
MAX_ZIP_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
#: Bounded child stdout/stderr, as pipeline/scripts/renderer_runtime_v2.py:64.
MAX_CHILD_OUTPUT_BYTES = 8 * 1024 * 1024
#: Child wall clock. Above the measured loaded-spawn distribution recorded in
#: tests/test_subprocess_bounds.py (median 9.00s, worst observed 36.46s).
CHILD_TIMEOUT_SECONDS = 120.0

#: An operator or a packaged host may point engine children at a real
#: interpreter. Without it children run under ``sys.executable``, which in a
#: frozen host is the host itself.
CHILD_PYTHON_ENV = "RIGORLOOM_CHILD_PYTHON"

# --- rendering --------------------------------------------------------------
#: A page raster is always written to the session and referenced by path. It is
#: ALSO inlined as base64 when it fits comfortably inside one frame; above this
#: the response carries the path and says why it did not inline. Well under
#: MAX_FRAME_BYTES because base64 costs a third on top.
MAX_INLINE_IMAGE_BYTES = 512 * 1024
DEFAULT_RENDER_DPI = 96
MIN_RENDER_DPI = 24
MAX_RENDER_DPI = 400

# --- events -----------------------------------------------------------------
#: Poll interval for an event subscription. Bounded at both ends: a busy loop
#: is not a subscription, and a five-second tail is not live.
DEFAULT_EVENT_POLL_MS = 250
MIN_EVENT_POLL_MS = 50
MAX_EVENT_POLL_MS = 5000
#: Events delivered per poll tick and per event/poll call. The tail continues
#: on the next tick rather than emitting an unbounded burst.
MAX_EVENTS_PER_POLL = 500
#: Subscriptions one connection may hold.
MAX_SUBSCRIPTIONS = 32

# --- error codes ------------------------------------------------------------
#: Transport and lifecycle.
TRANSPORT_CODES = frozenset({
    "protocol_version_unsupported",
    "not_initialized",
    "already_initialized",
    "frame_too_large",
    "frame_malformed",
    "duplicate_key",
    "nonfinite_number",
    "unknown_field",
    "unknown_method",
    "invalid_params",
    "duplicate_request_id",
    "response_too_large",
    "cancelled",
    "internal_error",
})

#: Session, plan, approval and publication.
DOMAIN_CODES = frozenset({
    "unknown_session",
    "unknown_plan",
    "unknown_approval",
    "unknown_op_kind",
    "unsupported_backend",
    "plan_stale",
    "plan_not_approved",
    "plan_invalid",
    "approval_binding_mismatch",
    "approval_already_resolved",
    "region_too_large",
    "source_rejected",
    "path_escape",
    "artifact_missing",
    "candidate_hash_mismatch",
    "receipt_body_mismatch",
    "capability_unavailable",
    "publication_failed",
    "backend_refused",
    "child_python_invalid",
    "render_failed",
    "page_out_of_range",
    "unknown_subscription",
    "subscription_limit",
    "com_busy",
    "needs_hancom",
    "convert_failed",
    "not_convertible",
})

ERROR_CODES = TRANSPORT_CODES | DOMAIN_CODES

#: Per-rule outcome, unchanged from pipeline/scripts/checker_base.py:41.
RULE_STATES = ("hard", "warn", "skipped", "clean")

#: A checker row in a VerificationReport. ``unavailable`` is a first-class
#: state and is NEVER collapsed into a pass: a gate may not claim more than it
#: checked (pipeline/scripts/privacy_scan.py:16-25).
CHECK_STATES = ("ran", "unavailable", "skipped")

#: Approval states, unchanged from modules/report/scripts/pipeline_ctl.py:90.
APPROVAL_STATES = ("pending", "approved", "auto_approved", "rejected")
#: What a *client* may decide. ``auto_approved`` is deliberately absent: the
#: Runtime never fabricates human approval, exactly as ``pipeline_ctl gate``
#: refuses to (modules/report/scripts/pipeline_ctl.py:1159).
APPROVAL_DECISIONS = ("approved", "rejected")

#: The only backend this slice can execute. ``com`` and ``xml`` op kinds are
#: refused with ``unsupported_backend`` naming which backend would serve them
#: (orchestrator decision D9).
SUPPORTED_BACKENDS = ("preedit",)
KNOWN_BACKENDS = ("preedit", "xml", "com")


class RpcError(Exception):
    """A refusal that becomes exactly one error frame.

    ``data`` is passed through to the client untouched — the engine's refusals
    already carry the whole escape hatch (every run's exact text, every
    occurrence, paste-ready flags: engine/scripts/preedit.py:2694-2717) and
    flattening that to a message is what makes a caller open section.xml.
    """

    def __init__(self, code: str, message: str, **data):
        assert code in ERROR_CODES, f"undeclared error code: {code!r}"
        self.code = code
        self.message = message
        self.data = dict(data)
        super().__init__(f"{code}: {message}")

    def to_frame_error(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.data:
            payload["data"] = self.data
        return payload
