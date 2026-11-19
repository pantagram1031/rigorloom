import assert from "node:assert/strict";
import test from "node:test";

const {
  composerDraftAfterSend,
  composerDraftOf,
  getState,
  setComposerDraft,
  setState,
  setView,
  sharedStateSignature,
} = await import("../src/store.ts");

/** What the composer shows: the active document's draft. */
const shownDraft = () => composerDraftOf().text;

test("an unsent composer draft survives a document-view round trip", () => {
  const before = getState();
  const original = {
    view: before.view,
    editIntentGeneration: before.editIntentGeneration,
  };
  const originalDraft = shownDraft();

  try {
    setState({ view: "agent" });
    setComposerDraft("검토할 표를 먼저 찾아 주세요.");
    const expected = sharedStateSignature();

    // Prove the signature actually covers this field; otherwise equality
    // across the round trip could pass while the user-visible draft vanished.
    setComposerDraft("다른 지시");
    assert.notEqual(sharedStateSignature(), expected);
    setComposerDraft("검토할 표를 먼저 찾아 주세요.");

    setView("document");
    assert.equal(shownDraft(), "검토할 표를 먼저 찾아 주세요.");
    assert.equal(sharedStateSignature(), expected);

    setView("agent");
    assert.equal(shownDraft(), "검토할 표를 먼저 찾아 주세요.");
    assert.equal(sharedStateSignature(), expected);
  } finally {
    setState(original);
    setComposerDraft(originalDraft);
  }
});

test("an unsent draft stays with the document it was typed for", () => {
  const before = getState().activeSessionId;
  try {
    setState({ activeSessionId: "doc-A" });
    setComposerDraft("A 문서의 수신자를 고쳐 주세요.");
    setState({ activeSessionId: "doc-B" });
    // Document B opens with its own, empty composer: A's instruction is not
    // shown there, and a send there cannot carry it.
    assert.equal(shownDraft(), "");
    setComposerDraft("B 문서 지시");
    setState({ activeSessionId: "doc-A" });
    assert.equal(shownDraft(), "A 문서의 수신자를 고쳐 주세요.");
    assert.equal(composerDraftOf("doc-B").text, "B 문서 지시");
  } finally {
    setState({ activeSessionId: before });
  }
});

test("a late send completion never overwrites newer composer work", () => {
  const sent = "첫 번째 지시";
  assert.equal(composerDraftAfterSend("", sent, false), sent);
  assert.equal(composerDraftAfterSend("다음 지시", sent, false), "다음 지시");
  assert.equal(composerDraftAfterSend("", sent, true), "");
  assert.equal(composerDraftAfterSend("다음 지시", sent, true), "다음 지시");
});
