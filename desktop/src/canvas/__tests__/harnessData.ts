import corpusRaw from "../../fixtures/corpus.json";
import type {
  CanvasChangeDecision,
  CanvasChangeRef,
} from "../../model/page";
import type { QueuedOp } from "../../store";
import type { InspectResult, RegionText } from "../../types";

export type HarnessScenario =
  | "default"
  | "marks"
  | "typing"
  | "outline"
  | "find"
  | "drying"
  | "live";

interface CorpusShape {
  inspect: InspectResult;
  regions: RegionText[];
  source: {
    name: string;
    documentKind: "hwpx" | "docx" | "pdf";
    bytes: number;
    sha256: string;
  };
}

const corpus = corpusRaw as unknown as CorpusShape;

export const HARNESS_SESSION_ID = "wp3-harness-gongmun";
export const HARNESS_DOC_NAME = "공문서-기안문-서식-1호.hwpx";
export const HARNESS_DOC_PATH = `examples/gongmun/${HARNESS_DOC_NAME}`;

/** Inspect snapshot enriched with real HWPX typefaces for font substitution count. */
export function buildHarnessInspect(): InspectResult {
  const base = corpus.inspect;
  const regionsList = (base.regions?.regions ?? []).map((reg, i) =>
    i % 2 === 0
      ? { ...reg, charPrFace: { hangul: "한양중고딕" } }
      : { ...reg, charPrFace: { hangul: "돋움" } },
  );
  return {
    ...base,
    sessionId: HARNESS_SESSION_ID,
    regions: {
      ...base.regions,
      regions: regionsList,
    },
    summary: {
      ...base.summary,
      sessionId: HARNESS_SESSION_ID,
      baselineCharPr: base.summary.baselineCharPr
        ? {
            ...base.summary.baselineCharPr,
            face: { hangul: "한양신명조", latin: "한양신명조" },
          }
        : undefined,
      typefaces: {
        state: "read",
        reason: null,
        source: "harness",
        charPrsWithFace: 27,
      } as unknown as InspectResult["summary"]["typefaces"],
    },
  };
}

export function buildHarnessTexts(): RegionText[] {
  return [...corpus.regions];
}

export const HARNESS_SOURCE = {
  ...corpus.source,
  name: HARNESS_DOC_NAME,
};

/**
 * 24-op gongmun review queue modeled on `examples/gongmun/expected/plan.json`
 * for the `default` scenario (mix of accepted & pending items so canvas mirrors M-opus).
 */
