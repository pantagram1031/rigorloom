/**
 * Single canonical document-title, tab-display, sample-catalog, and window-title
 * helper used across the title bar, tabs, Start recents, Files pane, and History.
 *
 * Ensures one document never displays conflicting names in different surfaces
 * (C#16, C#20, D1 §2, J1 §3).
 */
import { t, type VocabularyKey } from "../i18n/vocabulary.ts";
import { tWps } from "../i18n/v2/wps.ts";
import type { CorpusFileEntry, Session, UiLanguage } from "../types.ts";

export interface DocumentTitleParts {
  /** Primary display text: form title for sample forms, or filename stem for user files. */
  readonly stem: string;
  /** Dimmed extension including leading dot (e.g. ".hwpx"), or "" for sample forms / untitled. */
  readonly extension: string;
  /** Combined user-facing title (e.g. "기안문 (별지 제1호서식)" or "협조요청_개요.md"). */
  readonly displayName: string;
  /** Uppercase format token without dot for mono labels (e.g. "HWPX", "HWP", "DOCX", "MD"), or "". */
  readonly extensionLabel: string;
  /** True when matched against the bundled sample form catalog. */
  readonly isSampleForm: boolean;
  /** Parent-folder disambiguator set only when multiple open/recent items share a displayName. */
  readonly disambiguator: string;
}

export interface SampleFormDisplayInfo {
  readonly title: string;
  readonly sourceLabel: string;
  readonly filename: string;
  readonly extensionLabel: string;
}

interface CatalogMeta {
  readonly titleKey: VocabularyKey;
  readonly sourceKey: VocabularyKey;
  readonly order: number;
  readonly hidden?: boolean;
}

const SUPPORTED_WORKSPACE_EXTS = new Set([".hwp", ".hwpx", ".docx", ".md"]);

const KNOWN_CORPUS_CATALOG: Readonly<Record<string, CatalogMeta>> = {
  "gianmun-byeolji-1ho.hwpx": {
    titleKey: "corpus_title_gianmun_1",
    sourceKey: "corpus_source_mois",
    order: 1,
  },
  "gianmun-byeolji-2ho.hwpx": {
    titleKey: "corpus_title_gianmun_2",
    sourceKey: "corpus_source_mois",
    order: 2,
  },
  "jumin-deungchobon-sinchengseo.hwpx": {
    titleKey: "corpus_title_jumin",
    sourceKey: "corpus_source_mois",
    order: 3,
  },
  "jeongbo-gonggae-cheongguseo.hwpx": {
    titleKey: "corpus_title_jeongbo_gonggae",
    sourceKey: "corpus_source_mois",
    order: 4,
  },
  "saeopja-deungnok-sinchengseo.hwpx": {
    titleKey: "corpus_title_saeopja",
    sourceKey: "corpus_source_nts",
    order: 5,
  },
  "admrul-gajokdolbom-hyuga-sinchengseo.hwpx": {
    titleKey: "corpus_title_gajokdolbom",
    sourceKey: "corpus_source_nsm",
    order: 6,
  },
  "moel-pyojun-geunrogyeyakseo-2025.hwpx": {
    titleKey: "corpus_title_moel_2025",
    sourceKey: "corpus_source_moel",
    order: 7,
  },
  "moel-pyojun-geunrogyeyakseo-2013.hwpx": {
    titleKey: "corpus_title_moel_2013",
    sourceKey: "corpus_source_moel",
    order: 8,
  },
  "nrf-gyeolgwa-bogoseo-yangsik.hwpx": {
    titleKey: "corpus_title_nrf_report",
    sourceKey: "corpus_source_nrf",
    order: 9,
  },
  "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx": {
    titleKey: "corpus_title_kstartup",
    sourceKey: "corpus_source_kised",
    order: 10,
  },
  "pps-hyeopeop-seungin-sinchengseo.hwpx": {
    titleKey: "corpus_title_pps_collab",
    sourceKey: "corpus_source_pps",
    order: 11,
  },
  "pps-jeongbogonggae-donguiseo.hwpx": {
    titleKey: "corpus_title_pps_consent",
    sourceKey: "corpus_source_pps",
    order: 12,
  },
  "render-check-01.hwpx": {
    titleKey: "corpus_title_render_check",
    sourceKey: "corpus_source_internal",
    order: 90,
    hidden: true,
  },
  "table-break-probe.hwpx": {
    titleKey: "corpus_title_table_break",
    sourceKey: "corpus_source_internal",
    order: 91,
    hidden: true,
  },
};

