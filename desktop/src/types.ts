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

/** A three-state capability row, the shape `render_probe.py:22` established. */
export interface CapabilityRow {
  state: "yes" | "no" | "unknown" | string;
  reason: string | null;
  [key: string]: unknown;
}

/**
 * `capabilities.render` (protocol §11.1).
 *
 * Three separate rows because they fail separately, and the UI must be able to
 * say which one is missing: `rasterizer` is PyMuPDF, `prepare` is whether this
 * machine could run the Hancom conversion at all, `converter` is flatly `no`
 * because `document/render` itself converts nothing.
 */
export interface RenderCapability {
  rasterizer: CapabilityRow;
  prepare: CapabilityRow;
  converter: CapabilityRow;
  evidence: { class: string; proofGrade: string; note: string };
  unavailableReasons: string[];
}

export interface Capabilities {
  protocolVersion: string;
  methods: string[];
  supportedBackends: string[];
  backends: Record<string, BackendCapability>;
  tools: Record<string, { state: string; reason: string | null; path: string | null }>;
  render?: RenderCapability;
  /** Named reasons the build does NOT claim something. Rendered verbatim. */
  unavailable: Record<string, string>;
}

// --- plans, approvals, candidates (protocol §3.6-§3.12) ----------------------

/** One operation inside a plan, as the Runtime normalises it. */
export interface PlanOp {
  opId: string;
  kind: string;
  params: Record<string, unknown>;
}

export interface OperationPlan {
  schema: string;
  planId: string;
  planHash: string;
  /** Hash of the INTENT — this document, this backend, these ops (§10). */
  opsHash: string;
  sessionId: string;
  backend: string;
  boundSha256: string;
  createdUtc: string;
  proposer: string;
  implVersion: string;
  ops: PlanOp[];
  state: string;
}

/**
 * One row of a validation verdict. The Runtime's own `Finding` shape
 * (`pipeline/scripts/checker_base.py:106`) — `msg`, never `message`, and the
 * extra keys each code carries are passed through rather than flattened.
 */
export interface PlanFinding {
  code: string;
  msg: string;
  at: string;
  [key: string]: unknown;
}

export interface PlanValidation {
  planId: string;
  planHash: string;
  backend: string;
  boundSha256: string;
  currentSha256: string;
  stale: boolean;
  ok: boolean;
  verdict: "pass" | "fail" | string;
  hard: PlanFinding[];
  warn: PlanFinding[];
  counts: { hard: number; warn: number; ops: number };
  /**
   * What the validator could NOT reach. `deferred` is load-bearing: a clean
   * validation is not a promise that apply cannot refuse, and the UI says so.
   */
  preflight: { level: string; source: string; deferred: string[]; note: string };
}

export type ApprovalState = "pending" | "approved" | "rejected" | string;

export interface ApprovalRecord {
  approvalId: string;
  planId: string;
  /** The binding. `approval/resolve` refuses a decision naming another hash. */
  planHash: string;
  state: ApprovalState;
  requestedUtc: string;
  requestedBy: string;
  resolvedUtc: string | null;
  approver: string | null;
  decision: string | null;
}

/** One checker's row inside a VerificationReport. */
export interface CheckRow {
  checker: string;
  state: "ran" | "unavailable" | string;
  ok?: boolean | null;
  [key: string]: unknown;
}

/**
 * `rt_apply.verification_report`. **A check that could not run is never a
 * pass**: `acceptance` is true only when every required check RAN and was
 * clean, and `ranAll` says which half failed.
 */
export interface VerificationReport {
  required: string[];
  ranAll: boolean;
  acceptance: boolean;
  reason: string | null;
  checks: CheckRow[];
  note: string;
}

export interface ArtifactRef {
  role: string;
  path: string;
  sha256: string;
  bytes: number;
}

