// Regression tests for the UX11 trust fixes: the pure rules in
// src/workspace/trust.ts and the store selectors the screens read them through.
import assert from "node:assert/strict";
import test from "node:test";

import {
  applyStep,
  applyStepLabel,
  approveBlockedReason,
  autoCharPrFor,
  baseLabel,
  behindHeadFinding,
  behindHeadMessage,
  draftProposerKind,
  filledBlankCount,
  foreignOps,
  guardTagFor,
  guardTagLabel,
  guardWarningLines,
  guardWarningSummary,
  hardReason,
  historyProvenanceLine,
  isReturnedOp,
  opSignature,
  isSupersededApproval,
  planOpsPayload,
  proposerKind,
  proposerLabel,
  restorableOps,
  savableOps,
  sheetSubjectLabel,
  shortHash,
  swapSessionDrafts,
  undoBlockReason,
  withoutSignatures,
} from "../src/workspace/trust.ts";
import {
  EMPTY_DRAFT,
  activeDisplayText,
  canRequestApproval,
  composerBlocker,
  getState,
  returnedDraftOps,
  setState,
} from "../src/store.ts";

const LATIN = /[A-Za-z]/;

// --- 1. stale proposal ----------------------------------------------------------

test("a plan behind the head is named with the revision it would drop", () => {
  const validation = {
    ok: false,
    hard: [{ code: "plan_behind_head", msg: "x", at: "plan", baseRunId: null, headRunId: "run-1" }],
  };
  const finding = behindHeadFinding(validation);
  assert.equal(finding.code, "plan_behind_head");
  const text = behindHeadMessage(finding, (runId) => (runId === "run-1" ? 1 : null), "ko");
  assert.match(text, /수정본 1 이전 문서/);
  assert.match(text, /수정본 1 변경 내용이 빠집니다/);
  assert.equal(behindHeadFinding({ ok: true, hard: [] }), null);
  assert.equal(
    approveBlockedReason({ hardCount: 1, returnedCount: 0, behindHead: true }, "ko"),
    "최신 수정본 기준으로 다시 제안해야 승인할 수 있습니다",
  );
});

test("an approval the runtime superseded reads as superseded, not as a person's return", () => {
  assert.equal(
    isSupersededApproval({ state: "rejected", reasonCode: "superseded_by_newer_candidate" }),
    true,
  );
  assert.equal(isSupersededApproval({ state: "rejected", reason: "고쳐 주세요" }), false);
});

// --- 2. no silent mock -------------------------------------------------------------

test("a test agent's proposal is labelled as a test proposal everywhere", () => {
  // The runtime's provenance decides it; a proposer name is only a label.
  assert.equal(proposerKind("agenthost-mock"), "agent");
  assert.equal(proposerKind("anything", "mock"), "mock");
  assert.equal(proposerKind("rigorloom-desktop"), "user");
  assert.equal(proposerKind("claude-agent"), "agent");
  assert.equal(proposerLabel("mock", "ko"), "시험용 제안");
  assert.equal(proposerLabel("agent", "ko"), "에이전트");
  assert.equal(proposerLabel("user", "ko"), "직접 입력");
  const draft = {
    ops: [
      { origin: "user" },
      { origin: "agent", proposer: "agenthost-mock", provenance: "mock" },
    ],
  };
  assert.equal(draftProposerKind(draft), "mock");
  assert.equal(draftProposerKind({ ops: [{ origin: "agent", proposer: "x" }] }), "agent");
  const history = historyProvenanceLine(
    { proposer: "agenthost-mock", provenance: "mock", receiptCheck: "verified", acceptance: true },
    "ko",
  );
  assert.equal(history, "제안: 시험용 제안 · 영수증을 확인했습니다");
  assert.equal(LATIN.test(history), false);
});

test("with no real provider and no developer setting the request box is not connected", () => {
  const before = getState();
  try {
    setState({
      activeSessionId: "s1",
      activeTurn: null,
      agentHost: { available: true, mockAllowed: false },
      provider: { ...before.provider, provider: "mock" },
    });
    assert.equal(composerBlocker(getState()), "agent_not_connected");
    setState({ agentHost: { available: true } });
    assert.equal(composerBlocker(getState()), "agent_not_connected");
    setState({ agentHost: { available: true, mockAllowed: true } });
    assert.equal(composerBlocker(getState()), null);
  } finally {
    setState({
      activeSessionId: before.activeSessionId,
      agentHost: before.agentHost,
      provider: before.provider,
    });
  }
});

// --- 3. drafts belong to one document ---------------------------------------------

