import type {
  Capabilities,
  Candidate,
  CorpusFileEntry,
  Recent,
  RuntimeError,
  Session,
  UiLanguage,
} from "../types";
import type { Draft, WorkspaceState } from "../store";
import { errorCodeMessage, planStateLabel, t } from "../i18n/vocabulary";

export interface OpenRecentBadge {
  kind: "pending" | "applied";
  label: string;
}

export interface OpenRecentItem {
  key: string;
  liveSessionId: string | null;
  rawName: string;
  displayName: string;
  parentFolder: string;
  fullPath: string;
  openedUtc: string;
  formattedTime: string;
  badge: OpenRecentBadge | null;
}

export interface CorpusDisplayInfo {
  title: string;
  sourceLabel: string;
  filename: string;
}

interface CorpusFormMeta {
  ko: string;
  en: string;
  sourceKo: string;
  sourceEn: string;
  order: number;
}

const KNOWN_CORPUS_FORMS: Record<string, CorpusFormMeta> = {
  "gianmun-byeolji-1ho.hwpx": {
    ko: "기안문 (별지 제1호서식)",
    en: "Drafting Form (Annex 1)",
    sourceKo: "행정안전부 예시",
    sourceEn: "MOIS example",
    order: 1,
  },
  "gianmun-byeolji-2ho.hwpx": {
    ko: "기안문 (별지 제2호서식)",
    en: "Drafting Form (Annex 2)",
    sourceKo: "행정안전부 예시",
    sourceEn: "MOIS example",
    order: 2,
  },
  "jumin-deungchobon-sinchengseo.hwpx": {
    ko: "주민등록표 등·초본 교부 신청서",
    en: "Resident Registration Copy Request",
    sourceKo: "행정안전부 예시",
    sourceEn: "MOIS example",
    order: 3,
  },
  "jeongbo-gonggae-cheongguseo.hwpx": {
    ko: "정보공개 청구서",
    en: "Information Disclosure Request",
    sourceKo: "행정안전부 예시",
    sourceEn: "MOIS example",
    order: 4,
  },
  "saeopja-deungnok-sinchengseo.hwpx": {
    ko: "사업자등록 신청서 (개인사업자용)",
    en: "Business Registration Application",
    sourceKo: "국세청 예시",
    sourceEn: "NTS example",
    order: 5,
  },
  "admrul-gajokdolbom-hyuga-sinchengseo.hwpx": {
    ko: "가족돌봄 휴직·휴가 신청서",
    en: "Family Care Leave Request",
    sourceKo: "국립중앙과학관 예시",
    sourceEn: "NSM example",
    order: 6,
  },
  "moel-pyojun-geunrogyeyakseo-2025.hwpx": {
    ko: "표준근로계약서 (2025)",
    en: "Standard Employment Contract (2025)",
    sourceKo: "고용노동부 예시",
    sourceEn: "MOEL example",
    order: 7,
  },
  "moel-pyojun-geunrogyeyakseo-2013.hwpx": {
    ko: "표준근로계약서 (2013)",
    en: "Standard Employment Contract (2013)",
    sourceKo: "고용노동부 예시",
    sourceEn: "MOEL example",
    order: 8,
  },
  "nrf-gyeolgwa-bogoseo-yangsik.hwpx": {
    ko: "연구결과보고서 양식",
    en: "Research Result Report Form",
    sourceKo: "한국연구재단 예시",
    sourceEn: "NRF example",
    order: 9,
  },
  "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx": {
    ko: "예비창업가 지원 신청서 및 사업계획서",
    en: "Startup Support Application & Plan",
    sourceKo: "창업진흥원 예시",
    sourceEn: "KISED example",
    order: 10,
  },
  "pps-hyeopeop-seungin-sinchengseo.hwpx": {
    ko: "협업 승인 신청서",
    en: "Collaboration Approval Request",
    sourceKo: "조달청 예시",
    sourceEn: "PPS example",
    order: 11,
  },
  "pps-jeongbogonggae-donguiseo.hwpx": {
    ko: "정보공개 동의서 (개인정보 수집·이용)",
    en: "Information Disclosure Consent Form",
    sourceKo: "조달청 예시",
    sourceEn: "PPS example",
    order: 12,
  },
  "render-check-01.hwpx": {
    ko: "문서 배치 확인용 예시",
    en: "Layout Check Sample",
    sourceKo: "내부 점검 예시",
    sourceEn: "Internal check sample",
    order: 90,
  },
  "table-break-probe.hwpx": {
    ko: "표 페이지 나눔 확인용 예시",
    en: "Table Break Check Sample",
    sourceKo: "내부 점검 예시",
    sourceEn: "Internal check sample",
    order: 91,
  },
};

