import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const {
  moveRoving,
  typeaheadIndex,
  trapTabIndex,
  isActivateKey,
  isPrintableTypeahead,
} = await import("../src/ui/roving.ts");
const { placeLayer } = await import("../src/ui/place.ts");
const { cn } = await import("../src/ui/cn.ts");

test("menu arrows wrap, Home/End, typeahead by first letter", () => {
  assert.equal(moveRoving(3, 0, "ArrowDown"), 1);
  assert.equal(moveRoving(3, 2, "ArrowDown"), 0);
  assert.equal(moveRoving(3, 0, "ArrowUp"), 2);
  assert.equal(moveRoving(4, 2, "Home"), 0);
  assert.equal(moveRoving(4, 1, "End"), 3);
  assert.equal(typeaheadIndex(["열기", "저장", "설정"], 0, "설"), 2);
  assert.equal(typeaheadIndex(["Open", "Save", "Settings"], 0, "s"), 1);
  const src = readFileSync(new URL("../src/ui/DropdownMenu.tsx", import.meta.url), "utf8");
  assert.match(src, /moveRoving/);
  assert.match(src, /typeaheadIndex/);
  assert.match(src, /useLayer/);
});

test("dialog trap Tab wraps and Esc is handled in useLayer", () => {
  assert.equal(trapTabIndex(3, 0, true), 2);
  assert.equal(trapTabIndex(3, 2, false), 0);
  assert.equal(trapTabIndex(3, 1, false), null);
  const layer = readFileSync(new URL("../src/ui/useLayer.ts", import.meta.url), "utf8");
  assert.match(layer, /Escape/);
  assert.match(layer, /trapTabIndex/);
  assert.match(layer, /overflow/);
  assert.match(layer, /focus\(\)/);
  const dialog = readFileSync(new URL("../src/ui/Dialog.tsx", import.meta.url), "utf8");
  assert.match(dialog, /modal:\s*true/);
});

test("switch activate key is Space/Enter", () => {
  assert.equal(isActivateKey(" "), true);
  assert.equal(isActivateKey("Enter"), true);
  assert.equal(isActivateKey("Tab"), false);
  const src = readFileSync(new URL("../src/ui/Switch.tsx", import.meta.url), "utf8");
  assert.match(src, /role="switch"/);
  assert.match(src, /isActivateKey/);
});

test("tabs and toggle group share moveRoving", () => {
  const tabs = readFileSync(new URL("../src/ui/Tabs.tsx", import.meta.url), "utf8");
  const toggle = readFileSync(new URL("../src/ui/ToggleGroup.tsx", import.meta.url), "utf8");
  assert.match(tabs, /moveRoving/);
  assert.match(toggle, /moveRoving/);
  assert.equal(moveRoving(2, 0, "ArrowRight"), 1);
});

test("tooltip never covers the trigger: placeLayer flips above overflow", () => {
  const flipped = placeLayer(
    { top: 4, left: 40, bottom: 28, right: 80, width: 40, height: 24 },
    { width: 80, height: 32 },
    "top",
    "center",
    8,
    { width: 400, height: 300 },
  );
  assert.equal(flipped.side, "bottom");
  assert.ok(flipped.top >= 28);
  const above = placeLayer(
    { top: 200, left: 40, bottom: 224, right: 80, width: 40, height: 24 },
    { width: 80, height: 32 },
    "top",
    "center",
    8,
    { width: 400, height: 300 },
  );
  assert.equal(above.side, "top");
  assert.ok(above.top + 32 <= 200);
});

test("cn drops falsy class names", () => {
  assert.equal(cn("ui-btn", false, undefined, "is-on"), "ui-btn is-on");
});

test("placeLayer flips every side and clamps to an 8px margin", () => {
  const vp = { width: 400, height: 300 };
  const fromBottom = placeLayer(
    { top: 270, left: 180, bottom: 294, right: 220, width: 40, height: 24 },
    { width: 200, height: 80 },
    "bottom",
    "end",
    8,
    vp,
  );
  assert.equal(fromBottom.side, "top");
  assert.ok(fromBottom.top >= 8);
  assert.ok(fromBottom.top + 80 <= vp.height - 8);
  assert.ok(fromBottom.left >= 8);
  assert.ok(fromBottom.left + 200 <= vp.width - 8);

  const fromLeft = placeLayer(
    { top: 100, left: 4, bottom: 124, right: 44, width: 40, height: 24 },
    { width: 80, height: 32 },
    "left",
    "center",
    8,
    vp,
  );
  assert.equal(fromLeft.side, "right");
  assert.ok(fromLeft.left >= 44);

  const fromRight = placeLayer(
    { top: 100, left: 360, bottom: 124, right: 396, width: 36, height: 24 },
    { width: 80, height: 32 },
    "right",
    "center",
    8,
    vp,
  );
  assert.equal(fromRight.side, "left");
  assert.ok(fromRight.left + 80 <= 360);
});

test("menu typeahead ignores modifiers and space", () => {
  assert.equal(isPrintableTypeahead("s", {}), true);
  assert.equal(isPrintableTypeahead(" ", {}), false);
  assert.equal(isPrintableTypeahead("s", { ctrlKey: true }), false);
});

test("focus return is wired through useLayer wasOpen", () => {
  const src = readFileSync(new URL("../src/ui/useLayer.ts", import.meta.url), "utf8");
  assert.match(src, /wasOpen/);
  assert.match(src, /prevFocus/);
  assert.match(src, /triggerRef\.current/);
});
