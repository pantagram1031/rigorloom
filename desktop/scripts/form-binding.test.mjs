import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";

const nodeRequire = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const welcomeSource = readFileSync(new URL("../src/components/Welcome.tsx", import.meta.url), "utf8");
const mockSource = readFileSync(new URL("../src/devMock.ts", import.meta.url), "utf8");

function compile(relPath, fileName) {
  const source = readFileSync(new URL(relPath, import.meta.url), "utf8");
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2021,
      jsx: ts.JsxEmit.ReactJSX,
    },
    fileName,
  }).outputText;
}

function sameShape(actual, expected) {
  assert.equal(JSON.stringify(actual), JSON.stringify(expected));
}

function helpers() {
  const start = actionsSource.indexOf("const sessionFormBindings");
  const end = actionsSource.indexOf("const SUPPORTED = ");
  assert.ok(start >= 0 && end > start, "form-binding action slice moved");
  const code = stripTypeScriptTypes(actionsSource.slice(start, end)).replaceAll("export ", "");
  const calls = [];
  const picks = [];
  let state = {
    sessions: [
      {
        sessionId: "s1",
        source: { name: "doc.hwpx", sha256: "aa".repeat(32), bytes: 10, documentKind: "hwpx" },
      },
    ],
    openedPaths: {},
    recents: [],
    activeSessionId: null,
  };
  const ctx = vm.createContext({
    Map,
    Date,
    JSON,
    MAX_RECENTS: 8,
    picks,
    openFileDialog: async () => picks.shift() ?? null,
    rt: {
      openPath: async (path, binding) => {
        calls.push({ path, binding });
        return {
          sessionId: "s1",
          openedUtc: "2026-09-17T00:00:00Z",
          source: state.sessions[0].source,
        };
      },
      savePrefs: async () => {},
      asRuntimeError: (error) => error,
    },
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    refreshSessions: async () => {},
    selectSession: async (id) => {
      ctx.rememberRecent(id);
    },
    showToast: () => {},
  });
  vm.runInContext(
    `${code}
globalThis.formBindingFromPath = formBindingFromPath;
globalThis.openPathParams = openPathParams;
globalThis.needsBoundFormHint = needsBoundFormHint;
globalThis.rememberRecent = rememberRecent;
globalThis.openPath = openPath;
globalThis.bindFormAndOpen = bindFormAndOpen;
globalThis.openViaDialog = openViaDialog;`,
    ctx,
  );
  return { ctx, calls, picks, read: () => state };
}

function renderHome(state) {
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/Welcome.tsx", "Welcome.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return { openPath: () => {}, openViaDialog: () => {}, bindFormAndOpen: () => {} };
      }
      if (id === "../store") {
        return { useWorkspace: (selector) => selector(state), setState: () => {} };
      }
      if (id === "../types") return {};
      if (id === "./Logo") {
        return { Logo: () => React.createElement("svg", { "data-testid": "logo" }) };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(React.createElement(module.exports.Home));
}

function renderVerification(inspect) {
  const state = {
    status: { running: true, initialized: true, pid: 1, mode: "dev", jobConfined: true },
    checkPhase: "idle",
    findings: [],
    checkedAt: null,
    sheetOpen: false,
    applied: null,
    candidateVerdict: null,
    exportPhase: "idle",
    exportResult: null,
    exportError: null,
    reopened: null,
    draft: { ops: [] },
    centerMode: "text",
    page: 1,
    render: null,
    selection: null,
    overlayPick: null,
    geometry: null,
    inlineEdit: null,
    verifyDetailsOpen: true,
  };
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/VerificationBar.tsx", "VerificationBar.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return {
          exportApplied: () => {},
          openReceipt: () => {},
          reopenExported: () => {},
          runCheck: () => {},
        };
      }
      if (id === "../store") {
        return { useWorkspace: (selector) => selector(state), setState: () => {} };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ children, title }) => React.createElement("span", { title }, children),
        };
      }
      if (id === "./Icon") return { Icon };
      if (id === "../verifyReport") {
        return { worstVerifyVerdict: () => null, verifyTargetLabel: () => "원본" };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(
    React.createElement(module.exports.VerificationBar, {
      session: {
        sessionId: "s",
        openedUtc: "",
        source: { name: "문서.hwpx", documentKind: "hwpx", bytes: 1, sha256: "abc" },
      },
      inspect,
      candidates: [],
    }),
  );
}

