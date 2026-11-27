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

test("ChangeItemRow, MarkToolbar, ApprovalSheet, and Composer render 'Label · Chord' titles", async () => {
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const keysMod = await import("../src/shell/keys.ts");
  const keymapMod = await import("../src/shell/keymap.ts");
  const testidsMod = await import("../src/shell/testids.ts");
  const changesMod = await import("../src/model/changes.ts");
  const panelI18nMod = await import("../src/panel/i18n.ts");
  const wp3Mod = await import("../src/i18n/v2/wp3.ts");
  const buttonMod = await loadTsx("ui/Button.tsx", { "./attributes": { principleAttributes } });

  const { MarkToolbar } = await loadTsx("canvas/MarkToolbar.tsx", {
    "../i18n/v2/wp3": wp3Mod,
    "../shell/keymap": keymapMod,
    "../ui/Button": buttonMod,
  });
  const sampleMarkItem = {
    id: "op-1",
    n: 1,
    at: "t0/r1/c0",
    kind: "fill_cell",
    opKind: "fill_cell",
    label: "기관명",
    before: "",
    after: "가온공공기록원",
    page: 1,
    source: "agent",
    decision: "pending",
    contentHash: "h1",
    guard: "none",
    hard: false,
    isFactChanged: false,
    isStale: false,
  };
  const markPendingHtml = renderToStaticMarkup(
    createElement(MarkToolbar, {
      item: sampleMarkItem,
      anchor: { topPx: 10, leftPx: 20 },
      canEdit: true,
      language: "ko",
      onDecide: () => {},
      onEdit: () => {},
    }),
  );
  assert.match(markPendingHtml, /data-testid="mark-accept"[^>]*title="받아들이기 · Y"/);
  assert.match(markPendingHtml, /data-testid="mark-reject"[^>]*title="빼기 · N"/);
  assert.match(markPendingHtml, /data-testid="mark-edit"[^>]*title="고치기 · E"/);
  const markRejectedHtml = renderToStaticMarkup(
    createElement(MarkToolbar, {
      item: { ...sampleMarkItem, decision: "rejected" },
      anchor: { topPx: 10, leftPx: 20 },
      canEdit: false,
      language: "ko",
      onDecide: () => {},
      onEdit: () => {},
    }),
  );
  assert.match(markRejectedHtml, /data-testid="mark-restore"[^>]*title="다시 넣기 · U"/);

  const { ChangeItemRow } = await loadTsx("panel/ChangeItemRow.tsx", {
    "../canvas/actions": { beginCellEditV2: () => false },
    "../canvas/controller": { getPublishedChanges: () => [] },
    "../shell/keys": keysMod,
    "../shell/keymap": keymapMod,
    "../shell/testids": testidsMod,
    "../actions": { editOpValue: async () => {} },
    "../model/changes": changesMod,
    "../ui/Button": buttonMod,
    "./actions": { decide: () => {}, select: () => {} },
    "./bits": { SourceText: () => null },
    "./i18n": panelI18nMod,
  });
  const baseRowItem = {
    id: "op-1",
    n: 1,
    at: "t0/r1/c0",
    kind: "fill",
    label: "기관명",
    opName: "빈칸 채움",
    before: "",
    after: "가온공공기록원",
    page: 1,
    source: "agent",
    decision: "pending",
    contentHash: "h1",
    guard: { status: "none", facts: [] },
    hard: [],
  };
  const rowPendingHtml = renderToStaticMarkup(
    createElement(ChangeItemRow, { item: baseRowItem, selected: true, lang: "ko", locked: false }),
  );
  assert.match(rowPendingHtml, /data-testid="act-accept"[^>]*title="받아들이기 · Y"/);
  assert.match(rowPendingHtml, /data-testid="act-reject"[^>]*title="빼기 · N"/);
  assert.match(rowPendingHtml, /data-testid="act-edit"[^>]*title="고치기 · E"/);
  const rowAcceptedHtml = renderToStaticMarkup(
    createElement(ChangeItemRow, {
      item: { ...baseRowItem, decision: "accepted" },
      selected: true,
      lang: "ko",
      locked: false,
    }),
  );
  assert.match(rowAcceptedHtml, /title="결정 취소 · U"/);
  const rowRejectedHtml = renderToStaticMarkup(
    createElement(ChangeItemRow, {
      item: { ...baseRowItem, decision: "rejected" },
      selected: true,
      lang: "ko",
      locked: false,
    }),
  );
  assert.match(rowRejectedHtml, /data-testid="act-add-back"[^>]*title="다시 넣기 · U"/);

  const { ApprovalSheet } = await loadTsx("panel/ApprovalSheet.tsx", {
    "../model/changes": changesMod,
    "../store": {
      useWorkspace: (sel) =>
        sel({
          activeSessionId: "s1",
          sessions: [{ sessionId: "s1", source: { sha256: "a".repeat(64) } }],
        }),
    },
    "./actions": {
      closeApproval: () => {},
      confirmApproval: async () => {},
      prepareConfirmation: () => {},
      select: () => {},
      toggleTick: () => {},
    },
    "../ui/ApprovalBox": { ApprovalBox: () => null },
    "../ui/Button": buttonMod,
    "../ui/icons": { Icon: () => null },
    "./bits": { Parts: () => null },
    "./ChangesPane": { checkText: () => "", proposerText: () => "" },
    "./i18n": panelI18nMod,
    "../shell/keys": keysMod,
    "../shell/keymap": keymapMod,
    "./state": {
      panelSlice: {
        use: (_doc, sel) => sel({ ticks: [], confirmPhase: "idle", confirmError: null }),
      },
    },
  });
  const sheetHtml = renderToStaticMarkup(
    createElement(ApprovalSheet, {
      view: {
        id: "plan-1",
        planHash: "a".repeat(64),
        base: { kind: "source", revision: 0, sha256: "b".repeat(64) },
        stale: null,
        items: [{ ...baseRowItem, decision: "accepted" }],
        provenance: { agent: "agent", provider: null, mock: false },
        createdUtc: null,
      },
      lang: "ko",
      guardState: "ready",
    }),
  );
  assert.match(sheetHtml, /aria-label="닫기"[^>]*title="닫기 · Esc"/);
  assert.match(sheetHtml, /data-testid="approve-cancel"[^>]*title="취소 · Esc"/);
  assert.match(sheetHtml, /data-testid="approve-confirm"[^>]*title="승인 · Enter"/);

  let composerBlockerVal = null;
  const { Composer } = await loadTsx("panel/Composer.tsx", {
    "../shell/bindings": { openSettings: () => {} },
    "../shell/keys": keysMod,
    "../shell/keymap": keymapMod,
    "../ui/Button": buttonMod,
    "../store": {
      composerBlocker: () => composerBlockerVal,
      composerDraftAfterSend: () => "",
      composerDraftOf: () => ({ text: "" }),
      setComposerDraft: () => {},
      useComposerDraftText: () => "요청",
      useWorkspace: (sel) =>
        sel === composerBlockerVal
          ? composerBlockerVal
          : typeof sel === "function"
            ? sel({ activeSessionId: "s1", provider: { provider: "anthropic" } })
            : null,
    },
    "./actions": { cancelRequest: async () => {}, clearContext: () => {}, sendRequest: async () => true },
    "./i18n": panelI18nMod,
    "./state": { panelSlice: { use: (_doc, sel) => sel({ context: null }) } },
  });
  const composerReadyHtml = renderToStaticMarkup(createElement(Composer, { lang: "ko" }));
  assert.match(composerReadyHtml, /data-testid="composer-input"[^>]*title="에이전트 요청 · Ctrl\+L"/);
  assert.match(composerReadyHtml, /data-testid="composer-send"[^>]*title="요청 보내기 · Enter"/);
  composerBlockerVal = "busy";
  const composerBusyHtml = renderToStaticMarkup(createElement(Composer, { lang: "ko" }));
  assert.match(composerBusyHtml, /data-testid="composer-cancel"[^>]*title="요청 취소 · Esc"/);
});

