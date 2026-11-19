import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function transpileTsCjs(relUrl) {
  const source = readFileSync(new URL(relUrl, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  });
  return outputText;
}

function loadModules() {
  const cache = new Map();

  function loadCjs(relUrl, extraRequires = {}, jsx = false) {
    if (cache.has(relUrl)) return cache.get(relUrl);
    const source = readFileSync(new URL(relUrl, import.meta.url), "utf8");
    const code = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        ...(jsx ? { jsx: ts.JsxEmit.ReactJSX } : {}),
        esModuleInterop: true,
      },
    }).outputText;
    const module = { exports: {} };
    const req = (id) => {
      if (id in extraRequires) return extraRequires[id];
      throw new Error(`Unexpected require(${id}) from ${relUrl}`);
    };
    const fn = vm.runInThisContext(
      `(function(exports, require, module) {\n${code}\n})`,
      { filename: relUrl },
    );
    fn(module.exports, req, module);
    cache.set(relUrl, module.exports);
    return module.exports;
  }

  const vocabulary = loadCjs("../../i18n/vocabulary.ts");
  const formTokens = loadCjs("../../i18n/formTokens.ts");
  const planProjection = loadCjs("../../agent/planProjection.ts", {
    "../i18n/vocabulary.ts": vocabulary,
    "../i18n/vocabulary": vocabulary,
  });
  const fieldLabels = loadCjs("../fieldLabels.ts", {
    "../i18n/vocabulary.ts": vocabulary,
    "../i18n/vocabulary": vocabulary,
    "../i18n/formTokens.ts": formTokens,
    "../i18n/formTokens": formTokens,
  });
  const guardHelper = loadCjs("../guardHelper.ts", {
    react: {
      useSyncExternalStore: (_sub, getSnap) => getSnap(),
    },
    "../agent/planProjection": planProjection,
    "../i18n/vocabulary": vocabulary,
    "../i18n/formTokens.ts": formTokens,
    "../i18n/formTokens": formTokens,
    "./fieldLabels": fieldLabels,
    "../runtime": {
      guardDiff: async () => {
        throw new Error("mock guardDiffFn must be passed explicitly in tests");
      },
      asRuntimeError: (err) => ({
        code: "guard_unavailable",
        message: String(err),
      }),
    },
  });
  const pageSheet = loadCjs(
    "../../components/PageSheet.tsx",
    {
      react: {},
      "react/jsx-runtime": {},
      "../actions": {},
      "../i18n/vocabulary": vocabulary,
      "../store": {},
      "./SeatEditor": {},
    },
    true,
  );

  return { vocabulary, planProjection, fieldLabels, guardHelper, pageSheet };
}

const { fieldLabels, guardHelper, pageSheet } = loadModules();