test("switching documents parks the queue and never shows it on the other document", () => {
  const draftA = { ...EMPTY_DRAFT, sessionId: "A", ops: [{ opId: "o1", text: "기획조정실" }] };
  const approvalA = { approvalId: "ap-A", state: "pending" };
  let { parked, slot } = swapSessionDrafts(
    {},
    { draft: draftA, approval: approvalA, approvalPhase: "pending", redoStack: [] },
    "B",
    EMPTY_DRAFT,
  );
  assert.equal(slot.draft, EMPTY_DRAFT);
  assert.equal(slot.approval, null);
  assert.equal(parked.A.draft, draftA);

  ({ parked, slot } = swapSessionDrafts(parked, slot, "A", EMPTY_DRAFT));
  assert.equal(slot.draft, draftA);
  assert.equal(slot.approval, approvalA);
  assert.equal(parked.A, undefined);
});

test("a draft that already leaked is parked under the session it names", () => {
  const leaked = { ...EMPTY_DRAFT, sessionId: "A", ops: [{ opId: "o1", text: "AGENT-HOST-0001" }] };
  const { parked, slot } = swapSessionDrafts(
    {},
    { draft: leaked, approval: null, approvalPhase: "idle", redoStack: [] },
    "C",
    EMPTY_DRAFT,
  );
  assert.equal(slot.draft.ops.length, 0);
  assert.equal(parked.A.draft, leaked);
  assert.deepEqual(
    foreignOps(leaked, "C").map((op) => op.opId),
    ["o1"],
    "a re-propose on C refuses ops made for A",
  );
  assert.deepEqual(foreignOps(leaked, "A"), []);
});

// --- 4. the head is what the person sees ------------------------------------------

test("after approval the page and the fill counter stand on the head 수정본", () => {
  const source = [
    { table: 0, addr: { row: 5, col: 1 }, text: "" },
    { table: 0, addr: { row: 5, col: 2 }, text: "(서명)" },
  ];
  const head = [
    { table: 0, addr: { row: 5, col: 1 }, text: "기획조정실" },
    { table: 0, addr: { row: 5, col: 2 }, text: "(서명)" },
  ];
  const keys = ["c:0:5:1", "c:0:5:2", "c:0:6:1"];
  assert.equal(filledBlankCount(keys, [], source, null), 0);
  assert.equal(filledBlankCount(keys, [], source, head), 1, "the placeholder is not an entry");
  assert.equal(
    filledBlankCount(keys, [{ kind: "fill_cell", table: 0, row: 6, col: 1, text: "x" }], source, head),
    2,
  );

  assert.match(
    sheetSubjectLabel({ mode: "review", hasChanges: false, headRevision: 1, showingOriginal: false }, "ko"),
    /^수정본 1 \(현재\) · 미리보기/,
  );
  assert.match(
    sheetSubjectLabel({ mode: "fill", hasChanges: false, headRevision: 2, showingOriginal: true }, "ko"),
    /^원본 · 미리보기/,
  );
  assert.match(
    sheetSubjectLabel({ mode: "review", hasChanges: true, headRevision: 1, showingOriginal: false }, "ko"),
    /^수정본 1에 제안을 적용한 모습/,
  );

  const before = getState();
  try {
    setState({
      activeSessionId: "S",
      head: "run-1",
      candidates: { S: [{ runId: "run-1", createdUtc: "2026-11-19T00:00:00Z" }] },
      texts: { S: source },
      headTexts: { "S:run-1": head },
      showOriginal: false,
    });
    assert.equal(activeDisplayText(getState()), head);
    setState({ showOriginal: true });
    assert.equal(activeDisplayText(getState()), source, "원본 보기 is a toggle");
  } finally {
    setState({
      activeSessionId: before.activeSessionId,
      head: before.head,
      candidates: before.candidates,
      texts: before.texts,
      headTexts: before.headTexts,
      showOriginal: before.showOriginal,
    });
  }
});

// --- 5. guard visibility -------------------------------------------------------------

const DATE_PARA = {
  paragraph: 7,
  pass: false,
  kinds: ["dates"],
  changes: [{ kind: "dates", before: { "2026년 1월 1일": 1 }, after: { "2027년 1월 1일": 1 } }],
  before: "계약 기간 2026년 1월 1일",
  after: "계약 기간 2027년 1월 1일",
};
const GUIDE_PARA = {
  paragraph: 3,
  pass: false,
  kinds: ["direct_quotes", "qualifiers"],
  changes: [
    { kind: "direct_quotes", before: { "“행정기관명”": 1 }, after: {} },
    { kind: "qualifiers", before: { "아니": 1 }, after: {} },
  ],
  before: "", after: "",
};
const NEW_PARA = {
  paragraph: 12,
  pass: false,
  kinds: ["numbers"],
  changes: [{ kind: "numbers", before: {}, after: { "2026": 1 } }],
  before: "", after: "",
};

