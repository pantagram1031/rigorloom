import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadModule(path, require = () => { throw new Error("Unexpected import"); }) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const exports = {};
  vm.runInNewContext(outputText, { exports, require });
  return exports;
}

const { submitComposerDraft } = loadModule("../src/workspace/composerDraft.ts");

function fixture() {
  let draft = { text: "검토할 지시문" };
  let resolve;
  let reject;
  const pending = new Promise((yes, no) => { resolve = yes; reject = no; });
  const sent = [];
  const port = {
    read: () => draft,
    write: (next) => { draft = next; },
    send: (text) => { sent.push(text); return pending; },
  };
  return { port, resolve, reject, sent };
}

test("Workspace draft survives view replacement and remains in memory", () => {
  const store = loadModule("../src/store.ts", (name) => {
    assert.equal(name, "react");
    return { useSyncExternalStore: (_subscribe, snapshot) => snapshot() };
  });
  const draft = { text: "아직 보내지 않은 문장" };
  store.setState({ composerDraft: draft });
  store.setView("agent");
  store.setView("document");
  store.setView("agent");
  assert.equal(store.getState().composerDraft, draft);
  assert.equal(store.useWorkspace((s) => s.composerDraft.text), draft.text);
});

test("success submits the captured text and leaves the owned field empty", async () => {
  const f = fixture();
  const result = submitComposerDraft(f.port);
  assert.equal(f.port.read().text, "");
  assert.deepEqual(f.sent, ["검토할 지시문"]);
  f.resolve(true);
  assert.equal(await result, true);
  assert.equal(f.port.read().text, "");
});

test("refusal restores input even after its original view unmounted", async () => {
  const f = fixture();
  const original = f.port.read();
  const result = submitComposerDraft(f.port);
  f.resolve(false);
  assert.equal(await result, false);
  assert.equal(f.port.read(), original);
});

test("late refusal cannot overwrite newer input", async () => {
  const f = fixture();
  const result = submitComposerDraft(f.port);
  f.port.write({ text: "다음 지시" });
  f.resolve(false);
  await result;
  assert.equal(f.port.read().text, "다음 지시");
});

test("late refusal respects typing followed by an intentional clear", async () => {
  const f = fixture();
  const result = submitComposerDraft(f.port);
  f.port.write({ text: "다음 지시" });
  const intentionalClear = { text: "" };
  f.port.write(intentionalClear);
  f.resolve(false);
  await result;
  assert.equal(f.port.read(), intentionalClear);
});

test("successful completion does not clear newer input", async () => {
  const f = fixture();
  const result = submitComposerDraft(f.port);
  f.port.write({ text: "다음 지시" });
  f.resolve(true);
  await result;
  assert.equal(f.port.read().text, "다음 지시");
});

test("unexpected rejection preserves the owned input", async () => {
  const f = fixture();
  const original = f.port.read();
  const result = submitComposerDraft(f.port);
  f.reject(new Error("transport failed"));
  await assert.rejects(result, /transport failed/);
  assert.equal(f.port.read(), original);
});

test("blank input is not sent or replaced", async () => {
  const f = fixture();
  const blank = { text: "  \n" };
  f.port.write(blank);
  assert.equal(await submitComposerDraft(f.port), false);
  assert.equal(f.sent.length, 0);
  assert.equal(f.port.read(), blank);
});

function loadStore() {
  return loadModule("../src/store.ts", (name) => {
    assert.equal(name, "react");
    return { useSyncExternalStore: (_subscribe, snapshot) => snapshot() };
  });
}

test("a keyless router is not blocked by a missing credential", () => {
  const store = loadStore();
  store.setState({
    activeSessionId: "s1",
    agentHost: { available: true, mode: "packaged", script: "host.py", program: null, reason: null },
    activeTurn: null,
    provider: {
      provider: "router",
      scenario: "propose-one",
      router: { baseUrl: "http://127.0.0.1:8766/v1", model: "cursor-grok-4.6-high-fast", storeKey: "RIGORLOOM_ROUTER" },
      anthropic: { model: "", storeKey: "RIGORLOOM_ANTHROPIC" },
    },
    credential: { key: "RIGORLOOM_ROUTER", state: "absent", bytes: 0 },
  });
  assert.equal(store.composerBlocker(store.getState()), null);
});

test("a router still needs a base URL", () => {
  const store = loadStore();
  store.setState({
    activeSessionId: "s1",
    agentHost: { available: true, mode: "packaged", script: "host.py", program: null, reason: null },
    activeTurn: null,
    provider: {
      provider: "router",
      scenario: "propose-one",
      router: { baseUrl: "  ", model: "m", storeKey: "RIGORLOOM_ROUTER" },
      anthropic: { model: "", storeKey: "RIGORLOOM_ANTHROPIC" },
    },
    credential: { key: "RIGORLOOM_ROUTER", state: "absent", bytes: 0 },
  });
  assert.equal(store.composerBlocker(store.getState()), "no_base_url");
});

test("anthropic still requires a stored credential", () => {
  const store = loadStore();
  store.setState({
    activeSessionId: "s1",
    agentHost: { available: true, mode: "packaged", script: "host.py", program: null, reason: null },
    activeTurn: null,
    provider: {
      provider: "anthropic",
      scenario: "propose-one",
      router: { baseUrl: "", model: "", storeKey: "RIGORLOOM_ROUTER" },
      anthropic: { model: "claude", storeKey: "RIGORLOOM_ANTHROPIC" },
    },
    credential: { key: "RIGORLOOM_ANTHROPIC", state: "absent", bytes: 0 },
  });
  assert.equal(store.composerBlocker(store.getState()), "no_credential");
});
