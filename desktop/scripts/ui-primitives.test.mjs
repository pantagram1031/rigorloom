import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";
import test from "node:test";
import { fileURLToPath } from "node:url";

const { isImeComposing, principleAttributes } = await import("../src/ui/attributes.ts");
const { WP1B_STRINGS, tWp1b } = await import("../src/i18n/v2/wp1b.ts");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(HERE, "../src");

async function loadTsx(file, imports = {}) {
  const ts = (await import("typescript")).default;
  const nodeRequire = createRequire(import.meta.url);
  const { outputText } = ts.transpileModule(fs.readFileSync(path.join(SRC_DIR, file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    fileName: file,
  });
  const mod = { exports: {} };
  const requireImport = (id) => imports[id] ?? nodeRequire(id);
  vm.runInThisContext(`(function(exports, require, module) {
${outputText}
})`)(mod.exports, requireImport, mod);
  return mod.exports;
}

test("buttons put shortcuts in tooltips and segmented controls use a flat underline", async () => {
  const { Button } = await loadTsx("ui/Button.tsx", { "./attributes": { principleAttributes } });
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const html = renderToStaticMarkup(createElement(Button, {
    title: "Approve", shortcut: ["Ctrl", "Shift", "Enter"],
  }, "Approve"));
  assert.match(html, /title="Approve · Ctrl\+Shift\+Enter"/);
  assert.doesNotMatch(html, /<kbd\b|rl-keycap/);

  const css = fs.readFileSync(path.join(SRC_DIR, "ui/ui.css"), "utf8");
  const track = css.match(/\.rl-segmented \{([^}]+)\}/)?.[1];
  const active = css.match(/\.rl-segmented-btn--active \{([^}]+)\}/)?.[1];
  assert.ok(track && active);
  assert.doesNotMatch(track, /border|background/);
  assert.match(active, /box-shadow:\s*inset 0 -2px/);
  assert.doesNotMatch(active, /border|background/);
});

test("principleAttributes emits canonical data-* attributes only when active", () => {
  assert.deepEqual(principleAttributes({}), {});
  assert.deepEqual(
    principleAttributes({
      variant: "primary",
      docked: false,
      floating: false,
      fact: false,
      accent: false,
    }),
    { "data-variant": "primary" },
  );
  assert.deepEqual(
    principleAttributes({
      variant: "outline",
      docked: true,
      source: "agent",
    }),
    {
      "data-variant": "outline",
      "data-docked": "",
      "data-source": "agent",
    },
  );
  assert.deepEqual(
    principleAttributes({
      floating: true,
      fact: true,
      accent: true,
    }),
    {
      "data-floating": "",
      "data-fact": "",
      "data-accent": "",
    },
  );
});

test("isImeComposing guards Korean IME composition across synthetic and native events", () => {
  assert.equal(isImeComposing(null), false);
  assert.equal(isImeComposing(undefined), false);
  assert.equal(isImeComposing({ key: "Enter", isComposing: false, keyCode: 13 }), false);
  assert.equal(isImeComposing({ key: "y", isComposing: true, keyCode: 89 }), true);
  assert.equal(isImeComposing({ key: "Enter", isComposing: false, keyCode: 229 }), true);
  assert.equal(isImeComposing({ key: "Process", isComposing: false, keyCode: 0 }), true);
  assert.equal(
    isImeComposing({
      key: "ArrowDown",
      isComposing: false,
      nativeEvent: { isComposing: true, keyCode: 40, key: "ArrowDown" },
    }),
    true,
  );
  assert.equal(
    isImeComposing({
      key: "Enter",
      isComposing: false,
      nativeEvent: { isComposing: false, keyCode: 229, key: "Enter" },
    }),
    true,
  );
});