test("every failing guard paragraph is tagged on its row, true changes stay 바뀐 사실", () => {
  const fill = { op: { kind: "fill_cell" } };
  assert.equal(guardTagFor(fill, { status: "changed", paragraph: DATE_PARA }).kind, "changed");
  const removed = guardTagFor({ op: { kind: "delete_guides" } }, { status: "none", paragraph: GUIDE_PARA });
  assert.equal(removed.kind, "removed_with_guide");
  assert.equal(guardTagLabel(removed, "ko"), "안내문과 함께 빠진 표현");
  const added = guardTagFor(fill, { status: "none", paragraph: NEW_PARA });
  assert.equal(added.kind, "new_values");
  assert.equal(guardTagLabel(added, "ko"), "새로 넣은 숫자·날짜");
  assert.equal(guardTagFor(fill, { status: "kept", paragraph: { ...NEW_PARA, pass: true } }), null);
  assert.equal(guardTagFor(fill, { status: "none", paragraph: null }), null);
});

test("the approval dialog lists guard warnings in two lines with the actual values", () => {
  const changes = [
    { opId: "a", ordinal: 1, fieldLabel: "계약 시작일", op: { kind: "fill_cell" } },
    { opId: "b", ordinal: 3, fieldLabel: "행정기관명", op: { kind: "delete_guides" } },
    { opId: "c", ordinal: 12, fieldLabel: "시행일", op: { kind: "fill_cell" } },
  ];
  const audits = {
    a: { status: "changed", paragraph: DATE_PARA },
    b: { status: "none", paragraph: GUIDE_PARA },
    c: { status: "none", paragraph: NEW_PARA },
  };
  const summary = guardWarningSummary(changes, audits, "ko");
  const lines = guardWarningLines(summary, "ko");
  assert.equal(lines.length, 2, "one or two lines, never a wall");
  assert.match(lines[0], /^바뀐 사실 1곳: \[1\] 계약 시작일 날짜 ‘2026년 1월 1일’ → ‘2027년 1월 1일’\.$/);
  assert.match(lines[1], /^안내문과 함께 빠지는 표현 1곳: \[3\] 행정기관명 인용문 ‘“행정기관명”’, 부정·한정 표현 ‘아니’\.$/);
});

// --- 6. dialog semantics -------------------------------------------------------------

test("hashes shorten to 12 characters and the base line names 원본 or 수정본 N", () => {
  const hash = "a".repeat(64);
  assert.equal(shortHash(hash), "a".repeat(12));
  assert.equal(shortHash(null), "—");
  assert.equal(baseLabel(null, () => null, "ko"), "원본");
  assert.equal(baseLabel("run-2", () => 2, "ko"), "수정본 2");
});

test("the busy dialog names the step it is on", () => {
  assert.equal(applyStep({ submitting: true, approvalPhase: "idle", applyPhase: "idle" }), "checking");
  assert.equal(applyStep({ submitting: true, approvalPhase: "resolving", applyPhase: "idle" }), "recording");
  assert.equal(applyStep({ submitting: true, approvalPhase: "idle", applyPhase: "starting" }), "applying");
  assert.equal(
    applyStepLabel("applying", "ko"),
    "수정본을 만들고 점검하는 중입니다",
  );
  assert.equal(applyStepLabel(null, "ko"), null);
});

// --- 7. persistence ------------------------------------------------------------------

test("only the person's typed entries are saved and restored", () => {
  const draft = {
    ops: [
      { opId: "u", kind: "fill_cell", text: "기획조정실", origin: "user", table: 0, row: 5, col: 1 },
      { opId: "a", kind: "fill_cell", text: "AGENT", origin: "agent", table: 0, row: 6, col: 1 },
    ],
  };
  const saved = { ops: savableOps(draft), savedUtc: "2026-11-19T00:00:00Z" };
  assert.deepEqual(saved.ops.map((op) => op.opId), ["u"]);
  const roundTrip = restorableOps(JSON.parse(JSON.stringify(saved)));
  assert.deepEqual(roundTrip.map((op) => op.text), ["기획조정실"]);
  assert.deepEqual(restorableOps({ ops: [{ opId: "x", kind: "fill_cell", text: "t", origin: "agent" }] }), []);
  assert.deepEqual(restorableOps(null), []);
});

// --- 8. character shape -------------------------------------------------------------

