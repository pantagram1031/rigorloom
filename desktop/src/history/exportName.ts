/**
 * Export filename generation and source-overwrite refusal helpers.
 *
 * Guarantees:
 * - Export names follow `…_수정본N.ext` (Korean) / `…_revN.ext` (English)
 *   rather than internal `-candidate` slugs (C#15, D1 §3(e), J1 §5).
 * - Targets equal to the source path (or its sidecar receipt) are always
 *   refused, including case-insensitive, slash-normalized, extended-prefix,
 *   relative-segment, and Unicode NFC/NFD equivalents on Windows and POSIX.
 */
import { tWps } from "../i18n/v2/wps.ts";
import type { UiLanguage } from "../types.ts";

export type ExportFormat = "hwpx" | "pdf" | "hwp";
export type PathPlatform = "auto" | "win32" | "posix";

export interface ExportNameParams {
  /** Document display title or source filename/path. */
  readonly baseName: string;
  /** Positive 1-based revision number, or null/0 when exporting the original. */
  readonly revisionNumber?: number | null;
  /** Desired output format/extension (default: "hwpx"). */
  readonly format?: ExportFormat | string;
  /** UI language determining `_수정본N` vs `_revN` (default: "ko"). */
  readonly language?: UiLanguage;
}

export interface ExportTargetValidationOk {
  readonly ok: true;
  readonly normalizedPath: string;
  readonly filename: string;
  readonly directory: string;
}

export interface ExportTargetValidationError {
  readonly ok: false;
  readonly code: "empty_name" | "invalid_name" | "target_equals_source";
  readonly message: string;
}

export type ExportTargetValidation =
  | ExportTargetValidationOk
  | ExportTargetValidationError;

