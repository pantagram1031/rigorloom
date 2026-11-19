/**
 * Korean postposition (조사) helpers and template guards.
 *
 * Static UI templates never attach a particle directly to a placeholder
 * (J1 §3.6, C-copy §1). When programmatic prose or dynamic formatting needs
 * an inflected particle, these helpers choose the exact form from the final
 * pronounced syllable (handling 받침, ㄹ 받침 for 으로/로, digits, and Latin
 * tokens) so unresolved forms like `이(가)` never appear on screen.
 */

export type JosaPair =
  | "은/는"
  | "이/가"
  | "을/를"
  | "과/와"
  | "으로/로"
  | "이나/나"
  | "이랑/랑"
  | "아/야"
  | "이여/여"
  | "이어/여"
  | "으로서/로서"
  | "으로써/로써"
  | "으로부터/로부터"
  | "이란/란"
  | "이라/라"
  | "이/";

export interface BatchimInfo {
  readonly hasBatchim: boolean;
  readonly isRieul: boolean;
}

const HANGUL_BASE = 0xac00;
const HANGUL_END = 0xd7a3;
const RIEUL_JONGSEONG = 8;

const TRAILING_IGNORED_RE = /[\s"'`’”)\]}>」』》〉.,!?;:…·-]+$/;

// Digits read in Sino-Korean:
// 0(영)=받침, 1(일)=ㄹ, 2(이)=없음, 3(삼)=받침, 4(사)=없음,
// 5(오)=없음, 6(육)=받침, 7(칠)=ㄹ, 8(팔)=ㄹ, 9(구)=없음.
// Trailing zeros (10 십, 100 백, 1000 천, 10000 만) all have non-ㄹ 받침.
const DIGIT_BATCHIM: Readonly<Record<string, BatchimInfo>> = {
  "0": { hasBatchim: true, isRieul: false },
  "1": { hasBatchim: true, isRieul: true },
  "2": { hasBatchim: false, isRieul: false },
  "3": { hasBatchim: true, isRieul: false },
  "4": { hasBatchim: false, isRieul: false },
  "5": { hasBatchim: false, isRieul: false },
  "6": { hasBatchim: true, isRieul: false },
  "7": { hasBatchim: true, isRieul: true },
  "8": { hasBatchim: true, isRieul: true },
  "9": { hasBatchim: false, isRieul: false },
};

// Acronym/letter-by-letter reading (L=엘, M=엠, N=엔, R=알; others end in vowel).
const ACRONYM_LETTER_BATCHIM: Readonly<Record<string, BatchimInfo>> = {
  L: { hasBatchim: true, isRieul: true },
  M: { hasBatchim: true, isRieul: false },
  N: { hasBatchim: true, isRieul: false },
  R: { hasBatchim: true, isRieul: true },
};

const RIEUL_SENSITIVE_PAIRS: ReadonlySet<JosaPair> = new Set<JosaPair>([
  "으로/로",
  "으로서/로서",
  "으로써/로써",
  "으로부터/로부터",
]);

const UNRESOLVED_JOSA_RE = /(?:이\(가\)|은\(는\)|을\(를\)|과\(와\)|\(으\)로|\(이\)라|\(이\)나)/;

const PLACEHOLDER_JOSA_RE =
  /\{(?:\d+|[A-Za-z_]\w*)\}(?:이\(가\)|은\(는\)|을\(를\)|과\(와\)|\(으\)로|으로서|으로써|으로부터|으로|에서|에게|께서|부터|까지|처럼|보다|이랑|이나|이란|이라|(?:은|는|이|가|을|를|과|와|로|의|도|만|께|랑|나)(?=$|[\s,.·…:;)\]」』”’]))/;

function stripTrailingPunctuation(word: string): string {
  return word.normalize("NFC").trim().replace(TRAILING_IGNORED_RE, "");
}