/** The published receipt. `receipt/read` refuses unless it still binds bytes. */
export interface Receipt {
  schema: string;
  implVersion: string;
  createdUtc: string;
  runId: string;
  sessionId: string;
  planId: string;
  planHash: string;
  backend: string;
  bodySha256: string;
  source: { name: string; sha256: string; bytes: number };
  candidate: ArtifactRef;
  approval: ApprovalRecord;
  steps: Array<{
    opId: string;
    kind: string;
    subcommand: string;
    exitCode: number;
    result?: unknown;
  }>;
  checks: VerificationReport;
  evidence: { class: string; note: string };
}

/** What `plan/apply` returns. */
export interface AppliedCandidate {
  runId: string;
  sessionId: string;
  planId: string;
  candidate: ArtifactRef;
  checks: VerificationReport;
  receipt: string;
  canonical: boolean;
}

// --- rendering (protocol §11.1) ----------------------------------------------

export interface RenderImage {
  mediaType: string;
  widthPx: number;
  heightPx: number;
  bytes: number;
  sha256: string;
  path: string;
  inline: boolean;
  inlineLimit: number;
  encoding?: string;
  data?: string;
  reason?: string;
}

export interface RenderResult {
  sessionId: string;
  available: boolean;
  /** Present when `available` — the source the raster came from. */
  source?: { kind: string; sha256?: string; bytes?: number; runId?: string };
  page?: number;
  pageCount?: number;
  pageSize?: { widthPt: number; heightPt: number };
  dpi?: number;
  image?: RenderImage;
  /** Present when NOT available. The reason set is closed; detail is prose. */
  unavailable?: {
    reason:
      | "rasterizer_missing"
      | "no_rasterizable_artifact"
      | "needs_conversion"
      | "artifact_missing"
      | string;
    detail: string;
    prepare?: CapabilityRow;
    [key: string]: unknown;
  };
  capability?: RenderCapability;
  evidence?: { class: string; proofGrade: string; note: string };
}

export interface PrepareResult {
  sessionId: string;
  prepared: boolean;
  reason?: string;
  pdf?: {
    path: string;
    sha256: string;
    bytes: number;
    producedBy: string;
    producedUtc: string;
    sourceSha256: string;
  };
  convert?: { exitCode: number };
}

// --- events (protocol §11.2) --------------------------------------------------

/**
 * One line of the session's own `events.jsonl`, projected.
 *
 * `seq` is the line index, not a stored field — monotonic, gap-free and
 * duplicate-free by construction, which is what makes `after: N` mean
 * something across a reconnect.
 */
export interface RuntimeEvent {
  seq: number;
  at: string;
  kind: string;
  sessionId?: string;
  detail?: Record<string, unknown>;
  [key: string]: unknown;
}

/** A batch of `event` notifications, counted in Rust before crossing IPC. */
export interface EventDelivery {
  subscriptionId: string;
  sessionId: string;
  event: RuntimeEvent;
}

/**
 * One text run inside a region, from `document/readRegion`.
 *
 * `color_value` is the payload that matters: it is the actual colour the
 * document carries, and `color_anomaly` is the runtime's judgement that it
 * differs from the body baseline. Blue body text shipping as "checked and
 * clean" is T127; the document view renders the run in its real colour and
 * marks it, rather than quietly normalising it away.
 */
export interface TextRun {
  index: number;
  text: string;
  charpr?: string;
  color_anomaly?: boolean;
  color_value?: string;
}

/** A region's full text. Cells carry `table` + `addr`; paragraphs `at_para`. */
export interface RegionText {
  table?: number;
  addr?: CellAddr;
  at_para?: number;
  para_idx?: number;
  section?: string;
  text: string;
  truncated_preview?: boolean;
  runs?: TextRun[];
}

/** One thing a check found, addressed so selecting it navigates the document. */
export interface Finding {
  code: string;
  message: string;
  severity: "hard" | "warn" | "info";
  where: string;
  selection:
    | { kind: "cell"; table: number; row: number; col: number }
    | { kind: "paragraph"; atPara: number }
    | null;
}

/** A previously opened document, remembered across launches. */
export interface Recent {
  path: string;
  name: string;
  sha256: string;
  bytes: number;
  openedUtc: string;
}

/** A row of `candidate/list`. Only runs whose receipt landed appear. */
export interface Candidate {
  runId?: string;
  receipt?: string;
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