test("ui.css and v2 brand/ui sources contain zero color literals and zero v1 deprecated aliases", () => {
  const dirs = [path.join(SRC_DIR, "ui"), path.join(SRC_DIR, "brand")];
  const hexRe = /#[0-9a-fA-F]{3,8}\b/;
  const rawFuncRe = /\b(?:rgb|rgba|hsl|hsla)\s*\(/;
  const v1AliasRe =
    /(?<![a-zA-Z0-9-])--(?:bg-app|bg-canvas|bg-surface|bg-subtle|bg-control|bg-paper|bg-seat-empty|bg-hover|bg-selected|seg-track|seg-thumb|fg-primary|fg-secondary|fg-muted|fg-on-accent|fg-on-ink|border-subtle|border-strong|border-print|accent-hover|accent-soft|accent-marker-bg|focus-ring|kept-fg|kept-bg|kept-rail|needs-look-fg|needs-look-bg|needs-look-rail|changed-fact-fg|changed-fact-bg|changed-fact-rail|changed-fact-border|shadow-pop|space-[1-8]|radius-lg|topbar-h|row-compact-h|row-h|duration-fast|duration-scroll|duration-panel)(?![a-zA-Z0-9-])/;

  for (const dir of dirs) {
    for (const entry of fs.readdirSync(dir)) {
      const fullPath = path.join(dir, entry);
      if (!fs.statSync(fullPath).isFile()) continue;
      const raw = fs.readFileSync(fullPath, "utf8");
      const stripped = raw
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "");
      assert.equal(
        hexRe.test(stripped),
        false,
        `Unexpected hex literal in ${entry}`,
      );
      assert.equal(
        rawFuncRe.test(stripped),
        false,
        `Unexpected rgb/hsl literal in ${entry}`,
      );
      assert.equal(
        v1AliasRe.test(stripped),
        false,
        `Deprecated v1 token alias used in ${entry}`,
      );
    }
  }
});

