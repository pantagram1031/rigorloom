/**
 * Shapes returned by Runtime Protocol v0, transcribed from real responses.
 *
 * Every field below was read off `runtime/scripts/cli.py inspect` run against
 * `tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`, not from the design
 * document. Where the runtime omits a key rather than sending false — which is
 * the house rule for "undecidable" (`engine/scripts/form_inspect.py:913`) — the
 * field is optional here and the UI must render the absence, not a default.
 */

export type DocumentKind = "hwpx" | "hwp" | string;

export interface SourceRef {
  bytes: number;
  documentKind: DocumentKind;
  name: string;
  sha256: string;
}

export interface Session {
  sessionId: string;
  openedUtc: string;
  source: SourceRef;
}

export type CellClassification = "guide" | "static" | "fill_target" | "spacer";

export interface CellAddr {
  row: number;
  col: number;
}

export interface GraphCell {
  addr: CellAddr;
  classification: CellClassification;
  textPreview?: string;
  truncated?: boolean;
  charPr?: string;
  charPrSuggested?: string;
  colorAnomaly?: boolean;
  scriptAnomaly?: boolean;
  spacerPattern?: string;
}

export interface GraphTable {
  index: number;
  cells: GraphCell[];
}

export interface GraphParagraph {
  at_para: number;
  para_idx: number;
  section: string;
  text: string;
}

export interface DocumentGraph {
  documentHash: string;
  sessionId: string;
  paragraphs: GraphParagraph[];
  tables: GraphTable[];
}

/** A `fill_target` seat: where a value may be written, and what blocks it. */
export interface EditableRegion {
  kind: "cell" | string;
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
  run?: number;
  charPr?: string;
  charPrSuggested?: string;
  colorAnomaly?: boolean;
  scriptAnomaly?: boolean;
}

export interface DocumentSummary {
  documentHash: string;
  sessionId: string;
  anchors: string[];
  fillTargetCount: number;
  spacerCells: Array<{ table: number; addr: CellAddr; pattern: string }>;
  scriptAnomalyTargets: Array<{
    table: number;
    addr: CellAddr;
    charpr: string;
    charpr_suggested: string;
    differing: string[];
  }>;
  removalTargets: Array<{ para_idx: number; confidence: string }>;
  formatHints: {
    table_count: number;
    has_eq_placeholder: boolean;
    citation_example: string | null;
  };
  pageMetrics: {
    width: number;
    height: number;
    chars_per_line: number;
    lines_per_page: number;
    usable_width: number;
    usable_height: number;
    margin: Record<string, number>;
    assumptions: Record<string, unknown>;
  };
  constraints: {
    base_pt: number | null;
    line_spacing_pct: number | null;
    max_pages: number | null;
    min_pages: number | null;
  };
  baselineCharPr?: { id: string; height_pt: number; signature: unknown };
  blackCharPr?: {
    id: string;
    color: string;
    height_pt: number;
    same_height_as_baseline: boolean;
  };
}

export interface InspectResult {
  documentHash: string;
  sessionId: string;
  summary: DocumentSummary;
  graph: DocumentGraph;
  regions: { documentHash: string; sessionId: string; regions: EditableRegion[] };
}

export interface BackendCapability {
  state: "available" | "unavailable" | "unknown";
  reason: string | null;
  opKinds: string[];
  notImplemented?: string[];
}

export interface Capabilities {
  protocolVersion: string;
  methods: string[];
  supportedBackends: string[];
  backends: Record<string, BackendCapability>;
  tools: Record<string, { state: string; reason: string | null; path: string | null }>;
  /** Named reasons the build does NOT claim something. Rendered verbatim. */
  unavailable: Record<string, string>;
}

export interface Candidate {
  runId?: string;
  sha256?: string;
  [key: string]: unknown;
}

/** A protocol refusal, passed through whole — §3.7 requires the payload. */
export interface RuntimeError {
  code: string;
  message: string;
  detail?: string;
  data?: unknown;
}

export type SidecarMode = "packaged" | "interpreter";

export interface SidecarStatus {
  running: boolean;
  pid: number | null;
  mode: SidecarMode | null;
  root: string | null;
  jobConfined: boolean | null;
  jobError: string | null;
  exitCode: number | null;
  failure: string | null;
  initialized: boolean;
}

/** One batched record from the Rust side. Never one IPC event per line. */
export interface Activity {
  seq: number;
  atMs: number;
  kind: "frame" | "log" | "lifecycle";
  text: string | null;
  frame: unknown | null;
}
