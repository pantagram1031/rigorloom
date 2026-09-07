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

/**
 * The typeface a charPr id resolves to, PER LANGUAGE (§14).
 *
 * Hangul's own font dialog carries separate 한글 and 영문 faces and a 기안문
 * declares different ones, so the runtime never collapses them to one name. A
 * language whose id resolves to no face is ABSENT from this map rather than
 * null — the header did not say. `null` in place of the whole map means this
 * document declares no resolvable face for that charPr at all, which is a
 * different fact from `summary.typefaces.state === "unavailable"` (nothing
 * looked). The UI must not merge the two.
 */
export type TypefaceByLang = Partial<
  Record<"hangul" | "latin" | "hanja" | "japanese" | "other" | "symbol" | "user", string>
>;

/** A `fill_target` seat: where a value may be written, and what blocks it. */
export interface EditableRegion {
  kind: "cell" | string;
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
  run?: number;
  charPr?: string;
  /** §14. The face this seat's charPr declares, or null when it declares none. */
  charPrFace?: TypefaceByLang | null;
  charPrSuggested?: string;
  charPrSuggestedFace?: TypefaceByLang | null;
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
  baselineCharPr?: {
    id: string;
    height_pt: number;
    signature: unknown;
    face?: TypefaceByLang | null;
  };
  blackCharPr?: {
    id: string;
    color: string;
    height_pt: number;
    same_height_as_baseline: boolean;
    face?: TypefaceByLang | null;
  };
  /**
   * Whether faces could be read AT ALL, separate from what any one id says.
   *
   * `read` — the profile carries a charPr→face mapping. `unavailable` — nothing
   * looked, with the runtime's reason. A face of `null` under `read` means the
   * document names none; a face of `null` under `unavailable` means we do not
   * know. Two absences, and the toolbar keeps them apart.
   */
  typefaces?: {
    state: "read" | "unavailable" | string;
    reason: string | null;
    source?: string;
    charPrsWithFace?: number;
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
  /**
   * What `module/check` can do on THIS connection (§13).
   *
   * The authority for whether a 작업 팩 can be run is enablement, and this is
   * the runtime's own reading of it. The 작업 팩 list itself comes from a
   * separate child process (`taskpacks.rs`), so the panel has two readers of
   * the same file and says so when they disagree rather than picking one.
   */
  modules?: ModuleCapability;
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

/**
 * A point in the candidate chain: which run, and the digest it carries (§15).
 *
 * `null` where a plan or a receipt names none, which is the ROOT of a chain —
 * built from the session source. Absent and null are the same fact here and
 * the runtime always writes the key, so the UI does not have to tell them apart.
 */
export interface CandidateRef {
  runId: string;
  sha256: string;
}

export interface OperationPlan {
  schema: string;
  planId: string;
  planHash: string;
  /** Hash of the INTENT — this document, this backend, these ops (§10). */
  opsHash: string;
  sessionId: string;
  backend: string;
  /** The digest of whatever this plan is computed against: source, or `base`. */
  boundSha256: string;
  /** The candidate these ops chain onto, or null for the session source (§15.2). */
  base: CandidateRef | null;
  /** The candidate this plan undoes. A recorded CLAIM, proven after apply. */
  reverses: CandidateRef | null;
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
  /** The candidate this one was built ON, or null at the root of the chain. */
  base: CandidateRef | null;
  /** The candidate this one reverses, when its plan declared one. */
  reverses: CandidateRef | null;
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
  base: CandidateRef | null;
  reverses: CandidateRef | null;
  checks: VerificationReport;
  receipt: string;
  canonical: boolean;
}

/**
 * `candidate/compare` (§15.4). Where a reversal stops being a claim.
 *
 * Two equalities, and they are not the same fact. `regionsEqual` is the one an
 * undo has to satisfy: the addresses hold identical text, re-read by the
 * runtime from bytes each receipt re-verified. `artifactEqual` compares whole
 * files and is normally FALSE between an edit and its inverse, because the
 * engine rewrites and rezips the package — so the UI reports it and must never
 * draw it as a failed undo.
 *
 * `equal: null` on a row means neither profile returned that address: the
 * comparison did not happen, which is not a match.
 */
export interface CandidateCompare {
  sessionId: string;
  left: { kind: string; runId?: string; sha256: string };
  right: { kind: string; runId?: string; sha256: string };
  artifactEqual: boolean;
  regions: Array<{
    address: string;
    left: string | null;
    right: string | null;
    equal: boolean | null;
  }>;
  regionsCompared: number;
  /** `null` when nothing was compared. Never read a null as a pass. */
  regionsEqual: boolean | null;
  regionsUnreadable: string[];
  normalizer: string;
  note: string;
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

/**
 * One element the renderer did not draw, in its own words (§11.1c).
 *
 * Forwarded verbatim from the own renderer's sidecar. A renderer that quietly
 * omits a dashed border and one that draws it are indistinguishable from a
 * screenshot, so this list is the difference — which is why the page view puts
 * it one click away rather than in a log.
 */
export interface SkippedElement {
  element: string;
  reason: string;
  count: number;
}

/** How a page was drawn. The closed set `capabilities.render.grades` carries. */
export type RenderGrade = "hancom" | "pdf" | "own-uncertified";

export interface RenderResult {
  sessionId: string;
  available: boolean;
  /** Present when `available` — the source the raster came from. */
  source?: {
    kind: string;
    sha256?: string;
    bytes?: number;
    runId?: string;
    producedBy?: string;
  };
  /**
   * WHICH TIER DREW THIS, and it is never absent from an available result.
   * The badge switches on it; `gradeMeaning` is what it prints underneath.
   */
  grade?: RenderGrade | string;
  tier?: number;
  gradeMeaning?: string;
  renderer?: { id?: string; version?: string; certified: boolean };
  /** Empty for tiers 1 and 2 — a claim, not a gap. */
  elementsSkipped?: SkippedElement[];
  /** Tier 3 only: which declared faces were drawn with something else. */
  fonts?: {
    state: string;
    reason?: string;
    charactersResolved?: number;
    charactersSubstituted?: number;
    facesTotal?: number;
    facesSubstituted?: number;
    substituted?: {
      declared?: string;
      drawnWith?: string;
      slot?: string;
      characters?: number;
    }[];
  };
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
    /** Why the THIRD tier did not step in either (§11.1c). */
    own?: { state: string; reason: string; detail: string };
    [key: string]: unknown;
  };
  capability?: RenderCapability;
  evidence?: { class: string; proofGrade: string; note: string };
}

// --- page geometry (protocol §12) ---------------------------------------------
//
// Where the text IS on the rendered page, and which editable address each piece
// of it corresponds to. Its own method rather than a field on `document/render`,
// because a raster is per-zoom and these rects are not (§12.1) — which is why
// the store caches a geometry answer per (session, page) and multiplies by the
// raster's pixel size instead of re-asking when the zoom changes.

/** Normalized `[x0, y0, x1, y1]`, fractions of the page, origin top-left. */
export type NormRect = [number, number, number, number];

/**
 * An editable address the runtime matched a span to.
 *
 * `kind: "cell"` carries table/row/col — the same triple `beginEdit` takes, so
 * an overlay click and a tree click reach the identical function. `kind:
 * "anchor"` carries `atPara` and is NOT an editable seat; the shell must check
 * against `inspect.regions` rather than assume a mapped address is a fill seat.
 */
export interface GeometryAddress {
  kind: "anchor" | "cell" | string;
  text?: string;
  atPara?: number | null;
  table?: number | null;
  row?: number | null;
  col?: number | null;
  classification?: string | null;
}

/**
 * One line of text on the page. A LINE, not a span run: PyMuPDF splits at every
 * font change, and a label set in two weights would match neither half.
 *
 * `ambiguous` carries every candidate and `address: null`. The runtime refuses
 * to pick one (T41) and so does this shell — surfacing the choice IS the point.
 */
export interface GeometrySpan {
  index: number;
  text: string;
  rect: NormRect;
  address: GeometryAddress | null;
  confidence: "unique" | "ambiguous" | "unmapped" | string;
  candidates?: GeometryAddress[];
  /**
   * Where each character of `text` begins, as a fraction of the page width,
   * plus the last right edge — so `charX.length === text.length + 1`. Same
   * coordinate system as `rect`, so one pixel width scales both.
   *
   * ABSENT where the render did not resolve one box per character in order.
   * A caret offset derived from anything else would be a cursor standing where
   * the glyph is not, so a click on such a line snaps to its start and the
   * status bar says so. Never interpolate this.
   */
  charX?: number[];
  /**
   * The point size the render declares for this line, where every span in it
   * declares the same one. Absent for a line set in two sizes at once — one of
   * them would be a pick.
   */
  sizePt?: number;
  /**
   * Own-rendered pages only: which line breaker placed this box. `lineseg` is
   * the authoring engine's own cached layout, `computed` is our breaker's, and
   * they are not equally trustworthy.
   */
  lineMode?: string;
  /**
   * Own-rendered pages only: the address OUR RENDERER says it drew this line
   * from, which it knows because it drew it out of the tree.
   *
   * It is a witness, never a verdict. The runtime cross-checks it against the
   * form scan and only the scan's answer ever reaches `address`; this field is
   * here so the shell can SAY what the renderer thought, which is the whole
   * difference between a checked address and a trusted one.
   */
  sidecarAddress?: GeometryAddress | null;
  /**
   * How `address` (or its absence) came about on an own-rendered page:
   * `scan+sidecar` both witnesses agree · `disagreement` they do not, and the
   * span is ambiguous carrying both · `sidecar_only` the scan matched nothing
   * and the renderer's answer was recorded and NOT believed.
   */
  addressBasis?: "scan+sidecar" | "disagreement" | "sidecar_only" | string;
  /** Index into `candidates` of the one the renderer named. Never applied. */
  sidecarPick?: number;
}

/**
 * An empty fill seat that the runtime could place a rectangle for.
 *
 * `derivation` says how sure it is, so the UI can style certainty rather than
 * imply it. A seat that could not be placed is ABSENT — never a guessed box.
 */
export interface GeometrySeat {
  table?: number | null;
  row?: number | null;
  col?: number | null;
  rect: NormRect;
  derivation: "matched_text" | "cell_borders" | "interpolated" | "own_cell" | string;
  basis?: Record<string, unknown>;
}

export interface GeometryMapping {
  state: "ran" | "unavailable" | string;
  reason?: string;
  normalizer?: string;
  targets?: number;
  excluded?: { truncatedCells?: number };
  unique?: number;
  ambiguous?: number;
  unmapped?: number;
  /**
   * Own-rendered pages only. What the renderer's own record of which paragraph
   * or cell it drew each line from did to the scan's answer, counted per page:
   * `agree` confirmed a unique address, `disagree` demoted one to ambiguous,
   * `amongCandidates` / `notAmongCandidates` marked a candidate on an already
   * ambiguous line, `sidecarOnly` was recorded and not believed, `scanOnly`
   * had no renderer opinion at all.
   */
  crossCheck?: {
    declared?: number;
    agree?: number;
    disagree?: number;
    amongCandidates?: number;
    notAmongCandidates?: number;
    sidecarOnly?: number;
    scanOnly?: number;
  };
}

export interface GeometryResult {
  sessionId: string;
  available: boolean;
  source?: {
    kind: string;
    sha256?: string;
    bytes?: number;
    runId?: string;
    /** Document digest when ``sha256`` is a prepared PDF/raster artifact. */
    candidateSha256?: string;
  };
  /**
   * WHICH DOCUMENT the address map was built from. Distinct from
   * ``source.sha256``, which may be a PDF or raster artifact of that document.
   */
  subject?: { kind: string; runId?: string; sha256: string };
  page?: number;
  pageCount?: number;
  pageSize?: { widthPt: number; heightPt: number };
  unit?: string;
  origin?: string;
  spanUnit?: string;
  /**
   * WHOSE LAYOUT THIS IS. `"pdf"` read a PDF's own text objects — rects, text,
   * addresses, seats, per-character offsets. `"own"` read our renderer's
   * sidecar, which carries all of the same things and is mapped by the same
   * form scan; what still differs is that the RASTER under it is
   * `own-uncertified`. The page view refuses to draw an overlay whose source
   * disagrees with the raster's tier, and the status bar prints which of the
   * two the seats and the caret are standing on.
   */
  geometrySource?: "pdf" | "own" | string;
  grade?: RenderGrade | string;
  tier?: number;
  spans?: GeometrySpan[];
  seats?: GeometrySeat[];
  seatDerivations?: Record<string, number>;
  mapping?: GeometryMapping;
  /** Whether sub-line offsets were emitted for this page, and for how much of it. */
  charOffsets?: {
    state: "read" | "page_too_dense" | "unavailable" | string;
    reason?: string | null;
    lines?: number;
    of?: number;
    chars?: number;
  };
  cache?: { hit: boolean; key: string };
  /** Present when NOT available — the SAME closed reason set `render` uses. */
  unavailable?: {
    reason:
      | "rasterizer_missing"
      | "no_rasterizable_artifact"
      | "needs_conversion"
      | "artifact_missing"
      | string;
    detail: string;
    [key: string]: unknown;
  };
}

/**
 * What a click on the page resolved to. Shell state, for the status bar.
 *
 * `ambiguous` is a state the user has to leave deliberately: the candidates are
 * listed and nothing is chosen until a person chooses it.
 */
export interface OverlayPick {
  kind:
    | "seat"
    | "unique"
    | "ambiguous"
    | "not_editable"
    | "caret"
    | "no_caret"
    /**
     * A line with real position and no address. What every span on an
     * own-rendered page is (§11.1c), and what a click on one must still SAY —
     * silence would read as a dead page rather than as a stated limit.
     */
    | "unmapped";
  /** What the status bar prints. Already Korean, already final. */
  label: string;
  /** The span or seat this came from, so the drawn overlay can mark itself. */
  targetId: string;
  candidates?: GeometryAddress[];
  /**
   * Index into `candidates` of the one OUR RENDERER says it drew this line
   * from, on an own-rendered page. Marked in the chooser and never applied: a
   * second witness is something to show a person, not a tiebreak this shell is
   * entitled to take (T41).
   */
  sidecarPick?: number;
  address?: GeometryAddress | null;
  /**
   * How the runtime came by this rectangle, carried through to the status bar.
   *
   * §12.4's three derivations are not equally trustworthy, and a seat is the
   * one overlay class a person types into — so the bar says which one they are
   * about to type into rather than leaving it in a tooltip nobody hovers.
   * Absent for a span pick, which has no derivation: it has text.
   */
  derivation?: GeometrySeat["derivation"];
  /**
   * The character offset a caret landed on, or `null` where the line carried
   * no per-character boxes and the click snapped to its front. Present only
   * for `kind: "caret"`, and the null is load-bearing: a measured 0 and a
   * fallback 0 look identical on screen and are different facts.
   */
  caret?: number | null;
  /** Why no caret was placed. Present only for `kind: "no_caret"`. */
  refusal?:
    | "no_address"
    | "multi_run"
    | "run_text_differs"
    | "no_inventory"
    | "revision_mismatch"
    | "cross_run"
    | "utf16_split"
    | string;
}

export interface PrepareResult {
  sessionId: string;
  prepared: boolean;
  /** Which candidate was converted, or null/absent for the session source. */
  runId?: string | null;
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
  /**
   * §14, for a run rather than a seat. The face this run's charPr resolves to
   * in the document's own header, or `null` where the document declares none.
   * A caret standing in this run is the only way the toolbar can name a face
   * for a paragraph; before this it could print the integer and nothing else.
   */
  charpr_face?: TypefaceByLang | null;
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

/**
 * A row of `candidate/list`. Only runs whose receipt landed appear (§15.5).
 *
 * The lineage fields come straight out of the receipt on disk, so a history
 * view is one call. `verified` is always `false` here and it is not a defect:
 * the listing does not re-hash the artifact, and `receipt/read` is the read
 * that does — with `candidate_hash_mismatch` as its refusal. A row that
 * claimed verification it had not done would be the worst kind of lie in a
 * panel whose whole job is provenance.
 */
export interface Candidate {
  runId?: string;
  receipt?: string;
  sha256?: string;
  bytes?: number;
  createdUtc?: string;
  planId?: string;
  base?: CandidateRef | null;
  reverses?: CandidateRef | null;
  acceptance?: boolean | null;
  opKinds?: string[];
  verified?: boolean;
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

// --- the Agent Host (Phase 5) -------------------------------------------------
// Transcribed from real `agenthost/scripts/host.py` output, not from the design
// note: `--capabilities --provider anthropic` and a full `--provider mock` run
// against the corpus form were both captured before any of this was written.

/** One capability, with the state AND who said so. `unknown` is never a yes. */
export interface ProviderCapability {
  state: "yes" | "no" | "unknown" | string;
  reason: string | null;
  declaredBy: "adapter" | "config" | "probe" | string;
}

/**
 * `CapabilityProfile.public()`.
 *
 * Every name in `agenthost/scripts/ah_codes.py CAPABILITY_NAMES` is present or
 * the profile refuses to construct, so the UI can render a fixed table and a
 * missing row is a bug rather than a shrug.
 */
export interface ProviderProfile {
  providerId: string;
  model: string | null;
  authOwnership:
    | "none"
    | "env_reference"
    | "os_store_reference"
    | "provider_managed"
    | string;
  capabilities: Record<string, ProviderCapability>;
  notes: Record<string, unknown>;
}

/** One line of the Agent Host's own event log. Clock-free; the UI stamps time. */
export interface HostEvent {
  seq: number;
  kind: string;
  detail?: Record<string, unknown>;
}

/** What `AgentHost.run` returns. `plan` is re-read authoritatively regardless. */
export interface HostRunPayload {
  ok: boolean;
  host: string;
  hostVersion: string;
  provider: ProviderProfile;
  instruction: string;
  sessionId: string;
  turns: number;
  finishReason: string | null;
  closingText: string | null;
  plan: OperationPlan | null;
  validation: PlanValidation | null;
  approval: ApprovalRecord | null;
  refusals: Array<{ stage: string; code: string; message: string; [key: string]: unknown }>;
  providerFault: { code: string; message: string; [key: string]: unknown } | null;
  turnBudgetExhausted: boolean;
  /** The host-only methods the compile gate will never emit. */
  neverCompiled: string[];
  events: { schema: string; count: number; events: HostEvent[] };
  error?: { code: string; message: string; [key: string]: unknown };
}

export type ProviderId = "mock" | "router" | "anthropic";

/**
 * What the settings pane holds, and what is written to the config file.
 *
 * There is no secret here and there cannot be: `storeKey` is the NAME of an
 * entry in the OS credential store, and the Rust side refuses any other member
 * by name before the file is written.
 */
export interface ProviderSettings {
  provider: ProviderId;
  /** Mock only. Which scripted scenario to run. */
  scenario: string;
  router: { baseUrl: string; model: string; storeKey: string };
  anthropic: { model: string; storeKey: string };
}

export interface CredentialStatus {
  key: string;
  state: "present" | "absent" | "invalid" | string;
  bytes?: number;
  reason?: string | null;
}

/** Where the Agent Host is, if it is anywhere. */
export interface AgentHostStatus {
  available: boolean;
  mode: "explicit" | "packaged" | "interpreter" | null;
  script: string | null;
  program: string | null;
  reason: string | null;
}

/** One turn of the conversation, as the UI holds it. */
export interface Turn {
  id: string;
  instruction: string;
  at: string;
  phase: "idle" | "starting" | "ready" | "failed";
  provider: ProviderId;
  /** Live, from the tailed JSONL, while the turn is still running. */
  events: HostEvent[];
  payload: HostRunPayload | null;
  exitCode: number | null;
  error: RuntimeError | null;
  /** Set when this turn's plan was adopted into the review queue. */
  planId: string | null;
}

// --- 작업 팩 --------------------------------------------------------------------

export interface TaskPack {
  name: string;
  title: string;
  blurb: string;
  /** False when nobody wrote Korean copy for it, so the raw name is on screen. */
  named: boolean;
  enabled: boolean;
  requiresModules: string[] | null;
  checkers: Array<{ name: string; script: string }>;
  cli: Array<{ name: string; script: string }>;
}

export interface TaskPackList {
  available: boolean;
  mode: string | null;
  reason: string | null;
  schema?: string;
  version?: string;
  modulesRoot?: string;
  /** Which enablement file THIS reader read (see `capabilities.modules`). */
  enabledFile?: string;
  enabledFilePresent?: boolean;
  packs: TaskPack[];
}

// --- module/check (protocol §13) -------------------------------------------
//
// The wire that turned 작업 팩 from a declaration viewer into something with a
// button. Shaped like a VerificationReport and, crucially, never a fabricated
// pass: a checker that could not run carries a `state` and a `reason` from a
// closed set, and `acceptance` is false whenever anything did not run, ran
// without an input it declares it needs, or reported findings.

/** `severity: "skipped"` is a rule the checker itself could not decide. */
export interface ModuleFinding {
  severity: "hard" | "warn" | "skipped" | string;
  code: string | null;
  message: string | null;
  /** The checker's own words for where it looked. Prose, shape, or an index. */
  location: unknown;
  /**
   * The Runtime's own addressing, when a translation exists — never a half
   * address that would select the wrong cell. Null means it does not exist,
   * NOT that the finding has no place.
   */
  address: { table?: number; row?: number; col?: number; atPara?: number } | null;
}

export interface ModuleCheckRow {
  checker: string;
  module: string;
  subject: "document" | "workspace" | null;
  wants: string[];
  state: "ran" | "skipped" | "unavailable" | string;
  /** From `rt_codes` closed sets. Null exactly when `state === "ran"`. */
  reason:
    | "subject_undeclared"
    | "needs_workspace"
    | "spawn_failed"
    | "timed_out"
    | "missing_dependency"
    | "usage_error"
    | "no_verdict"
    | string
    | null;
  detail?: string;
  ok: boolean | null;
  verdict: string | null;
  counts?: Record<string, unknown>;
  findings?: ModuleFinding[];
  findingsTruncated?: Record<string, number>;
  ruleStates?: Record<string, unknown>;
  /** Declared inputs this call could not supply. `baseline`, on a document. */
  wantsUnsatisfied?: string[];
  partial?: boolean;
  exitCode?: number;
  durationMs?: number;
  timedOut?: boolean;
  outputTruncated?: boolean;
}

export interface ModuleCheckReport {
  sessionId: string;
  module: string;
  modulesRoot: string;
  enabledFile: string;
  subject: { kind: string; name: string; sha256: string; bytes: number; runId: string | null };
  baseline: { supplied: boolean; kind?: string; sha256?: string; reason: string | null };
  selected: string[];
  ranAll: boolean;
  acceptance: boolean;
  reason: string | null;
  checks: ModuleCheckRow[];
  counts: {
    selected: number;
    ran: number;
    skipped: number;
    unavailable: number;
    partial: number;
    hard: number;
    warn: number;
  };
  bounds: { perCheckerSeconds: number; worstCaseSeconds: number; containment: string };
  evidence: { class: string; note: string };
  note: string;
}

/** One module as `module/list` describes it. Script paths are module-relative. */
export interface ModuleListing {
  name: string;
  enabled: boolean;
  requires: Record<string, unknown>;
  requiresModules: string[];
  checkers: Array<{
    name: string;
    script: string;
    subject: "document" | "workspace" | null;
    wants: string[];
    /** The runtime's own answer, not ours to infer from `subject`. */
    runnableAgainstDocument: boolean;
    reason: string | null;
  }>;
  cli: string[];
  packTypes: string[];
  runModes: string[];
  gateKinds: string[];
  studioPanels: string[];
  playbooks: number;
  hasSkillFragment: boolean;
}

export interface ModuleList {
  version: string;
  modulesRoot: string;
  enabledFile: string;
  enabledFilePresent: boolean;
  discovered: string[];
  enabled: string[];
  modules: ModuleListing[];
  note: string;
}

/** What `capabilities.modules` says this connection can run, and where from. */
export interface ModuleCapability {
  state: "ready" | "unavailable" | string;
  reason: string | null;
  discovered?: string[];
  enabled?: string[];
  modulesRoot?: string;
  enabledFile?: string;
  enabledFilePresent?: boolean;
  skipReasons?: string[];
  unavailableReasons?: string[];
  findingSeverities?: string[];
  containment?: string;
  limits?: Record<string, number>;
}