test("ui.css scopes --fact to [data-fact], --accent to allowed selectors, and --raised to [data-floating]", () => {
  const css = fs
    .readFileSync(path.join(SRC_DIR, "ui/ui.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");

  // Split CSS blocks while ignoring @media wrappers.
  const ruleRe = /([^{}@]+)\{([^{}]+)\}/g;
  let match;
  while ((match = ruleRe.exec(css)) !== null) {
    const selector = match[1].trim();
    const body = match[2];

    if (/--fact(?:-tint)?\b/.test(body)) {
      assert.match(
        selector,
        /\[data-fact\]/,
        `--fact used outside [data-fact] selector: "${selector}"`,
      );
    }
    if (/--accent(?:-tint|-line)?\b/.test(body)) {
      const selectors = selector.split(",").map((s) => s.trim());
      for (const sel of selectors) {
        assert.equal(
          sel.includes('[data-source="agent"]') ||
            sel.includes("[data-accent]") ||
            sel.includes(":focus-visible"),
          true,
          `--accent used on disallowed selector: "${sel}"`,
        );
      }
    }
    if (/--raised\b|--shadow-float\b/.test(body)) {
      assert.match(
        selector,
        /\[data-floating\]/,
        `--raised / --shadow-float used outside [data-floating]: "${selector}"`,
      );
    }
  }
});

test("icons.tsx defines all 28 glyphs on a 16x16 grid with no fills except dot", () => {
  const iconsSrc = fs.readFileSync(path.join(SRC_DIR, "ui/icons.tsx"), "utf8");
  const listMatch = iconsSrc.match(/ICON_NAMES\s*=\s*\[([\s\S]*?)\]\s*as const/);
  assert.ok(listMatch, "ICON_NAMES constant missing");
  const names = [...listMatch[1].matchAll(/"([a-zA-Z0-9]+)"/g)].map((m) => m[1]);
  assert.equal(names.length, 28);
  assert.equal(new Set(names).size, 28);
  // Only `dot` and the outer `<svg fill="none">` should set `fill=`.
  const fills = [...iconsSrc.matchAll(/fill="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(fills, ["currentColor", "none"]);
});

test("WP1B_STRINGS maintains ko/en parity, pure Hangul ko copy, and zero banned phrases", () => {
  const banned = [
    "진행합니다",
    "하는 것이 가능",
    "해당 ",
    "에 대한",
    "되어집",
    "결재",
    "정확도 100%",
    "Claude 기반",
    "AI 탐지 회피",
    "AI 티 제거",
    "리걸룸",
    "홍길동",
  ];
  const particleAfterVarRe = /\{[^}]+\}(?:은|는|이|가|을|를|과|와|으로|로|에|에서|의|도|만)/;

  for (const [key, entry] of Object.entries(WP1B_STRINGS)) {
    assert.ok(entry.ko.trim().length > 0, `Empty ko for ${key}`);
    assert.ok(entry.en.trim().length > 0, `Empty en for ${key}`);
    assert.equal(
      /[A-Za-z]/.test(entry.ko),
      false,
      `Latin characters found in ko string ${key}: ${entry.ko}`,
    );
    assert.equal(
      particleAfterVarRe.test(entry.ko),
      false,
      `Particle attached directly to placeholder in ${key}: ${entry.ko}`,
    );
    for (const bad of banned) {
      assert.equal(
        entry.ko.includes(bad),
        false,
        `Banned phrase "${bad}" in ${key}: ${entry.ko}`,
      );
    }
  }

  assert.equal(tWp1b("demo_sheet_title", "ko", [24]), "변경 24건 승인");
  assert.equal(tWp1b("demo_sheet_title", "en", [24]), "Approve changes · 24");
});

test("ui/index.ts exports all 11 J1 §5 primitives, Icon, Mark, and principle helpers", () => {
  const indexSrc = fs.readFileSync(path.join(SRC_DIR, "ui/index.ts"), "utf8");
  const required = [
    "ApprovalBox",
    "Button",
    "Keycap",
    "ListRow",
    "Menu",
    "Popover",
    "Segmented",
    "Sheet",
    "Tabs",
    "Tag",
    "Tooltip",
    "Icon",
    "ICON_NAMES",
    "Mark",
    "Wordmark",
    "isImeComposing",
    "principleAttributes",
  ];
  for (const symbol of required) {
    assert.equal(
      new RegExp(`\\b${symbol}\\b`).test(indexSrc),
      true,
      `Missing export ${symbol} in desktop/src/ui/index.ts`,
    );
  }
});

test("public/favicon.ico is the generated 리을R favicon and index.html links it", () => {
  const desktopRoot = path.resolve(SRC_DIR, "..");
  const publicFav = path.join(desktopRoot, "public/favicon.ico");
  const indexHtml = fs.readFileSync(path.join(desktopRoot, "index.html"), "utf8");

  assert.equal(fs.existsSync(publicFav), true, "desktop/public/favicon.ico must exist");
  // scripts/make_icons.py writes an ICO with the 16, 24, 32 and 48 px tiles.
  const ico = fs.readFileSync(publicFav);
  assert.equal(ico.readUInt16LE(0), 0, "ICO reserved field");
  assert.equal(ico.readUInt16LE(2), 1, "ICO type");
  const sizes = Array.from({ length: ico.readUInt16LE(4) }, (_, i) => ico[6 + i * 16] || 256).sort((a, b) => a - b);
  assert.deepEqual(sizes, [16, 24, 32, 48]);
  assert.match(indexHtml, /rel="icon"[^>]+favicon\.ico/);
});

test("Mark draws the 리을R as one path, the 16-px cut at small sizes and the full drawing above", async () => {
  const { Mark } = await loadTsx("brand/Mark.tsx");
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const svgPath = (file) => fs.readFileSync(path.join(SRC_DIR, "assets", file), "utf8").match(/<path d="([^"]+)"/)[1];
  const render = (size) => renderToStaticMarkup(createElement(Mark, { size }));

  const small = render(16);
  const large = render(40);
  for (const html of [small, large]) {
    assert.equal((html.match(/<path\b/g) ?? []).length, 1, html);
    assert.match(html, /pathLength="100"/);
  }
  assert.ok(small.includes(`d="${svgPath("logo-16.svg")}"`), small);
  assert.ok(large.includes(`d="${svgPath("logo.svg")}"`), large);
  assert.match(small, /width="16"/);
  assert.match(large, /width="40"/);
});
