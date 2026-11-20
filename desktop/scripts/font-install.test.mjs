import assert from "node:assert/strict";
import test from "node:test";

import { FONT_SOURCE_LINK, substitutedFontRows } from "../src/model/fontInstall.ts";
import hancomFontSource from "../src/model/hancomFontSource.json" with { type: "json" };

test("font guidance uses one fixed HTTPS host and safe external anchor attributes", () => {
  assert.equal(FONT_SOURCE_LINK.href, hancomFontSource);
  const url = new URL(FONT_SOURCE_LINK.href);
  assert.equal(url.origin, "https://www.hancom.com");
  assert.equal(url.username + url.password, "");
  assert.equal(FONT_SOURCE_LINK.target, "_blank");
  assert.equal(FONT_SOURCE_LINK.rel, "noopener noreferrer");
  substitutedFontRows([{ declared: "https://example.invalid", drawnWith: null, state: "unknown" }], () => null);
  assert.equal(FONT_SOURCE_LINK.href, hancomFontSource);
});

test("show substitutions from the renderer with a fallback only when it is known", () => {
  const rows = [
    { declared: "함초롬바탕", drawnWith: "Noto Serif CJK KR", state: "missing" },
    { declared: "함초롬돋움", drawnWith: null, state: "unknown" },
    { declared: "한컴바탕", drawnWith: "Nanum Myeongjo", state: "installed" },
  ];
  assert.deepEqual(substitutedFontRows(rows, () => "Nanum Gothic"), [
    rows[0], { ...rows[1], drawnWith: "Nanum Gothic" },
  ]);
  assert.deepEqual(substitutedFontRows(rows, () => null), rows.slice(0, 2));
});