function loadGongmunFixtures() {
  const corpus = JSON.parse(
    readFileSync(new URL("../../fixtures/corpus.json", import.meta.url), "utf8"),
  );
  const plan = JSON.parse(
    readFileSync(
      new URL("../../../../examples/gongmun/expected/plan.json", import.meta.url),
      "utf8",
    ),
  );
  const textMap = {};
  for (const r of corpus.regions) {
    if (r.addr) {
      textMap[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
    } else if (typeof r.at_para === "number") {
      textMap[`p:${r.at_para}`] = r;
    }
  }
  return { inspect: corpus.inspect, textMap, plan };
}

function buildGongmunDraft(plan, textMap) {
  const ops = plan.ops.map((rawOp) => {
    const p = rawOp.params;
    if (rawOp.kind === "replace_at_cell") {
      const table = Number(p.table ?? 0);
      const row = Number(p.row ?? 0);
      const col = Number(p.col ?? 0);
      const run = typeof p.run === "number" ? p.run : undefined;
      const region = textMap[`c:${table}:${row}:${col}`];
      const before =
        run !== undefined
          ? (region?.runs?.find((r) => r.index === run)?.text ?? "")
          : (region?.text ?? "");
      return {
        opId: rawOp.opId,
        kind: "replace_at_cell",
        table,
        row,
        col,
        run,
        text: String(p.text ?? ""),
        mode: p.mode ?? "replace",
        before,
        origin: "agent",
        proposer: "gongmun",
      };
    }
    const table = Number(p.table ?? 0);
    const row = Number(p.row ?? 0);
    const col = Number(p.col ?? 0);
    const before = textMap[`c:${table}:${row}:${col}`]?.text ?? "";
    return {
      opId: rawOp.opId,
      kind: "fill_cell",
      table,
      row,
      col,
      text: String(p.text ?? ""),
      lines: Array.isArray(p.lines) ? p.lines : undefined,
      before,
      origin: "agent",
      proposer: "gongmun",
    };
  });

  return {
    sessionId: "sess-gongmun",
    boundSha256: plan.boundSha256,
    ops,
    phase: "ready",
    plan: {
      planId: "plan-gongmun-1",
      backend: "preedit",
      boundSha256: plan.boundSha256,
      ops: plan.ops,
    },
    validation: { ok: true, hard: [], warn: [], stale: false },
    error: null,
  };
}

test("collapseFormGuideLabel collapses spaced Hangul syllables cleanly and preserves word spaces", () => {
  assert.equal(fieldLabels.collapseFormGuideLabel("행 정 기 관 명"), "행정기관명");
  assert.equal(fieldLabels.collapseFormGuideLabel("성 명"), "성명");
  assert.equal(
    fieldLabels.collapseFormGuideLabel("  기안자   직위(직급) 서명 "),
    "기안자 직위(직급) 서명",
  );
  assert.equal(fieldLabels.collapseFormGuideLabel("공개 구분"), "공개 구분");
  assert.equal(
    fieldLabels.collapseFormGuideLabel("행정업무의 운영 및 혁신에 관한 규정 시행규칙"),
    "행정업무의 운영 및 혁신에 관한 규정 시행규칙",
  );
  assert.equal(
    fieldLabels.truncateLabel("비고(이 난은 서식에 포함하지 아니한다)", 20),
    "비고(이 난은 서식에 포함하지 아니한…",
  );
});

test("extractFormInstructionContext extracts quoted slot terms from gianmun fixture", () => {
  const { inspect, textMap } = loadGongmunFixtures();
  const ctx = fieldLabels.extractFormInstructionContext(inspect, textMap);
  assert.equal(ctx.isFormDocument, true);
  assert.equal(ctx.guideCellKeys.has("c:0:0:0"), true);
  assert.equal(ctx.instructionCellKeys.has("c:0:10:0"), true);
  for (const term of [
    "행정기관명",
    "발신명",
    "기안자",
    "검토자",
    "결재권자",
    "직위(직급)서명",
    "처리과명-연도별일련번호(시행일)",
    "도로명주소",
    "홈페이지주소",
    "공무원의전자우편주소",
    "공개구분",
  ]) {
    assert.equal(ctx.quotedTerms.has(term), true, `missing term: ${term}`);
  }
});

test("deriveCellFieldLabel returns body fallback for full-width body fill_target (0,2,0) and preserves left labels", () => {
  const { inspect, textMap } = loadGongmunFixtures();
  assert.equal(fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 2, 0, "ko"), "본문");
  assert.equal(fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 2, 0, "en"), "Body");
  assert.equal(fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 5, 1, "ko"), "협조자");
});

test("all 7 협조자 blanks on gianmun-byeolji-1ho inherit 협조자 in shared deriveCellFieldLabel while guide row stays fallback", () => {
  const { inspect, textMap } = loadGongmunFixtures();
  const coopCols = [1, 2, 4, 5, 8, 10, 13];
  for (let i = 0; i < coopCols.length; i += 1) {
    const col = coopCols[i];
    assert.equal(
      fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 5, col, "ko", i + 3),
      "협조자",
      `expected 협조자 at (0,5,${col})`,
    );
  }
  // Guide cell (0,0,0) must not be inherited onto (0,0,14) as a static row header.
  assert.equal(fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 0, 14, "ko", 1), "빈칸 1");
  assert.equal(fieldLabels.deriveCellFieldLabel(inspect, textMap, 0, 0, 14, "en", 1), "Blank 1");
});