function renderReceipt(receipt) {
  const state = { receiptOpen: "run-A", receipts: { "run-A": receipt }, receiptError: null };
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/ReceiptPanel.tsx", "ReceiptPanel.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") return { openReceipt: () => {} };
      if (id === "../store") return { useWorkspace: (selector) => selector(state), showToast: () => {} };
      if (id === "../label") {
        return {
          formatBytes: (n) => `${n} B`,
          humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
          humanTableLabel: (t) => `표 ${t + 1}`,
          quoteKo: (s) => `「${s}」`,
          shortHash: (v, n = 12) => String(v ?? "").slice(0, n),
          stampWhen: (iso) => (iso ? String(iso).replace("T", " ").slice(0, 16) : ""),
        };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
        };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(React.createElement(module.exports.ReceiptPanel));
}

function receiptFixture(residue) {
  return {
    source: { name: "a.hwpx", sha256: "aa".repeat(32), bytes: 10 },
    candidate: { path: "c.hwpx", sha256: "bb".repeat(32), bytes: 11, role: "candidate" },
    backend: "xml",
    planHash: "cc".repeat(32),
    steps: [{ opId: "op-1", kind: "replace_all", subcommand: "edit", exitCode: 0 }],
    approval: {
      state: "approved",
      approver: "host",
      requestedBy: "desktop",
      resolvedUtc: "2026-09-17T00:00:00Z",
      planHash: "cc".repeat(32),
    },
    checks: {
      acceptance: true,
      ranAll: true,
      reason: null,
      checks: [{ checker: "check_residue", state: "ran", ok: true }],
      note: "offline",
    },
    evidence: { class: "structural_only", note: "no render" },
    residue,
  };
}

function renderReview(inspect) {
  const state = {
    view: "document",
    inspectorTab: "review",
    inspectorTabUserSet: true,
    selection: null,
    draft: { ops: [] },
    approvalPhase: "idle",
    turns: [],
    candidates: {},
    activeSessionId: "s",
  };
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/ContextPanel.tsx", "ContextPanel.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return {
          beginEdit: () => {},
          bindFormToActiveDocument: () => {},
          needsBoundFormHint: (value) => {
            const forbidden = value?.forbidden;
            if (!forbidden || forbidden.residue?.profileSource !== "self_derived") return false;
            return (forbidden.placeholders?.length ?? -1) === 0;
          },
        };
      }
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          selectionId: () => "none",
          visibleInspectorTab: () => "review",
          selectInspectorTab: () => {},
          markAgentTurnsSeen: () => {},
          markHistoryCandidatesSeen: () => {},
          inspectorHistoryBadge: () => 0,
          inspectorAgentUnread: () => 0,
        };
      }
      if (id === "../types") return {};
      if (id === "../label") {
        return {
          humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
          humanTableLabel: (t) => `표 ${t + 1}`,
          machineTableIndex: (t) => `table ${t}`,
          humanSelectionLabel: (s) => (s ? "선택됨" : "선택 없음"),
        };
      }
      if (id === "./History") return { History: () => null };
      if (id === "./ReviewQueue") {
        return { ReviewQueue: () => null, ApproveAllButton: () => null };
      }
      if (id === "./Composer") return { Composer: () => null };
      if (id === "./Conversation") return { Conversation: () => null };
      if (id === "./DocumentContext") return { DocumentContext: () => null };
      if (id === "./Tag") {
        return { Tag: ({ children }) => React.createElement("span", null, children) };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(
    React.createElement(module.exports.ContextPanel, { inspect, status: null }),
  );
}

const boundRecent = {
  path: "C:\\forms\\보고서.hwpx",
  name: "보고서.hwpx",
  sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  bytes: 12,
  openedUtc: "2026-09-17T00:04:00Z",
  documentKind: "hwpx",
  formBinding: { kind: "profile", path: "C:\\forms\\blank_profile.json" },
};

test("openPathParams sends formProfile for json and form for hwpx", () => {
  const { ctx } = helpers();
  sameShape(ctx.formBindingFromPath("p.json"), { kind: "profile", path: "p.json" });
  sameShape(ctx.openPathParams("doc.hwpx", ctx.formBindingFromPath("p.json")), {
    path: "doc.hwpx",
    formProfile: "p.json",
  });
  sameShape(ctx.openPathParams("doc.hwpx", ctx.formBindingFromPath("blank.hwpx")), {
    path: "doc.hwpx",
    form: "blank.hwpx",
  });
});