test(".rl-blank-loc uses var(--text-xs) in a fixed-width right-aligned tabular column and .rl-blanks-group-hdr stays quiet", () => {
  const panesCss = fs.readFileSync(path.join(SRC_DIR, "panes/panes.css"), "utf8");
  const blankLocBlocks = [...panesCss.matchAll(/\.rl-blank-loc\s*\{([^}]+)\}/g)].map((m) => m[1]);
  assert.ok(blankLocBlocks.length >= 1, "Expected .rl-blank-loc rule in panes.css");
  for (const block of blankLocBlocks) {
    if (/\bfont(?:-size)?\s*:/.test(block)) {
      assert.match(block, /var\(--text-xs\)/);
      assert.doesNotMatch(block, /\b9px\b/);
    }
  }
  const mergedBlankLoc = blankLocBlocks.join("\n");
  assert.match(mergedBlankLoc, /text-align:\s*right/);
  assert.match(mergedBlankLoc, /font-variant-numeric:\s*tabular-nums/);
  assert.match(mergedBlankLoc, /\bwidth:\s*9ch/);

  const hdrBlock = panesCss.match(/\.rl-blanks-group-hdr\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.ok(hdrBlock, "Expected .rl-blanks-group-hdr rule in panes.css");
  assert.match(hdrBlock, /font-size:\s*var\(--text-xs\)/);
  assert.match(hdrBlock, /color:\s*var\(--text-3\)/);
  assert.match(hdrBlock, /background:\s*transparent/);
  const hdrNotFirst = panesCss.match(/\.rl-blanks-group-hdr:not\(:first-child\)\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.match(hdrNotFirst, /border-top:\s*var\(--border-hair\)/);
});

test("--text-disabled in v2-tokens.css is not var(--text-3) in light or dark and meets >= 3:1 contrast", () => {
  const v2TokensCss = fs.readFileSync(path.join(SRC_DIR, "v2-tokens.css"), "utf8");
  const lightBlock = v2TokensCss.match(/:root\[data-ui="v2"\]\s*\{([^}]+)\}/)?.[1] ?? "";
  const darkBlock = v2TokensCss.match(/:root\[data-ui="v2"\]\[data-theme="dark"\]\s*\{([^}]+)\}/)?.[1] ?? "";
  const autoDarkBlock = v2TokensCss.match(/:root\[data-ui="v2"\]:not\(\[data-theme\]\)\s*\{([^}]+)\}/)?.[1] ?? "";
  const parseVars = (block) =>
    Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)].map((m) => [m[1], m[2].trim()]));
  const lightVars = parseVars(lightBlock);
  const darkVars = { ...lightVars, ...parseVars(darkBlock) };
  const autoDarkVars = { ...lightVars, ...parseVars(autoDarkBlock) };
  const hexLum = (hex) => {
    const h = hex.replace("#", "").trim();
    const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
    const rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
    const lin = rgb.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  };
  const contrast = (a, b) => {
    const l1 = hexLum(a);
    const l2 = hexLum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  for (const [mode, vars] of [
    ["light", lightVars],
    ["dark", darkVars],
    ["auto-dark", autoDarkVars],
  ]) {
    assert.ok(vars["--text-disabled"], `Missing --text-disabled in ${mode}`);
    assert.notEqual(vars["--text-disabled"], "var(--text-3)", `--text-disabled in ${mode} must not be var(--text-3)`);
    assert.notEqual(vars["--text-disabled"].toLowerCase(), vars["--text-3"].toLowerCase(), `--text-disabled in ${mode} must differ from --text-3`);
    for (const surf of ["--chrome", "--panel", "--field", "--raised"]) {
      const disabledCr = contrast(vars["--text-disabled"], vars[surf]);
      const text3Cr = contrast(vars["--text-3"], vars[surf]);
      assert.ok(disabledCr >= 3.0, `${mode}: --text-disabled on ${surf} is ${disabledCr.toFixed(2)}:1 (< 3.0)`);
      assert.ok(disabledCr < text3Cr, `${mode}: --text-disabled on ${surf} (${disabledCr.toFixed(2)}) must be lower than --text-3 (${text3Cr.toFixed(2)})`);
    }
  }
});

test("MarginMarks.tsx does not exist, is not exported, and its CSS rules are removed", () => {
  assert.equal(fs.existsSync(path.join(SRC_DIR, "canvas/MarginMarks.tsx")), false, "MarginMarks.tsx must be deleted");
  const canvasIndex = fs.readFileSync(path.join(SRC_DIR, "canvas/index.ts"), "utf8");
  assert.doesNotMatch(canvasIndex, /MarginMarks/);
  const canvasCss = fs.readFileSync(path.join(SRC_DIR, "canvas/canvas.css"), "utf8");
  assert.doesNotMatch(canvasCss, /\.rl-margin-(?:layer|mark|num|bar)\b/);
});