test("buildIndexedChanges on Review labels fill_cell ops on row 5 as 협조자 identically to Fill", () => {
  const { inspect, textMap } = loadGongmunFixtures();
  const coopCols = [1, 2, 4, 5, 8, 10, 13];
  const draft = {
    sessionId: "sess-coop",
    boundSha256: inspect.documentHash,
    phase: "ready",
    plan: { planId: "plan-coop", backend: "preedit", boundSha256: inspect.documentHash, ops: [] },
    validation: { ok: true, hard: [], warn: [], stale: false },
    error: null,
    ops: coopCols.map((col, idx) => ({
      opId: `coop-${col}`,
      kind: "fill_cell",
      table: 0,
      row: 5,
      col,
      text: `기관${idx + 1}`,
      before: "",
      origin: "user",
    })),
  };

  const changes = guardHelper.buildIndexedChanges(draft, inspect, textMap, "ko");
  assert.equal(changes.length, coopCols.length);
  for (const ch of changes) {
    assert.equal(ch.fieldLabel, "협조자", ch.opId);
    assert.equal(ch.opKindText, "빈칸 채움", ch.opId);
  }
});

test("column-header-above takes priority over row-header inheritance across sibling fill_target cells", () => {
  const syntheticInspect = {
    documentHash: "h-prio",
    sessionId: "s-prio",
    summary: {
      documentHash: "h-prio",
      sessionId: "s-prio",
      anchors: [],
      fillTargetCount: 3,
      spacerCells: [],
      scriptAnomalyTargets: [],
      removalTargets: [],
      formatHints: { table_count: 1, has_eq_placeholder: false, citation_example: null },
      pageMetrics: {
        width: 595,
        height: 842,
        chars_per_line: 40,
        lines_per_page: 30,
        usable_width: 480,
        usable_height: 700,
        margin: {},
        assumptions: {},
      },
      constraints: { base_pt: 11, line_spacing_pct: 160, max_pages: null, min_pages: null },
    },
    graph: {
      documentHash: "h-prio",
      sessionId: "s-prio",
      paragraphs: [],
      tables: [
        {
          index: 0,
          cells: [
            { addr: { row: 0, col: 0 }, classification: "static", textPreview: "구분" },
            { addr: { row: 0, col: 1 }, classification: "static", textPreview: "성명" },
            { addr: { row: 0, col: 2 }, classification: "static", textPreview: "연락처" },
            { addr: { row: 0, col: 3 }, classification: "fill_target", textPreview: "" },
            { addr: { row: 1, col: 0 }, classification: "static", textPreview: "신청인" },
            { addr: { row: 1, col: 1 }, classification: "fill_target", textPreview: "" },
            { addr: { row: 1, col: 2 }, classification: "fill_target", textPreview: "" },
            { addr: { row: 1, col: 3 }, classification: "fill_target", textPreview: "" },
          ],
        },
      ],
    },
    regions: { documentHash: "h-prio", sessionId: "s-prio", regions: [] },
  };

  // (1,1) takes immediate left static header ("신청인").
  assert.equal(fieldLabels.deriveCellFieldLabel(syntheticInspect, {}, 0, 1, 1, "ko", 1), "신청인");
  // (1,2) hits (1,1) fill_target in Step 1, then finds column header above ("연락처") in Step 2 before Step 4.
  assert.equal(fieldLabels.deriveCellFieldLabel(syntheticInspect, {}, 0, 1, 2, "ko", 2), "연락처");
  // (1,3) has fill_target at (0,3) above so Step 2 breaks, and Step 4 inherits row header ("신청인").
  assert.equal(fieldLabels.deriveCellFieldLabel(syntheticInspect, {}, 0, 1, 3, "ko", 3), "신청인");
});