const HIDDEN_FIXTURE_NAME_RE = /^(?:render-check|table-break-probe|test-fixture)/i;
const CORPUS_PATH_MARKER_RE = /(?:^|\/)(?:tests\/)?corpus\//i;
const CONTROL_CHARS_RE = /[\x00-\x1f\x7f]+/g;

function normalizeSlashes(raw: string): string {
  return raw.replace(CONTROL_CHARS_RE, "").replace(/\\/g, "/").replace(/\/+$/, "").trim();
}

export function splitFilename(rawPathOrName: string): {
  readonly basename: string;
  readonly stem: string;
  readonly extension: string;
  readonly extensionLabel: string;
} {
  const norm = normalizeSlashes(rawPathOrName);
  if (!norm) {
    return { basename: "", stem: "", extension: "", extensionLabel: "" };
  }
  const parts = norm.split("/");
  const basename = (parts[parts.length - 1] ?? "").trim();
  if (!basename || basename === "." || basename === "..") {
    return { basename: "", stem: "", extension: "", extensionLabel: "" };
  }
  const lastDot = basename.lastIndexOf(".");
  // Dotfiles (e.g. ".gitignore") or trailing dot have no split extension.
  if (lastDot <= 0 || lastDot === basename.length - 1) {
    return { basename, stem: basename, extension: "", extensionLabel: "" };
  }
  const stem = basename.slice(0, lastDot);
  const extension = basename.slice(lastDot);
  const extensionLabel = extension.slice(1).toUpperCase();
  return { basename, stem, extension, extensionLabel };
}

export function isSupportedWorkspaceExtension(pathOrName: string): boolean {
  const { extension } = splitFilename(pathOrName);
  return SUPPORTED_WORKSPACE_EXTS.has(extension.toLowerCase());
}

/**
 * Return true for internal test/probe fixtures that must stay hidden from
 * user-facing sample form lists (C#16).
 */
export function isHiddenCorpusFixture(pathOrName: string): boolean {
  const norm = normalizeSlashes(pathOrName);
  if (!norm) return false;
  const { basename } = splitFilename(norm);
  const lower = basename.toLowerCase();
  if (KNOWN_CORPUS_CATALOG[lower]?.hidden) {
    return true;
  }
  if (HIDDEN_FIXTURE_NAME_RE.test(lower)) {
    return true;
  }
  const segments = norm.toLowerCase().split("/").filter(Boolean);
  return segments.includes("probes") || segments.includes("fixtures");
}

function catalogEntryForFilename(filename: string): CatalogMeta | null {
  const lower = filename.toLowerCase();
  if (KNOWN_CORPUS_CATALOG[lower]) {
    return KNOWN_CORPUS_CATALOG[lower];
  }
  // Also match an `.hwp` twin of a known `.hwpx` catalog entry.
  if (lower.endsWith(".hwp")) {
    const hwpxKey = `${lower.slice(0, -4)}.hwpx`;
    if (KNOWN_CORPUS_CATALOG[hwpxKey]) {
      return KNOWN_CORPUS_CATALOG[hwpxKey];
    }
  }
  return null;
}

function humanizeSampleFilename(filename: string): string {
  const { stem } = splitFilename(filename);
  return (
    stem
      .replace(/[-_]+/g, " ")
      .replace(/\s+/g, " ")
      .trim() || filename
  );
}

/**
 * Filter and order bundled sample forms for the Start screen and Files pane:
 * hides internal test fixtures, drops `.hwp` twins when `.hwpx` exists, and
 * omits `.hwp` when HWP support is unavailable.
 */
export function visibleSampleForms(
  entries: readonly CorpusFileEntry[],
  hwpAvailable: boolean,
): CorpusFileEntry[] {
  const hwpxStems = new Set<string>();
  for (const entry of entries) {
    const raw = entry.path || entry.name;
    if (isHiddenCorpusFixture(raw)) continue;
    const { stem, extension } = splitFilename(raw);
    if (extension.toLowerCase() === ".hwpx") {
      hwpxStems.add(stem.toLowerCase());
    }
  }

  const visible = entries.filter((entry) => {
    const raw = entry.path || entry.name;
    if (isHiddenCorpusFixture(raw)) return false;
    const { stem, extension } = splitFilename(raw);
    const extLower = extension.toLowerCase();
    if (extLower === ".hwp") {
      if (hwpxStems.has(stem.toLowerCase())) return false;
      if (!hwpAvailable) return false;
    }
    return true;
  });

  return [...visible].sort((a, b) => {
    const baseA = splitFilename(a.path || a.name).basename;
    const baseB = splitFilename(b.path || b.name).basename;
    const orderA = catalogEntryForFilename(baseA)?.order ?? 50;
    const orderB = catalogEntryForFilename(baseB)?.order ?? 50;
    if (orderA !== orderB) return orderA - orderB;
    return baseA.localeCompare(baseB);
  });
}