const KNOWN_DOC_EXT_RE = /\.(?:hwpx|hwp|docx|md|pdf)$/i;
const ILLEGAL_FILENAME_CHARS_RE = /[<>:"/\\|?*\x00-\x1f\x7f]+/g;
const CONTROL_OR_NUL_RE = /[\x00-\x1f\x7f]/;
const WINDOWS_RESERVED_DEVICE_RE = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i;
const WINDOWS_DRIVE_RE = /^[A-Za-z]:(?:[\\/]|$)/;
const WINDOWS_UNC_RE = /^(?:\\\\|\/\/)[^\\/]+[\\/][^\\/]+/;
const WINDOWS_EXTENDED_UNC_RE = /^\\\\\?\\UNC\\/i;
const WINDOWS_EXTENDED_DRIVE_RE = /^\\\\[?.]\\([A-Za-z]:)/;
const MAX_EXPORT_STEM_LEN = 120;

function escapeRegExp(literal: string): string {
  return literal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripPriorExportSuffix(stem: string): string {
  const koRev = escapeRegExp(tWps("wps_revision_file_token", "ko"));
  const enRev = escapeRegExp(tWps("wps_revision_file_token", "en"));
  const koOrig = escapeRegExp(tWps("wps_original_file_token", "ko"));
  const enOrig = escapeRegExp(tWps("wps_original_file_token", "en"));
  const suffixRe = new RegExp(
    `(?:_(?:(?:${koRev}|${enRev})\\d+|${koOrig}|${enOrig})|-candidate)$`,
    "i",
  );
  let current = stem.trim();
  // Strip at most two trailing generated suffixes to avoid `foo_수정본1_수정본2`.
  for (let i = 0; i < 2; i += 1) {
    const next = current.replace(suffixRe, "").trim();
    if (next === current || !next) break;
    current = next;
  }
  return current;
}

function extractRawBasename(raw: string): string {
  const trimmed = raw.normalize("NFC").trim();
  if (!trimmed) return "";
  const unified = trimmed.replace(/\\/g, "/").replace(/\/+$/, "");
  const parts = unified.split("/");
  return parts[parts.length - 1] ?? "";
}

function normalizeExtension(format: string | undefined, fallbackSource: string): string {
  if (typeof format === "string" && format.trim()) {
    const cleaned = format.trim().replace(/^\.+/, "").toLowerCase();
    if (/^[a-z0-9]{1,10}$/.test(cleaned)) {
      return cleaned;
    }
  }
  const m = fallbackSource.match(KNOWN_DOC_EXT_RE);
  if (m) {
    return m[0].slice(1).toLowerCase();
  }
  return "hwpx";
}

/**
 * Sanitize a user-facing document title or filename into a safe export stem
 * without path separators, control characters, trailing dots, or Windows device names.
 */
export function sanitizeExportStem(rawName: string, language: UiLanguage = "ko"): string {
  const base = extractRawBasename(rawName);
  const withoutExt = base.replace(KNOWN_DOC_EXT_RE, "");
  const withoutPrior = stripPriorExportSuffix(withoutExt);

  let cleaned = withoutPrior
    .replace(ILLEGAL_FILENAME_CHARS_RE, " ")
    .replace(/\s+/g, " ")
    .replace(/^[.\s]+|[.\s]+$/g, "");

  if (!cleaned) {
    cleaned = tWps("wps_export_default_stem", language);
  }
  if (cleaned.length > MAX_EXPORT_STEM_LEN) {
    cleaned = cleaned.slice(0, MAX_EXPORT_STEM_LEN).replace(/[.\s]+$/, "");
  }
  if (!cleaned) {
    cleaned = tWps("wps_export_default_stem", language);
  }
  if (WINDOWS_RESERVED_DEVICE_RE.test(cleaned)) {
    cleaned = `${cleaned}_`;
  }
  return cleaned;
}

/**
 * Generate the canonical export filename:
 * - Korean revision 2: `기안문(별지 제1호서식)_수정본2.hwpx`
 * - Korean revision 1 PDF: `기안문(별지 제1호서식)_수정본1.pdf`
 * - English revision 2: `Draft_rev2.hwpx`
 * - Original (revisionNumber null/0): `기안문(별지 제1호서식)_원본.hwpx`
 */
export function formatExportFilename(params: ExportNameParams): string {
  const language: UiLanguage = params.language ?? "ko";
  const stem = sanitizeExportStem(params.baseName, language);
  const ext = normalizeExtension(params.format, params.baseName);

  const rev = params.revisionNumber;
  let tag: string;
  if (typeof rev === "number" && Number.isInteger(rev) && rev >= 1) {
    tag = `${tWps("wps_revision_file_token", language)}${rev}`;
  } else {
    tag = tWps("wps_original_file_token", language);
  }

  return `${stem}_${tag}.${ext}`;
}

export function isWindowsStylePath(rawPath: string): boolean {
  const trimmed = rawPath.trim();
  return (
    WINDOWS_EXTENDED_UNC_RE.test(trimmed) ||
    WINDOWS_EXTENDED_DRIVE_RE.test(trimmed) ||
    WINDOWS_DRIVE_RE.test(trimmed) ||
    WINDOWS_UNC_RE.test(trimmed) ||
    trimmed.includes("\\")
  );
}

function resolvePlatform(
  paths: readonly string[],
  platform: PathPlatform = "auto",
): "win32" | "posix" {
  if (platform === "win32" || platform === "posix") {
    return platform;
  }
  if (paths.some((p) => isWindowsStylePath(p))) {
    return "win32";
  }
  return "posix";
}

function normalizeLexicalSegments(segments: readonly string[], anchored: boolean): string[] {
  const out: string[] = [];
  for (const seg of segments) {
    if (!seg || seg === ".") continue;
    if (seg === "..") {
      if (out.length > 0 && out[out.length - 1] !== "..") {
        out.pop();
      } else if (!anchored) {
        out.push("..");
      }
    } else {
      out.push(seg);
    }
  }
  return out;
}

/**
 * Normalize a file path for deterministic equality checks across slash styles,
 * `.` / `..` segments, Windows extended prefixes (`\\?\`), Unicode NFC/NFD,
 * and Windows case-insensitivity.
 */
export function normalizeComparePath(
  rawPath: string,
  options: { readonly platform?: PathPlatform } = {},
): string {
  if (!rawPath || CONTROL_OR_NUL_RE.test(rawPath)) {
    return "";
  }
  let p = rawPath.normalize("NFC").trim();
  if (!p) return "";

  const plat = resolvePlatform([p], options.platform);

  // Strip Windows extended-length prefixes before normalizing slashes.
  if (WINDOWS_EXTENDED_UNC_RE.test(p)) {
    p = `\\\\${p.slice(8)}`;
  } else if (WINDOWS_EXTENDED_DRIVE_RE.test(p)) {
    p = p.slice(4);
  }

  let prefix = "";
  let anchored = false;
  let rest = p;

  if (WINDOWS_UNC_RE.test(rest)) {
    const unified = rest.replace(/\\/g, "/");
    const uncParts = unified.replace(/^\/+/, "").split("/");
    const server = uncParts[0] ?? "";
    const share = uncParts[1] ?? "";
    prefix = `//${server}/${share}/`;
    anchored = true;
    rest = uncParts.slice(2).join("/");
  } else if (WINDOWS_DRIVE_RE.test(rest)) {
    const drive = rest.slice(0, 2);
    const afterDrive = rest.slice(2).replace(/\\/g, "/");
    if (afterDrive.startsWith("/")) {
      prefix = `${drive}/`;
      anchored = true;
      rest = afterDrive.slice(1);
    } else {
      prefix = drive;
      anchored = false;
      rest = afterDrive;
    }
  } else {
    const unified = rest.replace(/\\/g, "/");
    if (unified.startsWith("/")) {
      prefix = "/";
      anchored = true;
      rest = unified.slice(1);
    } else {
      rest = unified;
    }
  }

  const rawParts = rest.split("/");
  const cleanParts = normalizeLexicalSegments(rawParts, anchored);
  let normalized = `${prefix}${cleanParts.join("/")}`;

  // Trim trailing slash except for root paths (`/`, `C:/`, `//server/share/`).
  if (
    normalized.length > prefix.length &&
    normalized.endsWith("/")
  ) {
    normalized = normalized.slice(0, -1);
  }

  // On Windows, trailing dots/spaces in a filename component are stripped by Win32.
  if (plat === "win32") {
    const splitIdx = normalized.lastIndexOf("/");
    const dirPart = splitIdx >= 0 ? normalized.slice(0, splitIdx + 1) : "";
    const leafPart = (splitIdx >= 0 ? normalized.slice(splitIdx + 1) : normalized).replace(
      /[.\s]+$/,
      "",
    );
    normalized = `${dirPart}${leafPart}`.toLowerCase();
  }

  return normalized;
}

/**
 * Return true when `targetPath` refers to the same file as `sourcePath` (or
 * collides with its `.receipt.json` sidecar). Fail-closed on malformed inputs.
 */
export function isSamePathAsSource(
  targetPath: string,
  sourcePath: string,
  options: { readonly platform?: PathPlatform } = {},
): boolean {
  if (!targetPath || !sourcePath) return false;
  if (CONTROL_OR_NUL_RE.test(targetPath) || CONTROL_OR_NUL_RE.test(sourcePath)) {
    return true;
  }
  const plat = resolvePlatform([targetPath, sourcePath], options.platform);
  const normTarget = normalizeComparePath(targetPath, { platform: plat });
  const normSource = normalizeComparePath(sourcePath, { platform: plat });
  if (!normTarget || !normSource) return true;
  if (normTarget === normSource) return true;

  // Also refuse overwriting the source via the sidecar receipt path or vice versa.
  const normTargetReceipt = normalizeComparePath(`${targetPath}.receipt.json`, {
    platform: plat,
  });
  const normSourceReceipt = normalizeComparePath(`${sourcePath}.receipt.json`, {
    platform: plat,
  });
  return normTarget === normSourceReceipt || normTargetReceipt === normSource;
}

/**
 * Validate a proposed export destination path against filename safety rules
 * and the sacred rule that export must never overwrite the source file.
 */
export function validateExportTarget(params: {
  readonly targetPath: string;
  readonly sourcePath?: string | null;
  readonly protectedPaths?: ReadonlyArray<string | null | undefined>;
  readonly platform?: PathPlatform;
  readonly language?: UiLanguage;
}): ExportTargetValidation {
  const language: UiLanguage = params.language ?? "ko";
  const raw = params.targetPath ?? "";
  if (!raw.trim()) {
    return {
      ok: false,
      code: "empty_name",
      message: tWps("wps_export_empty_name", language),
    };
  }
  if (CONTROL_OR_NUL_RE.test(raw)) {
    return {
      ok: false,
      code: "invalid_name",
      message: tWps("wps_export_invalid_name", language),
    };
  }

  const trimmed = raw.normalize("NFC").trim();
  const unified = trimmed.replace(/\\/g, "/");
  if (unified.endsWith("/")) {
    return {
      ok: false,
      code: "invalid_name",
      message: tWps("wps_export_invalid_name", language),
    };
  }

  const slashIdx = unified.lastIndexOf("/");
  const directory = slashIdx >= 0 ? trimmed.slice(0, slashIdx) : "";
  const filename = slashIdx >= 0 ? trimmed.slice(slashIdx + 1) : trimmed;

  if (
    !filename ||
    filename === "." ||
    filename === ".." ||
    /[<>:"|?*]/.test(filename) ||
    WINDOWS_RESERVED_DEVICE_RE.test(filename) ||
    /[.\s]$/.test(filename)
  ) {
    return {
      ok: false,
      code: "invalid_name",
      message: tWps("wps_export_invalid_name", language),
    };
  }

  const allProtected: string[] = [];
  if (params.sourcePath) allProtected.push(params.sourcePath);
  if (params.protectedPaths) {
    for (const p of params.protectedPaths) {
      if (p) allProtected.push(p);
    }
  }

  for (const protectedPath of allProtected) {
    if (
      isSamePathAsSource(trimmed, protectedPath, { platform: params.platform })
    ) {
      return {
        ok: false,
        code: "target_equals_source",
        message: tWps("wps_export_same_as_source", language),
      };
    }
  }

  const normalizedPath = normalizeComparePath(trimmed, {
    platform: params.platform,
  });
  return {
    ok: true,
    normalizedPath,
    filename,
    directory,
  };
}

/**
 * Join an export directory and filename cleanly while preserving separator style.
 */
export function joinExportPath(directory: string, filename: string): string {
  const cleanFile = filename.replace(/^[\\/]+/, "").trim();
  const cleanDir = directory.trim().replace(/[\\/]+$/, "");
  if (!cleanDir) return cleanFile;
  const sep = cleanDir.includes("\\") ? "\\" : "/";
  return `${cleanDir}${sep}${cleanFile}`;
}
