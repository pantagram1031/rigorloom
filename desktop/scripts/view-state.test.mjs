import assert from "node:assert/strict";
import test from "node:test";

const {
  composerDraftAfterSend,
  getState,
  setComposerDraft,
  setState,
  setView,
  sharedStateSignature,
} = await import("../src/store.ts");

test("an unsent composer draft survives a document-view round trip", () => {
  const before = getState();
  const original = {
    view: before.view,
    composerDraft: before.composerDraft,
    editIntentGeneration: before.editIntentGeneration,
  };

  try {
    setState({ view: "agent", composerDraft: "검토할 표를 먼저 찾아 주세요." });
    const expected = sharedStateSignature();

    // Prove the signature actually covers this field; otherwise equality
    // across the round trip could pass while the user-visible draft vanished.
    setComposerDraft("다른 지시");
    assert.notEqual(sharedStateSignature(), expected);
    setComposerDraft("검토할 표를 먼저 찾아 주세요.");

    setView("document");
    assert.equal(getState().composerDraft, "검토할 표를 먼저 찾아 주세요.");
    assert.equal(sharedStateSignature(), expected);

    setView("agent");
    assert.equal(getState().composerDraft, "검토할 표를 먼저 찾아 주세요.");
    assert.equal(sharedStateSignature(), expected);
  } finally {
    setState(original);
  }
});

test("a late send completion never overwrites newer composer work", () => {
  const sent = "첫 번째 지시";
  assert.equal(composerDraftAfterSend("", sent, false), sent);
  assert.equal(composerDraftAfterSend("다음 지시", sent, false), "다음 지시");
  assert.equal(composerDraftAfterSend("", sent, true), "");
  assert.equal(composerDraftAfterSend("다음 지시", sent, true), "다음 지시");
});