test("all 24 Review labels on examples/gongmun/expected/plan.json remain unchanged", () => {
  const { inspect, textMap, plan } = loadGongmunFixtures();
  const draft = buildGongmunDraft(plan, textMap);
  const changes = guardHelper.buildIndexedChanges(draft, inspect, textMap, "ko");

  assert.equal(changes.length, 24);
  const expectedLabels = [
    ["op-1", "[별지 제1호서식]"],
    ["op-2", "행정업무의 운영 및 혁신에 관한 규정…"],
    ["op-3", "[별지 제1호서식]"],
    ["op-4", "<개정 2016. 7. 11.>"],
    ["op-5", "행정기관명"],
    ["op-6", "수신"],
    ["op-7", "제목"],
    ["op-24", "본문"],
    ["op-9", "기안자 직위(직급) 서명"],
    ["op-10", "검토자 직위(직급) 서명"],
    ["op-11", "결재권자 직위(직급) 서명"],
    ["op-12", "처리과명-연도별 일련번호(시행일)"],
    ["op-13", "처리과명-연도별 일련번호(접수일)"],
    ["op-14", "우"],
    ["op-15", "도로명주소"],
    ["op-16", "홈페이지 주소"],
    ["op-17", "전화번호( )"],
    ["op-18", "팩스번호( )"],
    ["op-19", "공무원의 전자우편주소"],
    ["op-20", "공개 구분"],
    ["op-21", "비고(이 난은 서식에 포함하지 아니한…"],
    ["op-22", "비고(이 난은 서식에 포함하지 아니한…"],
    ["op-23", "문서를 작성할 때 \"행정기관명\", \"…"],
    ["op-8", "발신명의"],
  ];
  assert.deepEqual(
    changes.map((c) => [c.opId, c.fieldLabel]),
    expectedLabels,
  );
});

test("computeEffectiveSheetZoom fits Fill on 390px, zooms to 100% on focus when blanks < 32px, and leaves Review unchanged", () => {
  const baseInput = {
    isFillMode: true,
    isCompactMobile: true,
    mobileExplicitFit: false,
    pageFit: "width",
    boxWidth: 374,
    naturalWidthPx: 794,
    zoom: 1,
    isBlankFocused: false,
    minBlankHeightPx: 36,
  };

  // Fill resting at 390px: width-fit (~0.471), fitted blank = 36 * 0.471 = 16.9px < 32px.
  const resting = pageSheet.computeEffectiveSheetZoom(baseInput);
  assert.equal(resting, 0.471);

  // Focusing a blank whose fitted height < 32px auto-zooms to 100%.
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({ ...baseInput, isBlankFocused: true }),
    1,
  );

  // Leaving focus / Esc cancels editing returns to width-fit.
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({ ...baseInput, isBlankFocused: false }),
    0.471,
  );

  // If fitted blank is already >= 32px tall, focus stays at width-fit.
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({
      ...baseInput,
      isBlankFocused: true,
      minBlankHeightPx: 80,
    }),
    0.471,
  );

  // Review at 390px stays 100% by default unless mobileExplicitFit is true.
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({
      ...baseInput,
      isFillMode: false,
      isBlankFocused: true,
    }),
    1,
  );
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({
      ...baseInput,
      isFillMode: false,
      mobileExplicitFit: true,
      isBlankFocused: true,
    }),
    0.471,
  );

  // Free zoom respects explicit user zoom even when a blank is focused.
  assert.equal(
    pageSheet.computeEffectiveSheetZoom({
      ...baseInput,
      pageFit: "free",
      zoom: 1.25,
      isBlankFocused: true,
    }),
    1.25,
  );
});