export function sampleFormDisplayInfo(
  entry: CorpusFileEntry,
  language: UiLanguage = "ko",
): SampleFormDisplayInfo {
  const { basename, extensionLabel } = splitFilename(entry.path || entry.name);
  const filename = basename || entry.name;
  const meta = catalogEntryForFilename(filename);
  if (meta) {
    return {
      title: t(meta.titleKey, language),
      sourceLabel: t(meta.sourceKey, language),
      filename,
      extensionLabel,
    };
  }
  return {
    title: humanizeSampleFilename(filename),
    sourceLabel: t("open_sample_form_label", language),
    filename,
    extensionLabel,
  };
}

function matchesCorpusEntry(
  normPath: string,
  corpusFiles: readonly CorpusFileEntry[],
): CorpusFileEntry | null {
  if (!normPath || corpusFiles.length === 0) return null;
  for (const entry of corpusFiles) {
    if (!entry.path) continue;
    const normEntry = normalizeSlashes(entry.path);
    if (!normEntry) continue;
    if (
      normPath === normEntry ||
      normPath.endsWith(`/${normEntry}`) ||
      normEntry.endsWith(`/${normPath}`)
    ) {
      return entry;
    }
  }
  return null;
}

export interface ResolveTitleInput {
  readonly name?: string | null;
  readonly path?: string | null;
  readonly corpusFiles?: readonly CorpusFileEntry[];
  readonly isSample?: boolean;
  readonly language?: UiLanguage;
}

/**
 * Resolve one canonical title representation for any document (bundled sample
 * form, user file, or untitled document).
 */
export function resolveDocumentTitle(input: ResolveTitleInput): DocumentTitleParts {
  const language: UiLanguage = input.language ?? "ko";
  const normPath = input.path ? normalizeSlashes(input.path) : "";
  const rawCandidate = normPath || (input.name ? normalizeSlashes(input.name) : "");

  if (!rawCandidate) {
    const untitled = tWps("wps_untitled_document", language);
    return {
      stem: untitled,
      extension: "",
      displayName: untitled,
      extensionLabel: "",
      isSampleForm: false,
      disambiguator: "",
    };
  }

  const { basename, stem, extension, extensionLabel } = splitFilename(rawCandidate);
  if (!basename) {
    const untitled = tWps("wps_untitled_document", language);
    return {
      stem: untitled,
      extension: "",
      displayName: untitled,
      extensionLabel: "",
      isSampleForm: false,
      disambiguator: "",
    };
  }

  // 1) Explicit match against loaded corpus catalog entries
  const corpusMatch = matchesCorpusEntry(normPath, input.corpusFiles ?? []);
  if (corpusMatch) {
    const info = sampleFormDisplayInfo(corpusMatch, language);
    return {
      stem: info.title,
      extension: "",
      displayName: info.title,
      extensionLabel: info.extensionLabel || extensionLabel,
      isSampleForm: true,
      disambiguator: "",
    };
  }

  // 2) Bundled sample form recognized via corpus path marker or explicit flag
  if (input.isSample || (normPath && CORPUS_PATH_MARKER_RE.test(normPath))) {
    const meta = catalogEntryForFilename(basename);
    if (meta) {
      const title = t(meta.titleKey, language);
      return {
        stem: title,
        extension: "",
        displayName: title,
        extensionLabel,
        isSampleForm: true,
        disambiguator: "",
      };
    }
  }

  // 3) User document: keep file stem + dimmed extension (J1 §3)
  return {
    stem,
    extension,
    displayName: basename,
    extensionLabel,
    isSampleForm: false,
    disambiguator: "",
  };
}

