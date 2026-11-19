// v1 stays the default; editor v2 is opt-in with ?ui=v2 or the devEditorV2
// developer preference, and ?ui=v1 always wins.
import assert from "node:assert/strict";
import test from "node:test";

const v = await import("../src/uiVariant.ts");

test("the address names a variant only with ui=v1 or ui=v2", () => {
  assert.equal(v.uiVariantFromQuery(""), null);
  assert.equal(v.uiVariantFromQuery("?ui=v2"), "v2");
  assert.equal(v.uiVariantFromQuery("?token=x&ui=v1"), "v1");
  assert.equal(v.uiVariantFromQuery("?ui=v3"), null);
});

test("v1 is the default, and the developer preference opts into v2", () => {
  assert.equal(v.resolveUiVariant(null, null), "v1");
  assert.equal(v.resolveUiVariant(null, {}), "v1");
  assert.equal(v.resolveUiVariant(null, { devEditorV2: "true" }), "v1");
  assert.equal(v.resolveUiVariant(null, { [v.EDITOR_V2_PREF]: true }), "v2");
});

test("the address wins over the preference", () => {
  assert.equal(v.resolveUiVariant("v1", { devEditorV2: true }), "v1");
  assert.equal(v.resolveUiVariant("v2", {}), "v2");
});