export function buildDefaultGongmunChanges(
  scenario: HarnessScenario,
): {
  changes: CanvasChangeRef[];
  initialSelectedId: string;
  initialView: "marks" | "clean" | "base";
  initialPane: "outline" | "blanks" | "find";
  initialDecisions: Record<string, CanvasChangeDecision>;
  initialFindQuery: string;
  initialSeatKey: string | null;
  drying: boolean;
} {
  const gongmunOps: Array<{
    id: string;
    n: number;
    opKind: NonNullable<CanvasChangeRef["opKind"]>;
    table: number;
    row: number;
    col: number;
    run?: number;
    label: string;
    before: string;
    after: string;
    source?: CanvasChangeRef["source"];
    decision?: CanvasChangeDecision;
    isFactChanged?: boolean;
    isStale?: boolean;
    hasFormText?: boolean;
    bodyStyleApplied?: boolean;
  }> = [
    {
      id: "op-5",
      n: 5,
      opKind: "replace_at_cell",
      table: 0,
      row: 1,
      col: 0,
      run: 0,
      label: "행정기관명",
      before: "행 정 기 관 명",
      after: "가온공공기록원",
      decision: "accepted",
    },
    {
      id: "op-6",
      n: 6,
      opKind: "replace_at_cell",
      table: 0,
      row: 1,
      col: 0,
      run: 1,
      label: "수신",
      before: "수신",
      after: "수신 협조기관장(기록관리과장)",
      decision: "accepted",
    },
    {
      id: "op-7",
      n: 7,
      opKind: "replace_at_cell",
      table: 0,
      row: 1,
      col: 0,
      run: 3,
      label: "제목",
      before: "제목 ",
      after: "제목 2026년 전자기록물 장기보존 체계 공동 점검 협조 요청",
      decision: "accepted",
    },
    {
      id: "op-24",
      n: 24,
      opKind: "fill_cell",
      table: 0,
      row: 2,
      col: 0,
      label: "본문",
      before: "",
      after: [
        "1. 관련: 기록정책과-88(2026. 10. 30.)",
        "2. 우리 원은 2026년도 생산 전자기록물의 보존 포맷 호환성을 점검합니다. 귀 기관은 아래 일정에 따라 소관 기록물을 점검하고 결과를 회신하여 주시기 바랍니다.",
        "  가. 점검 기간: 2026. 11. 18.(수) ~ 2026. 11. 27.(금)",
        "  나. 점검 대상: 보존 포맷 메타데이터 및 첨부 파일 무결성",
        "  다. 회신 기한: 2026. 11. 30.(월) 18:00까지",
        "  라. 제출 방법: 붙임 점검표를 작성하여 전자문서 시스템으로 발송",
        "",
        "붙임  전자기록물 보존 체계 공동 점검표 1부.  끝.",
      ].join("\n"),
      decision: "pending",
      bodyStyleApplied: true,
    },
    {
      id: "op-9",
      n: 9,
      opKind: "replace_at_cell",
      table: 0,
      row: 4,
      col: 0,
      run: 0,
      label: "기안자",
      before: "기안자  직위(직급) 서명",
      after: "주무관 한서진",
      decision: "accepted",
    },
    {
      id: "op-10",
      n: 10,
      opKind: "replace_at_cell",
      table: 0,
      row: 4,
      col: 3,
      run: 0,
      label: "검토자",
      before: " 검토자  직위(직급) 서명",
      after: "사무관 박도윤",
      decision: "pending",
    },
    {
      id: "op-11",
      n: 11,
      opKind: "replace_at_cell",
      table: 0,
      row: 4,
      col: 9,
      run: 0,
      label: "결재권자",
      before: " 결재권자  직위(직급) 서명",
      after: "원장 윤지현",
      decision: "pending",
    },
    {
      id: "op-12",
      n: 12,
      opKind: "replace_at_cell",
      table: 0,
      row: 6,
      col: 1,
      run: 0,
      label: "시행일 · 번호",
      before: " 처리과명-연도별 일련번호(시행일)",
      after: "기록정책과-104(2026. 11. 15.)",
      decision: "pending",
      isFactChanged: true,
    },
    {
      id: "op-14",
      n: 14,
      opKind: "replace_at_cell",
      table: 0,
      row: 7,
      col: 0,
      run: 0,
      label: "우편번호",
      before: "우",
      after: "우 04521",
      decision: "accepted",
    },
    {
      id: "op-15",
      n: 15,
      opKind: "replace_at_cell",
      table: 0,
      row: 7,
      col: 1,
      run: 0,
      label: "도로명주소",
      before: "도로명주소",
      after: "가상시 예시구 예시로 120",
      decision: "accepted",
    },
    {
      id: "op-16",
      n: 16,
      opKind: "replace_at_cell",
      table: 0,
      row: 7,
      col: 7,
      run: 0,
      label: "홈페이지 주소",
      before: "홈페이지 주소",
      after: "https://archive.example.com",
      decision: "accepted",
    },
    {
      id: "op-17",
      n: 17,
      opKind: "replace_at_cell",
      table: 0,
      row: 8,
      col: 0,
      run: 0,
      label: "전화번호",
      before: "전화번호(   )",
      after: "전화번호(044-555-0142)",
      source: "user",
      decision: "accepted",
      hasFormText: true,
    },
    {
      id: "op-18",
      n: 18,
      opKind: "replace_at_cell",
      table: 0,
      row: 8,
      col: 2,
      run: 0,
      label: "팩스번호",
      before: "팩스번호(   )",
      after: "팩스번호(044-555-0143)",
      decision: "accepted",
      hasFormText: true,
    },
    {
      id: "op-19",
      n: 19,
      opKind: "replace_at_cell",
      table: 0,
      row: 8,
      col: 7,
      run: 0,
      label: "전자우편주소",
      before: "공무원의 전자우편주소",
      after: "gongmun@example.com",
      decision: "pending",
    },
    {
      id: "op-20",
      n: 20,
      opKind: "replace_at_cell",
      table: 0,
      row: 8,
      col: 12,
      run: 0,
      label: "공개 구분",
      before: "공개 구분",
      after: "부분공개(5호)",
      decision: "pending",
    },
    {
      id: "op-8",
      n: 8,
      opKind: "replace_at_cell",
      table: 2,
      row: 0,
      col: 0,
      run: 0,
      label: "발신명의",
      before: "발신명의",
      after: "가온공공기록원장",
      decision: "accepted",
    },
  ];

  if (scenario === "marks") {
    // Rich showcase: ensure every mark visual state appears in the viewport at once!
    gongmunOps[0].decision = "accepted"; // accepted / ink
    gongmunOps[0].source = "agent";
    gongmunOps[1].decision = "pending"; // pending / indigo
    gongmunOps[1].source = "agent";
    gongmunOps[2].decision = "pending"; // fact-changed / crimson
    gongmunOps[2].isFactChanged = true;
    gongmunOps[3].decision = "pending"; // multiline fill_cell pending + selected
    gongmunOps[4].source = "test"; // 시험용 amber hatch
    gongmunOps[4].decision = "pending";
    gongmunOps[5].decision = "rejected"; // 빼기: reverted text + dotted margin bar
    gongmunOps[6].decision = "pending";
    gongmunOps[6].isStale = true; // 지난 제안: dashed amber line
    // Delete op inside op-10's neighbor: blank deletion showcase
    gongmunOps[7].after = "";
    gongmunOps[7].before = "처리과명-연도별 일련번호(시행일)";
    gongmunOps[7].isFactChanged = false;
    gongmunOps[7].decision = "pending";
  }

  if (scenario === "typing") {
    // User typing scenario: blank seats remain unfilled except a user append edit
    const typingOps = gongmunOps.filter((o) =>
      ["op-5", "op-6", "op-7", "op-17"].includes(o.id),
    );
    const changes: CanvasChangeRef[] = typingOps.map((o) => ({
      id: o.id,
      n: o.n,
      at: `t${o.table}/r${o.row}/c${o.col}`,
      kind: o.opKind,
      opKind: o.opKind,
      label: o.label,
      before: o.before,
      after: o.after,
      page: 1,
      source: o.id === "op-17" ? "user" : "agent",
      decision: "accepted",
      guard: "none",
      hard: false,
      isFactChanged: false,
      isStale: false,
      cellKey: `c:${o.table}:${o.row}:${o.col}`,
      run: o.run,
      hasFormText: o.hasFormText,
      bodyStyleApplied: true,
    }));
    const initialDecisions: Record<string, CanvasChangeDecision> = {};
    for (const c of changes) initialDecisions[c.id] = c.decision;
    return {
      changes,
      initialSelectedId: "op-17",
      initialView: "marks",
      initialPane: "blanks",
      initialDecisions,
      initialFindQuery: "",
      initialSeatKey: null,
      drying: false,
    };
  }

  const changes: CanvasChangeRef[] = gongmunOps.map((o) => ({
    id: o.id,
    n: o.n,
    at: `t${o.table}/r${o.row}/c${o.col}`,
    kind: o.opKind,
    opKind: o.opKind,
    label: o.label,
    before: o.before,
    after: o.after,
    page: 1,
    source: o.source ?? "agent",
    decision: o.decision ?? "pending",
    guard: o.isFactChanged ? "changed" : "kept",
    hard: false,
    isFactChanged: Boolean(o.isFactChanged),
    isStale: Boolean(o.isStale),
    cellKey: `c:${o.table}:${o.row}:${o.col}`,
    run: o.run,
    hasFormText: o.hasFormText,
    bodyStyleApplied: o.bodyStyleApplied ?? true,
  }));

  const initialDecisions: Record<string, CanvasChangeDecision> = {};
  for (const ch of changes) initialDecisions[ch.id] = ch.decision;

  return {
    changes,
    initialSelectedId: scenario === "marks" ? "op-24" : "op-24",
    initialView: "marks",
    initialPane:
      scenario === "outline"
        ? "outline"
        : scenario === "find"
          ? "find"
          : "blanks",
    initialDecisions,
    initialFindQuery: scenario === "find" ? "전자기록물" : "",
    initialSeatKey: null,
    drying: scenario === "drying",
  };
}

export function changesToQueuedOps(changes: readonly CanvasChangeRef[]): QueuedOp[] {
  return changes.map((ch) => {
    const m = /^c:(\d+):(\d+):(\d+)$/.exec(ch.cellKey ?? "");
    const table = m ? Number(m[1]) : 0;
    const row = m ? Number(m[2]) : 0;
    const col = m ? Number(m[3]) : 0;
    if (ch.opKind === "fill_cell") {
      return {
        opId: ch.id,
        kind: "fill_cell",
        table,
        row,
        col,
        text: ch.after,
        lines: ch.after.split("\n"),
        before: ch.before,
        origin: ch.source === "user" ? "user" : "agent",
        charPr: "23",
      };
    }
    return {
      opId: ch.id,
      kind: "replace_at_cell",
      table,
      row,
      col,
      run: ch.run ?? 0,
      text: ch.after,
      mode: ch.after.startsWith(ch.before) && ch.before.length > 0 ? "append" : "replace",
      expect: ch.before,
      before: ch.before,
      origin: ch.source === "user" ? "user" : "agent",
    };
  });
}