export function resolveSessionTitle(
  session: Session | null | undefined,
  options: {
    readonly openedPaths?: Readonly<Record<string, string>>;
    readonly corpusFiles?: readonly CorpusFileEntry[];
    readonly language?: UiLanguage;
  } = {},
): DocumentTitleParts {
  if (!session) {
    return resolveDocumentTitle({ language: options.language });
  }
  return resolveDocumentTitle({
    name: session.source.name,
    path: options.openedPaths?.[session.sessionId] ?? null,
    corpusFiles: options.corpusFiles,
    language: options.language,
  });
}

function parentSegments(rawPath: string | null | undefined): string[] {
  if (!rawPath) return [];
  const norm = normalizeSlashes(rawPath);
  if (!norm) return [];
  const parts = norm.split("/").filter(Boolean);
  if (parts.length < 2) return [];
  // Drop drive specifiers like "C:" and the filename itself.
  return parts.slice(0, -1).filter((seg) => !/^[A-Za-z]:$/.test(seg));
}

/**
 * Attach shortest distinguishing parent-folder suffixes when two or more items
 * share the same `displayName` (C-copy §4: "같은 이름의 파일을 둘 이상 열면
 * 탭의 보조 표시에 상위 폴더를 붙입니다"). Never exposes raw system roots.
 */
export function disambiguateDocumentTitles<
  T extends { readonly title: DocumentTitleParts; readonly path?: string | null },
>(items: readonly T[]): Array<T & { readonly title: DocumentTitleParts }> {
  const groups = new Map<string, number[]>();
  items.forEach((item, index) => {
    const key = item.title.displayName.normalize("NFC").toLowerCase();
    const list = groups.get(key);
    if (list) {
      list.push(index);
    } else {
      groups.set(key, [index]);
    }
  });

  const disambiguators = new Array<string>(items.length).fill("");

  for (const indices of groups.values()) {
    if (indices.length < 2) continue;
    const segsByIdx = indices.map((idx) => parentSegments(items[idx].path));
    const maxDepth = Math.min(
      3,
      segsByIdx.reduce((acc, s) => Math.max(acc, s.length), 0),
    );
    for (let depth = 1; depth <= maxDepth; depth += 1) {
      const candidates = segsByIdx.map((segs) =>
        segs.length > 0 ? segs.slice(-depth).join("/") : "",
      );
      const nonEmpty = candidates.filter(Boolean);
      const uniqueCount = new Set(nonEmpty.map((c) => c.toLowerCase())).size;
      if (uniqueCount === nonEmpty.length || depth === maxDepth) {
        indices.forEach((idx, pos) => {
          disambiguators[idx] = candidates[pos] ?? "";
        });
        break;
      }
    }
  }

  return items.map((item, idx) => ({
    ...item,
    title: {
      ...item.title,
      disambiguator: disambiguators[idx],
    },
  }));
}

/**
 * Format the window / browser tab title:
 * - No document open: `Rigorloom`
 * - Document open: `{document title} — Rigorloom`
 */
export function formatWindowTitle(
  docTitle: string | DocumentTitleParts | null | undefined,
  language: UiLanguage = "ko",
): string {
  const raw =
    typeof docTitle === "string"
      ? docTitle.trim()
      : docTitle
        ? docTitle.displayName.trim()
        : "";
  if (!raw) {
    return tWps("wps_window_title_app", language);
  }
  return tWps("wps_window_title_doc", language, [raw]);
}

/**
 * Format a compact folder breadcrumb for recent-document subtitles without
 * exposing raw OS prefixes such as `/home/...` or `C:\Users\<user>\...`.
 */
export function formatFolderBreadcrumb(
  fullPath: string | null | undefined,
  rootPath?: string | null,
  maxSegments = 3,
): string {
  const segs = parentSegments(fullPath);
  if (segs.length === 0) return "";
  if (rootPath) {
    const rootNorm = normalizeSlashes(rootPath);
    const fullNorm = normalizeSlashes(fullPath ?? "");
    if (
      rootNorm &&
      fullNorm.toLowerCase().startsWith(`${rootNorm.toLowerCase()}/`)
    ) {
      const rel = fullNorm.slice(rootNorm.length + 1);
      const relParts = rel.split("/").filter(Boolean).slice(0, -1);
      const rootLabel = splitFilename(rootNorm).basename;
      const combined = rootLabel ? [rootLabel, ...relParts] : relParts;
      return combined.slice(-maxSegments).join(" › ");
    }
  }
  return segs.slice(-Math.min(2, maxSegments)).join(" › ");
}