test("typing into a superscript blank takes the suggested body shape, hard reasons are readable", () => {
  assert.equal(autoCharPrFor({ scriptAnomaly: true, charPrSuggested: "7" }, undefined), "7");
  assert.equal(autoCharPrFor({ scriptAnomaly: true, charPrSuggested: "7" }, "9"), null);
  assert.equal(autoCharPrFor({ scriptAnomaly: false, charPrSuggested: "7" }, undefined), null);
  assert.equal(
    hardReason([{ code: "fill_charpr_script_anomaly", msg: "preserving this run's charPr", at: "x" }], "ko"),
    "위첨자나 아래첨자 서식이 있는 칸입니다. 글자 크기 확인이 필요합니다.",
  );
  assert.equal(
    approveBlockedReason({ hardCount: 1, returnedCount: 0, behindHead: false }, "ko"),
    "1건을 고쳐야 승인할 수 있습니다",
  );
});

// --- 9. returned changes --------------------------------------------------------------

test("a returned change is recognised in a later proposal and blocks approval until handled", () => {
  const returnedOp = { opId: "x1", kind: "fill_cell", table: 0, row: 1, col: 4, text: "AGENT-HOST-0001", origin: "agent" };
  const again = { ...returnedOp, opId: "other-id" };
  const typed = { opId: "u1", kind: "fill_cell", table: 0, row: 5, col: 1, text: "기획조정실", origin: "user" };
  const sigs = [opSignature(returnedOp)];
  assert.equal(isReturnedOp(again, sigs), true);
  assert.equal(isReturnedOp(typed, sigs), false);
  assert.deepEqual(withoutSignatures(sigs, [again]), [], "다시 넣기 clears it");

  const before = getState();
  try {
    setState({
      activeSessionId: "S",
      returnedOps: { S: sigs },
      draft: {
        ...EMPTY_DRAFT,
        sessionId: "S",
        ops: [again, typed],
        plan: { planId: "p", planHash: "h", boundSha256: "b" },
        boundSha256: "b",
        validation: { ok: true, stale: false, hard: [], boundSha256: "b", currentSha256: "b" },
        phase: "ready",
      },
      approvalPhase: "idle",
      applyPhase: "idle",
    });
    assert.deepEqual(returnedDraftOps(getState()).map((op) => op.opId), ["other-id"]);
    assert.equal(
      returnedDraftOps(getState()),
      returnedDraftOps(getState()),
      "reference-stable, or useSyncExternalStore loops (React #185)",
    );
    assert.equal(canRequestApproval(getState()), false);
    assert.equal(
      approveBlockedReason({ hardCount: 0, returnedCount: 1, behindHead: false }, "ko"),
      "돌려보낸 변경 1건을 빼거나 다시 넣어야 승인할 수 있습니다",
    );
    setState({ returnedOps: { S: [] } });
    assert.equal(canRequestApproval(getState()), true);
  } finally {
    setState({
      activeSessionId: before.activeSessionId,
      returnedOps: before.returnedOps,
      draft: before.draft,
      approvalPhase: before.approvalPhase,
      applyPhase: before.applyPhase,
    });
  }
});

// --- 10. revert proposals ---------------------------------------------------------------

test("an undo whose dry run fails validation is refused with the reason", () => {
  assert.equal(undoBlockReason({ ok: true, hard: [] }, "ko"), null);
  const text = undoBlockReason(
    { ok: false, hard: [{ code: "fill_charpr_script_anomaly" }, { code: "cell_address_unknown" }] },
    "ko",
  );
  assert.match(text, /^되돌리기 제안을 만들지 않았습니다\./);
  assert.match(text, /위첨자나 아래첨자/);
  assert.deepEqual(
    planOpsPayload([
      { opId: "u", kind: "fill_cell", table: 0, row: 1, col: 2, text: "a", overwrite: true, before: "b", origin: "user" },
      { opId: "r", kind: "set_run", atPara: 3, run: 0, text: "x", before: "y", origin: "user" },
    ]),
    [
      { opId: "u", kind: "fill_cell", table: 0, row: 1, col: 2, text: "a", overwrite: true },
      { opId: "r", kind: "set_run", atPara: 3, run: 0, text: "x" },
    ],
  );
});

// --- 11. history ----------------------------------------------------------------------------

test("history names proposer and receipt state without English", () => {
  for (const receiptCheck of ["verified", "failed", "pending"]) {
    const line = historyProvenanceLine(
      { proposer: "rigorloom-desktop", provenance: null, receiptCheck, acceptance: false },
      "ko",
    );
    assert.equal(LATIN.test(line), false, line);
    assert.match(line, /^제안: 직접 입력 · /);
    assert.match(line, /자동 점검에서 확인할 항목이 남아 있습니다$/);
  }
});