const HWP_ERROR_CODES = new Set([
  "needs_hancom",
  "needs_conversion",
  "convert_failed",
  "not_convertible",
  "capability_unavailable",
]);

const MISSING_SOURCE_ERROR_CODES = new Set([
  "artifact_missing",
  "source_not_found",
]);

export function normalizePathKey(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").trim();
}

export function pathBasename(path: string): string {
  const normalized = normalizePathKey(path);
  if (!normalized) return "";
  const parts = normalized.split("/");
  return parts[parts.length - 1] ?? normalized;
}

export function pathParentFolder(path: string): string {
  const normalized = normalizePathKey(path);
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length < 2) return "";
  return parts[parts.length - 2] ?? "";
}

export function stemWithoutExtension(filename: string): string {
  return filename.replace(/\.(hwpx|hwp)$/i, "").toLowerCase();
}

export function isSupportedDocumentFilename(name: string): boolean {
  return /\.(hwpx|hwp)$/i.test(name.trim());
}

export function isHwpFilename(name: string): boolean {
  return /\.hwp$/i.test(name.trim());
}

export function isHwpBackendAvailable(capabilities: Capabilities | null): boolean {
  const backends = capabilities?.backends as
    | Record<string, { state?: string } | undefined>
    | undefined;
  return backends?.hwp?.state === "available";
}

export function isHwpGuidanceErrorCode(code: string | null | undefined): boolean {
  return Boolean(code && HWP_ERROR_CODES.has(code));
}

export function isMissingSourceErrorCode(code: string | null | undefined): boolean {
  return Boolean(code && MISSING_SOURCE_ERROR_CODES.has(code));
}

export function resolveOpenErrorMessage(
  err: RuntimeError | null,
  language: UiLanguage,
): string {
  if (!err) return errorCodeMessage("internal_error", language);
  return errorCodeMessage(err.code, language);
}

/**
 * Format an ISO timestamp in the active UI language. Invalid timestamps
 * degrade to an empty string rather than throwing or rendering "Invalid Date".
 */