test("24-op gongmun plan classifies clearing ops and blank fills cleanly with zero 빈칸 N and zero auditable rows", () => {
  const { inspect, textMap, plan } = loadGongmunFixtures();
  const draft = buildGongmunDraft(plan, textMap);
  const changes = guardHelper.buildIndexedChanges(draft, inspect, textMap, "ko");

  assert.equal(changes.length, 24);
  const blankFallbackHits = changes.filter((c) => /^빈칸 \d+$/.test(c.fieldLabel));
  assert.deepEqual(blankFallbackHits, []);

  const auditable = changes.filter((c) => c.isAuditable);
  assert.deepEqual(auditable, []);

  const byId = new Map(changes.map((c) => [c.opId, c]));
  const countsByKind = new Map();
  for (const ch of changes) {
    countsByKind.set(ch.opKindText, (countsByKind.get(ch.opKindText) ?? 0) + 1);
  }
  assert.equal(countsByKind.get("기호 지움"), 2);
  assert.equal(countsByKind.get("안내문 지움"), 6);
  assert.equal(countsByKind.get("빈칸 채움"), 16);
  assert.equal(countsByKind.get("칸 문구 바꿈") ?? 0, 0);

  assert.equal(byId.get("op-1")?.opKindText, "기호 지움");
  assert.equal(byId.get("op-1")?.fieldLabel, "[별지 제1호서식]");
  assert.equal(byId.get("op-1")?.previewMode, "before_only");

  assert.equal(byId.get("op-22")?.opKindText, "기호 지움");
  assert.equal(byId.get("op-22")?.fieldLabel, "비고(이 난은 서식에 포함하지 아니한…");
  assert.equal(byId.get("op-22")?.previewMode, "before_only");

  for (const id of ["op-2", "op-3", "op-4", "op-13", "op-21", "op-23"]) {
    assert.equal(byId.get(id)?.opKindText, "안내문 지움", id);
    assert.equal(byId.get(id)?.previewMode, "before_only", id);
  }

  for (const id of [
    "op-5",
    "op-6",
    "op-7",
    "op-8",
    "op-9",
    "op-10",
    "op-11",
    "op-12",
    "op-14",
    "op-15",
    "op-16",
    "op-17",
    "op-18",
    "op-19",
    "op-20",
    "op-24",
  ]) {
    assert.equal(byId.get(id)?.opKindText, "빈칸 채움", id);
    assert.equal(byId.get(id)?.previewMode, "after_only", id);
  }

  assert.equal(byId.get("op-5")?.fieldLabel, "행정기관명");
  assert.equal(byId.get("op-6")?.fieldLabel, "수신");
  assert.equal(byId.get("op-7")?.fieldLabel, "제목");
  assert.equal(byId.get("op-8")?.fieldLabel, "발신명의");
  assert.equal(byId.get("op-9")?.fieldLabel, "기안자 직위(직급) 서명");
  assert.equal(byId.get("op-10")?.fieldLabel, "검토자 직위(직급) 서명");
  assert.equal(byId.get("op-11")?.fieldLabel, "결재권자 직위(직급) 서명");
  assert.equal(byId.get("op-14")?.fieldLabel, "우");
  assert.equal(byId.get("op-17")?.fieldLabel, "전화번호( )");
  assert.equal(byId.get("op-18")?.fieldLabel, "팩스번호( )");
  assert.equal(byId.get("op-24")?.fieldLabel, "본문");
});

