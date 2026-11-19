// Every Escape handler in the UI ignores an IME composition (finding 23): a
// Korean IME cancel inside a field must not close the surface around it.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const GUARD = /isComposing|keyCode === 229|isImeComposing|eventIsComposing|isComposingEvent|composing\.current|composingRef/;

function* sources(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* sources(path);
    else if (/\.(tsx?|mts)$/.test(name)) yield path;
  }
}

/** The text of the handler around line `at`: back to the nearest arrow or function head. */
function handlerHead(lines, at) {
  for (let i = at; i >= Math.max(0, at - 40); i -= 1) {
    if (/=>\s*\{\s*$|function\s*\w*\s*\(|=\s*\(\s*(e|event)\b/.test(lines[i])) return lines.slice(i, at + 1).join("\n");
  }
  return lines.slice(Math.max(0, at - 40), at + 1).join("\n");
}

test("every Escape handler checks for an IME composition first", () => {
  const misses = [];
  for (const file of sources(SRC)) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (!/key === "Escape"/.test(line)) return;
      if (!GUARD.test(handlerHead(lines, i))) misses.push(`${file.slice(SRC.length)}:${i + 1}`);
    });
  }
  assert.deepEqual(misses, []);
});