export function formatOpenTimestamp(iso: string, language: UiLanguage): string {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  try {
    return new Intl.DateTimeFormat(language === "ko" ? "ko-KR" : "en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ms));
  } catch {
    return "";
  }
}

export function resolveRecentBadge(
  liveSessionId: string | null,
  draft: Draft,
  candidates: Record<string, Candidate[]>,
  applyOutcomes: WorkspaceState["applyOutcomes"],
  language: UiLanguage,
): OpenRecentBadge | null {
  if (!liveSessionId) return null;
  if (draft.sessionId === liveSessionId && draft.ops.length > 0) {
    return {
      kind: "pending",
      label: t("open_pending_badge", language, [draft.ops.length]),
    };
  }
  const hasApplied =
    Boolean(applyOutcomes[liveSessionId]?.applied) ||
    (candidates[liveSessionId]?.length ?? 0) > 0;
  if (hasApplied) {
    return {
      kind: "applied",
      label: planStateLabel("applied", language),
    };
  }
  return null;
}

/**
 * Build merged recent rows from active sessions and persistent recents,
 * keeping clean basenames (parent folder appended only when basenames collide).
 */
export function buildOpenRecentItems(params: {
  sessions: readonly Session[];
  recents: readonly Recent[];
  openedPaths: Record<string, string>;
  draft: Draft;
  candidates: Record<string, Candidate[]>;
  applyOutcomes: WorkspaceState["applyOutcomes"];
  language: UiLanguage;
}): OpenRecentItem[] {
  const {
    sessions,
    recents,
    openedPaths,
    draft,
    candidates,
    applyOutcomes,
    language,
  } = params;

  const rawEntries: Array<{
    key: string;
    liveSessionId: string | null;
    rawName: string;
    fullPath: string;
    openedUtc: string;
  }> = [];

  const matchedPaths = new Set<string>();
  const matchedSha = new Set<string>();

  for (const s of sessions) {
    const knownPath = openedPaths[s.sessionId] ?? "";
    const rawName = pathBasename(knownPath || s.source.name) || s.source.name;
    const fullPath = knownPath || s.source.name;
    if (knownPath) matchedPaths.add(normalizePathKey(knownPath));
    if (s.source.sha256) matchedSha.add(s.source.sha256);
    rawEntries.push({
      key: `session:${s.sessionId}`,
      liveSessionId: s.sessionId,
      rawName,
      fullPath,
      openedUtc: s.openedUtc,
    });
  }

  for (const r of recents) {
    const normRecent = normalizePathKey(r.path);
    if (matchedPaths.has(normRecent)) continue;
    if (r.sha256 && matchedSha.has(r.sha256)) continue;
    const rawName = pathBasename(r.path || r.name) || r.name;
    rawEntries.push({
      key: `recent:${r.path}`,
      liveSessionId: null,
      rawName,
      fullPath: r.path,
      openedUtc: r.openedUtc,
    });
  }

  rawEntries.sort((a, b) => {
    const ta = Date.parse(a.openedUtc);
    const tb = Date.parse(b.openedUtc);
    if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) {
      return tb - ta;
    }
    if (a.liveSessionId && !b.liveSessionId) return -1;
    if (!a.liveSessionId && b.liveSessionId) return 1;
    return 0;
  });

  const nameCounts = new Map<string, number>();
  for (const entry of rawEntries) {
    nameCounts.set(entry.rawName, (nameCounts.get(entry.rawName) ?? 0) + 1);
  }

  return rawEntries.map((entry) => {
    const duplicateName = (nameCounts.get(entry.rawName) ?? 0) > 1;
    const parent = pathParentFolder(entry.fullPath);
    const parentFolder =
      duplicateName && parent && parent !== entry.rawName ? parent : "";
    const displayName = parentFolder
      ? `${entry.rawName} (${parentFolder})`
      : entry.rawName;

    return {
      key: entry.key,
      liveSessionId: entry.liveSessionId,
      rawName: entry.rawName,
      displayName,
      parentFolder,
      fullPath: entry.fullPath,
      openedUtc: entry.openedUtc,
      formattedTime: formatOpenTimestamp(entry.openedUtc, language),
      badge: resolveRecentBadge(
        entry.liveSessionId,
        draft,
        candidates,
        applyOutcomes,
        language,
      ),
    };
  });
}

function pathMatchesSessionTarget(knownPath: string, targetPath: string): boolean {
  const a = normalizePathKey(knownPath);
  const b = normalizePathKey(targetPath);
  if (!a || !b) return false;
  if (a === b) return true;
  return a.endsWith(`/${b}`) || b.endsWith(`/${a}`);
}

export function findSessionByPath(
  sessions: readonly Session[],
  openedPaths: Record<string, string>,
  targetPath: string,
): Session | null {
  const targetName = pathBasename(targetPath);
  for (const s of sessions) {
    const known = openedPaths[s.sessionId];
    if (known && pathMatchesSessionTarget(known, targetPath)) {
      return s;
    }
  }
  // Secondary guard only when a session's path carries an identical trailing folder/file match
  const targetParent = pathParentFolder(targetPath);
  if (targetName && targetParent) {
    const tail = `${targetParent}/${targetName}`;
    for (const s of sessions) {
      const known = openedPaths[s.sessionId];
      if (known && normalizePathKey(known).endsWith(tail)) {
        return s;
      }
    }
  }
  return null;
}