test("genuine content edits remain auditable with diff previews", () => {
  const plainInspect = {
    documentHash: "h1",
    sessionId: "s1",
    summary: {
      documentHash: "h1",
      sessionId: "s1",
      anchors: [],
      fillTargetCount: 0,
      spacerCells: [],
      scriptAnomalyTargets: [],
      removalTargets: [],
      formatHints: { table_count: 1, has_eq_placeholder: false, citation_example: null },
      pageMetrics: {
        width: 595,
        height: 842,
        chars_per_line: 40,
        lines_per_page: 30,
        usable_width: 480,
        usable_height: 700,
        margin: {},
        assumptions: {},
      },
      constraints: {
        base_pt: 11,
        line_spacing_pct: 160,
        max_pages: null,
        min_pages: null,
      },
    },
    graph: {
      documentHash: "h1",
      sessionId: "s1",
      paragraphs: [{ at_para: 3, para_idx: 3, section: "Contents/section0.xml", text: "기존 본문 문단입니다." }],
      tables: [
        {
          index: 0,
          cells: [
            { addr: { row: 0, col: 0 }, classification: "static", textPreview: "예산" },
            { addr: { row: 0, col: 1 }, classification: "static", textPreview: "100만원을 집행한다" },
            { addr: { row: 1, col: 0 }, classification: "static", textPreview: "■ 항목" },
          ],
        },
      ],
    },
    regions: { documentHash: "h1", sessionId: "s1", regions: [] },
  };
  const textMap = {
    "c:0:0:1": {
      table: 0,
      addr: { row: 0, col: 1 },
      text: "100만원을 집행한다",
      runs: [{ index: 0, text: "100만원을 집행한다" }],
    },
    "c:0:1:0": {
      table: 0,
      addr: { row: 1, col: 0 },
      text: "■ 항목",
      runs: [
        { index: 0, text: "■ " },
        { index: 1, text: "항목" },
      ],
    },
  };
  const draft = {
    sessionId: "s1",
    boundSha256: "h1",
    phase: "ready",
    plan: { planId: "p1", backend: "preedit", boundSha256: "h1", ops: [] },
    validation: { ok: true, hard: [], warn: [], stale: false },
    error: null,
    ops: [
      {
        opId: "c-1",
        kind: "replace_at_cell",
        table: 0,
        row: 0,
        col: 1,
        run: 0,
        text: "200만원을 집행한다",
        before: "100만원을 집행한다",
        origin: "user",
      },
      {
        opId: "c-2",
        kind: "set_run",
        atPara: 3,
        run: 0,
        text: "수정한 본문 문단입니다.",
        before: "기존 본문 문단입니다.",
        origin: "user",
      },
      {
        opId: "c-3",
        kind: "delete_guides",
        color: "#0000ff",
        text: "",
        before: "",
        origin: "user",
      },
      {
        opId: "c-4",
        kind: "replace_at_cell",
        table: 0,
        row: 1,
        col: 0,
        run: 0,
        text: "",
        before: "■ ",
        origin: "user",
      },
    ],
  };

  const changes = guardHelper.buildIndexedChanges(draft, plainInspect, textMap, "ko");
  const byId = new Map(changes.map((c) => [c.opId, c]));

  assert.equal(byId.get("c-1")?.isAuditable, true);
  assert.equal(byId.get("c-1")?.opKindText, "칸 문구 바꿈");
  assert.equal(byId.get("c-1")?.previewMode, "diff");

  assert.equal(byId.get("c-2")?.isAuditable, true);
  assert.equal(byId.get("c-2")?.opKindText, "본문 문구 바꿈");
  assert.equal(byId.get("c-2")?.previewMode, "diff");

  assert.equal(byId.get("c-3")?.isAuditable, true);
  assert.equal(byId.get("c-3")?.opKindText, "안내문 지움");
  assert.equal(byId.get("c-3")?.previewMode, "before_only");
  assert.equal(byId.get("c-3")?.afterText, "");

  // Non-guide, non-instruction symbol clearing keeps `기호 지움` and remains auditable.
  assert.equal(byId.get("c-4")?.isAuditable, true);
  assert.equal(byId.get("c-4")?.opKindText, "기호 지움");
  assert.equal(byId.get("c-4")?.previewMode, "before_only");
});