test("openPath receives formProfile from the Home action", async () => {
  const { ctx, calls, picks } = helpers();
  picks.push("C:\\docs\\보고서.hwpx", "C:\\forms\\blank_profile.json");
  await ctx.bindFormAndOpen();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "C:\\docs\\보고서.hwpx");
  sameShape(calls[0].binding, {
    kind: "profile",
    path: "C:\\forms\\blank_profile.json",
  });
  assert.match(welcomeSource, /data-testid="home-bind-form"/);
  assert.match(welcomeSource, /bindFormAndOpen/);
});

test("recents keep the form binding and Home shows a 양식 tag", async () => {
  const { ctx, picks, read } = helpers();
  picks.push("C:\\docs\\보고서.hwpx", "C:\\forms\\blank_profile.json");
  await ctx.bindFormAndOpen();
  const recent = read().recents[0];
  assert.equal(recent.path, "C:\\docs\\보고서.hwpx");
  sameShape(recent.formBinding, {
    kind: "profile",
    path: "C:\\forms\\blank_profile.json",
  });
  const html = renderHome({ recents: [boundRecent], dragOver: false, inspectError: null });
  assert.match(html, /data-testid="recent-form-tag"/);
  assert.match(html, />양식</);
  assert.match(html, /data-testid="home-bind-form"/);
  assert.match(mockSource, /formBinding/);
  assert.match(mockSource, /profileSource: "bound_form"/);
});

test("popover 판정 기준 renders bound_form and self_derived", () => {
  const bound = renderVerification({
    documentHash: "abc",
    summary: { fillTargetCount: 1 },
    regions: { regions: [] },
    forbidden: {
      anchors: [],
      placeholders: [{ text: "[제목]" }],
      removalTargets: [],
      counts: { anchors: 0, placeholders: 1, removalTargets: 0 },
      residue: { profileSource: "bound_form", sha256: "abcdef0123456789" },
    },
  });
  assert.match(bound, /data-testid="verify-judgement-source"/);
  assert.match(bound, /연결된 양식 \(abcdef012345\)/);
  const derived = renderVerification({
    documentHash: "abc",
    summary: { fillTargetCount: 0 },
    regions: { regions: [] },
    forbidden: {
      anchors: [],
      placeholders: [],
      removalTargets: [],
      counts: { anchors: 0, placeholders: 0, removalTargets: 0 },
      residue: { profileSource: "self_derived", sha256: "ffff", note: "heuristic" },
    },
  });
  assert.match(derived, /문서 자체 추정/);
  assert.match(derived, /휴리스틱/);
});

test("ReceiptPanel shows profileSource and the keep declaration", () => {
  const html = renderReceipt(
    receiptFixture({
      profileSource: "bound_form",
      sha256: "deadbeefcafebabe",
      declaration: { keep: ["학번", "이름"] },
    }),
  );
  assert.match(html, /data-testid="receipt-residue"/);
  assert.match(html, /연결된 양식 \(deadbeefcafe\)/);
  assert.match(html, /data-testid="receipt-declaration-keep"/);
  assert.match(html, /학번, 이름/);
});

test("form-bind hint appears only for self_derived with zero placeholders", () => {
  const hint = renderReview({
    forbidden: {
      placeholders: [],
      residue: { profileSource: "self_derived" },
    },
  });
  assert.match(hint, /data-testid="form-bind-hint"/);
  assert.match(hint, /이 문서는 완성본으로 보입니다\. 양식을 연결하면 검사 판정이 정확해집니다/);
  assert.match(hint, /data-testid="review-bind-form"/);

  const bound = renderReview({
    forbidden: {
      placeholders: [],
      residue: { profileSource: "bound_form" },
    },
  });
  assert.doesNotMatch(bound, /data-testid="form-bind-hint"/);

  const unfinished = renderReview({
    forbidden: {
      placeholders: [{ text: "[제목]" }],
      residue: { profileSource: "self_derived" },
    },
  });
  assert.doesNotMatch(unfinished, /data-testid="form-bind-hint"/);
});