export async function computeFileSha256(file: File): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle?.digest) return null;
    const buf = await file.arrayBuffer();
    const digest = await globalThis.crypto.subtle.digest("SHA-256", buf);
    const bytes = new Uint8Array(digest);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

export function findSessionByFile(
  sessions: readonly Session[],
  openedPaths: Record<string, string>,
  fileName: string,
  fileBytes: number,
  sha256: string | null,
): Session | null {
  if (sha256) {
    const byHash = sessions.find((s) => s.source.sha256 === sha256);
    if (byHash) return byHash;
  }
  return (
    sessions.find((s) => {
      const known = openedPaths[s.sessionId] ?? s.source.name;
      return pathBasename(known) === pathBasename(fileName) && s.source.bytes === fileBytes;
    }) ?? null
  );
}

/**
 * Filter redundant raw `.hwp` corpus files when a `.hwpx` twin exists (and omit
 * `.hwp` entries when HWP conversion is unavailable so users only see openable examples),
 * while sorting canonical forms ahead of check probes.
 */
export function filterCorpusEntries(
  entries: readonly CorpusFileEntry[],
  hwpAvailable: boolean,
): CorpusFileEntry[] {
  const hwpxStems = new Set<string>();
  for (const entry of entries) {
    const base = pathBasename(entry.path || entry.name);
    if (/\.hwpx$/i.test(base)) {
      hwpxStems.add(stemWithoutExtension(base));
    }
  }

  const visible = entries.filter((entry) => {
    const base = pathBasename(entry.path || entry.name);
    if (/\.hwp$/i.test(base)) {
      if (hwpxStems.has(stemWithoutExtension(base))) return false;
      if (!hwpAvailable) return false;
    }
    return true;
  });

  return [...visible].sort((a, b) => {
    const baseA = pathBasename(a.path || a.name);
    const baseB = pathBasename(b.path || b.name);
    const orderA = KNOWN_CORPUS_FORMS[baseA]?.order ?? 50;
    const orderB = KNOWN_CORPUS_FORMS[baseB]?.order ?? 50;
    if (orderA !== orderB) return orderA - orderB;
    return baseA.localeCompare(baseB);
  });
}

function humanizeCorpusFilename(filename: string): string {
  return filename
    .replace(/\.(hwpx|hwp)$/i, "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function corpusFormDisplayInfo(
  entry: CorpusFileEntry,
  language: UiLanguage,
): CorpusDisplayInfo {
  const filename = pathBasename(entry.path || entry.name) || entry.name;
  const known = KNOWN_CORPUS_FORMS[filename];
  if (known) {
    return {
      title: language === "ko" ? known.ko : known.en,
      sourceLabel: language === "ko" ? known.sourceKo : known.sourceEn,
      filename,
    };
  }
  const humanized = humanizeCorpusFilename(filename) || filename;
  return {
    title: humanized,
    sourceLabel: t("open_sample_form_label", language),
    filename,
  };
}

/**
 * Resolve the user-facing document title for a session: built-in sample forms
 * opened from the corpus show their localized catalog title (e.g. `기안문 (별지 제1호서식)`),
 * while user-opened files keep their source filename.
 */
export function getSessionDisplayTitle(
  session: Session | null,
  openedPaths: Record<string, string>,
  corpusFiles: readonly CorpusFileEntry[],
  language: UiLanguage,
): string {
  if (!session) return "";
  const knownPath = openedPaths[session.sessionId];
  if (knownPath && corpusFiles.length > 0) {
    const normKnown = normalizePathKey(knownPath);
    if (normKnown && normKnown.includes("/")) {
      const matched = corpusFiles.find((entry) => {
        if (!entry.path) return false;
        const normEntry = normalizePathKey(entry.path);
        if (!normEntry) return false;
        return (
          normKnown === normEntry ||
          normKnown.endsWith(`/${normEntry}`) ||
          normEntry.endsWith(`/${normKnown}`)
        );
      });
      if (matched) {
        return corpusFormDisplayInfo(matched, language).title;
      }
    }
  }
  return session.source.name;
}