test("extractAddedNumbers restricts to kind === numbers + status === added and deduplicates exact text", () => {
  const para = {
    paragraph: 4,
    pass: false,
    kinds: ["numbers", "dates"],
    changes: ["numbers"],
    before: "수신",
    after: "2026. 11. 15. 044-555-0142 100 100 200 300 400 500",
    beforeProtected: [],
    afterProtected: [
      { start: 0, end: 13, kind: "dates", text: "2026. 11. 15.", status: "added" },
      { start: 14, end: 26, kind: "phones", text: "044-555-0142", status: "added" },
      { start: 27, end: 30, kind: "numbers", text: "100", status: "added" },
      { start: 31, end: 34, kind: "numbers", text: "100", status: "added" },
      { start: 35, end: 38, kind: "numbers", text: "200", status: "kept" },
      { start: 39, end: 42, kind: "numbers", text: "300", status: "added" },
      { start: 43, end: 46, kind: "numbers", text: "400", status: "added" },
      { start: 47, end: 50, kind: "numbers", text: "500", status: "added" },
    ],
  };

  assert.deepEqual(guardHelper.extractAddedNumbers(para), ["100", "300", "400", "500"]);
});

test("runAuthoritativeGuardDiff attaches raw paragraphs to non-auditable rows, suppresses pill/addedNumbers, and yields 0 changed facts", async () => {
  const { inspect, textMap, plan } = loadGongmunFixtures();
  const draft = buildGongmunDraft(plan, textMap);
  const changes = guardHelper.buildIndexedChanges(draft, inspect, textMap, "ko");

  const mockDiff = {
    schema: "rigorloom/guard-diff-v1",
    before: "before",
    after: "after",
    paragraphs: 3,
    pass: false,
    reason: null,
    edited: true,
    changed: [
      {
        paragraph: 0,
        pass: false,
        kinds: ["dates"],
        changes: ["dates"],
        before: "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] <개정 2016. 7. 11.>",
        after: "",
        beforeProtected: [
          { start: 41, end: 53, kind: "dates", text: "2016. 7. 11.", status: "removed" },
        ],
        afterProtected: [],
      },
      {
        paragraph: 1,
        pass: false,
        kinds: ["numbers"],
        changes: ["numbers"],
        before: "행 정 기 관 명수신(경유)제목 ",
        after: "가온공공기록원수신 협조기관장(기록관리과장)(경유)제목 2026년 전자기록물 장기보존 체계 공동 점검 협조 요청",
        beforeProtected: [],
        afterProtected: [
          { start: 30, end: 34, kind: "numbers", text: "2026", status: "added" },
        ],
      },
      {
        paragraph: 2,
        pass: false,
        kinds: ["numbers", "dates"],
        changes: ["numbers", "dates"],
        before: " ",
        after: "1. 관련: 기록정책과-88(2026. 10. 30.)",
        beforeProtected: [],
        afterProtected: [
          { start: 13, end: 15, kind: "numbers", text: "88", status: "added" },
        ],
      },
    ],
    allParagraphs: [],
  };

  const summary = await guardHelper.runAuthoritativeGuardDiff(
    "sess-gongmun",
    draft,
    changes,
    async () => mockDiff,
  );

  assert.equal(summary.state, "ready");
  assert.deepEqual(summary.changedFactOpIds, []);
  for (const ch of changes) {
    assert.equal(summary.rowAudits[ch.opId]?.status, "none", ch.opId);
    assert.deepEqual(summary.rowAudits[ch.opId]?.addedNumbers, [], ch.opId);
  }
  assert.equal(summary.rowAudits["op-1"]?.paragraph?.paragraph, 0);
  assert.equal(summary.rowAudits["op-2"]?.paragraph?.paragraph, 0);
  assert.equal(summary.rowAudits["op-5"]?.paragraph?.paragraph, 1);
  assert.equal(summary.rowAudits["op-24"]?.paragraph?.paragraph, 2);
});