function inspectLatinEnding(clean: string): BatchimInfo {
  const tokenMatch = clean.match(/([A-Za-z]+)$/);
  if (!tokenMatch) {
    return { hasBatchim: false, isRieul: false };
  }
  const token = tokenMatch[1];
  const lastUpper = token[token.length - 1].toUpperCase();

  // Single uppercase letter or all-uppercase acronym (e.g. PDF, HWPX, XML, JSON, L, M, N)
  if (token === token.toUpperCase()) {
    return ACRONYM_LETTER_BATCHIM[lastUpper] ?? { hasBatchim: false, isRieul: false };
  }

  // Lowercase / mixed-case loanwords & product names (e.g. Rigorloom, file, plan, panel)
  const lower = token.toLowerCase();
  if (lower.endsWith("ng") || lower.endsWith("m") || lower.endsWith("n")) {
    return { hasBatchim: true, isRieul: false };
  }
  if (lower.endsWith("l") || /[aeiouy]le$/.test(lower)) {
    return { hasBatchim: true, isRieul: true };
  }
  return { hasBatchim: false, isRieul: false };
}

/**
 * Inspect whether the final pronounced syllable of `word` carries a batchim
 * (종성) and specifically whether that batchim is ㄹ (needed for 으로/로).
 */
export function inspectBatchim(word: string): BatchimInfo {
  const clean = stripTrailingPunctuation(word);
  if (!clean) {
    return { hasBatchim: false, isRieul: false };
  }

  const last = clean[clean.length - 1];
  const code = last.charCodeAt(0);

  // Modern Hangul syllable block (가..힣)
  if (code >= HANGUL_BASE && code <= HANGUL_END) {
    const jong = (code - HANGUL_BASE) % 28;
    return {
      hasBatchim: jong !== 0,
      isRieul: jong === RIEUL_JONGSEONG,
    };
  }

  // Digits (including multi-digit numerals)
  if (last >= "0" && last <= "9") {
    return DIGIT_BATCHIM[last] ?? { hasBatchim: false, isRieul: false };
  }

  // Latin words and acronyms
  if ((last >= "A" && last <= "Z") || (last >= "a" && last <= "z")) {
    return inspectLatinEnding(clean);
  }

  // Hangul compatibility jamo consonants (ㄱ..ㅎ)
  if (code >= 0x3131 && code <= 0x314e) {
    return { hasBatchim: true, isRieul: code === 0x3139 };
  }

  return { hasBatchim: false, isRieul: false };
}

export function hasBatchim(word: string): boolean {
  return inspectBatchim(word).hasBatchim;
}

export function hasRieulBatchim(word: string): boolean {
  return inspectBatchim(word).isRieul;
}

/**
 * Pick the grammatically correct particle from a slash-separated pair
 * (`"은/는"`, `"이/가"`, `"을/를"`, `"과/와"`, `"으로/로"`, etc.).
 */
export function pickJosa(word: string, pair: JosaPair): string {
  const slashIdx = pair.indexOf("/");
  const withCoda = pair.slice(0, slashIdx);
  const withoutCoda = pair.slice(slashIdx + 1);

  const info = inspectBatchim(word);
  if (!info.hasBatchim) {
    return withoutCoda;
  }
  if (RIEUL_SENSITIVE_PAIRS.has(pair) && info.isRieul) {
    return withoutCoda;
  }
  return withCoda;
}

/**
 * Return `word` followed by the appropriate particle for `pair`.
 * Returns `""` when `word` is empty.
 */
export function withJosa(word: string, pair: JosaPair): string {
  if (!word) {
    return "";
  }
  return `${word}${pickJosa(word, pair)}`;
}

/** Detect unresolved parenthesized particles such as `이(가)` or `(으)로`. */
export function containsUnresolvedJosa(text: string): boolean {
  return UNRESOLVED_JOSA_RE.test(text);
}

/** Detect any Korean particle directly attached to a template placeholder (`{0}을`, `{0}이(가)`, etc.). */
export function hasPlaceholderJosa(template: string): boolean {
  return PLACEHOLDER_JOSA_RE.test(template);
}