test("unclaimed failing paragraphs never blindly attach onto unrelated auditable rows", async () => {
  const { inspect, textMap } = loadGongmunFixtures();
  const mixedDraft = {
    sessionId: "sess-mixed",
    boundSha256: "h1",
    phase: "ready",
    plan: { planId: "plan-mixed", backend: "preedit", boundSha256: "h1", ops: [] },
    validation: { ok: true, hard: [], warn: [], stale: false },
    error: null,
    ops: [
      {
        opId: "fill-body",
        kind: "fill_cell",
        table: 0,
        row: 2,
        col: 0,
        text: "예산 500만원 집행",
        before: " ",
        origin: "user",
      },
      {
        opId: "audit-prose",
        kind: "set_run",
        atPara: 3,
        run: 0,
        text: "이상 없음 확인",
        before: "기존 안내",
        origin: "user",
      },
    ],
  };

  const changes = guardHelper.buildIndexedChanges(mixedDraft, inspect, textMap, "ko");
  const mockDiff = {
    schema: "rigorloom/guard-diff-v1",
    before: "before",
    after: "after",
    paragraphs: 3,
    pass: false,
    reason: null,
    edited: true,
    changed: [
      {
        paragraph: 2,
        pass: false,
        kinds: ["numbers"],
        changes: ["numbers"],
        before: " ",
        after: "예산 500만원 집행",
        beforeProtected: [],
        afterProtected: [
          { start: 3, end: 6, kind: "numbers", text: "500", status: "added" },
        ],
      },
      {
        paragraph: 99,
        pass: false,
        kinds: ["dates"],
        changes: ["dates"],
        before: "전혀 무관한 문단",
        after: "2026-01-01 전혀 무관한 문단",
        beforeProtected: [],
        afterProtected: [],
      },
    ],
    allParagraphs: [
      {
        paragraph: 3,
        pass: true,
        kinds: [],
        changes: [],
        before: "기존 안내",
        after: "이상 없음 확인",
        beforeProtected: [],
        afterProtected: [],
      },
    ],
  };

  const summary = await guardHelper.runAuthoritativeGuardDiff(
    "sess-mixed",
    mixedDraft,
    changes,
    async () => mockDiff,
  );

  assert.deepEqual(summary.changedFactOpIds, []);
  assert.equal(summary.rowAudits["fill-body"]?.status, "none");
  assert.equal(summary.rowAudits["fill-body"]?.paragraph?.paragraph, 2);
  assert.equal(summary.rowAudits["audit-prose"]?.status, "kept");
  assert.equal(summary.rowAudits["audit-prose"]?.paragraph?.paragraph, 3);
});

test("auditable changed paragraph populates changedFactOpIds identically to rowAudits status", async () => {
  const { inspect, textMap } = loadGongmunFixtures();
  const draft = {
    sessionId: "sess-auditable",
    boundSha256: "h1",
    phase: "ready",
    plan: { planId: "plan-aud", backend: "preedit", boundSha256: "h1", ops: [] },
    validation: { ok: true, hard: [], warn: [], stale: false },
    error: null,
    ops: [
      {
        opId: "audit-1",
        kind: "set_run",
        atPara: 3,
        run: 0,
        text: "예산 999원을 신규 편성한다.",
        before: "기존 안내 문구",
        origin: "user",
      },
    ],
  };

  const changes = guardHelper.buildIndexedChanges(draft, inspect, textMap, "ko");
  const mockDiff = {
    schema: "rigorloom/guard-diff-v1",
    before: "before",
    after: "after",
    paragraphs: 1,
    pass: false,
    reason: null,
    edited: true,
    changed: [
      {
        paragraph: 3,
        pass: false,
        kinds: ["numbers"],
        changes: ["numbers"],
        before: "기존 안내 문구",
        after: "예산 999원을 신규 편성한다.",
        beforeProtected: [],
        afterProtected: [
          { start: 3, end: 6, kind: "numbers", text: "999", status: "added" },
        ],
      },
    ],
    allParagraphs: [],
  };

  const summary = await guardHelper.runAuthoritativeGuardDiff(
    "sess-auditable",
    draft,
    changes,
    async () => mockDiff,
  );

  assert.deepEqual(summary.changedFactOpIds, ["audit-1"]);
  assert.equal(summary.rowAudits["audit-1"]?.status, "changed");
  assert.deepEqual(summary.rowAudits["audit-1"]?.addedNumbers, ["999"]);
});
