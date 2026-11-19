/**
 * Single canonical date and time formatter for Rigorloom editor v2.
 *
 * Enforces one consistent format across Start recents, History nodes, thread
 * messages, and approval boxes:
 * - Korean full: `11월 17일 오후 1:13`
 * - Korean time: `오후 2:31`
 * - English full: `Nov 17, 1:13 PM`
 * - English time: `2:31 PM`
 *
 * Never emits relative labels (`오늘`, `어제`), raw ISO timestamps, or
 * `"Invalid Date"` (C#16, J1 §1 defect 36, J1 §5).
 */
import { tWps } from "../i18n/v2/wps.ts";
import type { UiLanguage } from "../types.ts";

export type DateInput = Date | number | string | null | undefined;

export interface DateFormatOptions {
  /** Optional IANA time zone (e.g. "Asia/Seoul", "UTC"). Defaults to local time zone. */
  readonly timeZone?: string;
  /** Test/screenshot override string; falls back to `data-capture-fixed-time` when `useCaptureOverride` is true. */
  readonly fixedTime?: string | null;
  /** Read `document.documentElement[data-capture-fixed-time]` when present (default: false). */
  readonly useCaptureOverride?: boolean;
  /** Value returned when the input is missing or unparseable (default: ""). */
  readonly emptyFallback?: string;
}

export const CAPTURE_FIXED_TIME_ATTR = "data-capture-fixed-time";

const EN_SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

interface CalendarParts {
  readonly month: number; // 1..12
  readonly day: number; // 1..31
  readonly hour24: number; // 0..23
  readonly minute: number; // 0..59
}

export function readCaptureFixedTime(): string | null {
  if (typeof document === "undefined") return null;
  const val = document.documentElement?.getAttribute(CAPTURE_FIXED_TIME_ATTR);
  return val && val.trim().length > 0 ? val.trim() : null;
}

export function parseDateInput(value: DateInput): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isFinite(value.getTime()) ? new Date(value.getTime()) : null;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    const d = new Date(value);
    return Number.isFinite(d.getTime()) ? d : null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const ms = Date.parse(trimmed);
    if (!Number.isFinite(ms)) return null;
    return new Date(ms);
  }
  return null;
}

function extractCalendarParts(date: Date, timeZone?: string): CalendarParts {
  if (timeZone) {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone,
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
        hourCycle: "h23",
      }).formatToParts(date);
      let month = date.getMonth() + 1;
      let day = date.getDate();
      let hour24 = date.getHours();
      let minute = date.getMinutes();
      for (const p of parts) {
        if (p.type === "month") month = Number(p.value);
        else if (p.type === "day") day = Number(p.value);
        else if (p.type === "hour") hour24 = Number(p.value) % 24;
        else if (p.type === "minute") minute = Number(p.value);
      }
      if (
        Number.isFinite(month) &&
        Number.isFinite(day) &&
        Number.isFinite(hour24) &&
        Number.isFinite(minute)
      ) {
        return { month, day, hour24, minute };
      }
    } catch {
      // Invalid timeZone falls back cleanly to local calendar getters.
    }
  }
  return {
    month: date.getMonth() + 1,
    day: date.getDate(),
    hour24: date.getHours(),
    minute: date.getMinutes(),
  };
}

function toClockParts(hour24: number, minute: number, language: UiLanguage): {
  readonly period: string;
  readonly hour12: string;
  readonly minutePadded: string;
} {
  const isPm = hour24 >= 12;
  const hour12Num = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return {
    period: tWps(isPm ? "wps_date_pm" : "wps_date_am", language),
    hour12: String(hour12Num),
    minutePadded: String(minute).padStart(2, "0"),
  };
}

/**
 * Format a date/time in the single application format:
 * - ko: `11월 17일 오후 1:13`
 * - en: `Nov 17, 1:13 PM`
 */
export function formatAppDateTime(
  value: DateInput,
  language: UiLanguage = "ko",
  options: DateFormatOptions = {},
): string {
  const parsed = parseDateInput(value);
  if (!parsed) {
    return options.emptyFallback ?? "";
  }
  const fixed =
    options.fixedTime ??
    (options.useCaptureOverride ? readCaptureFixedTime() : null);
  if (fixed) {
    return fixed;
  }

  const { month, day, hour24, minute } = extractCalendarParts(
    parsed,
    options.timeZone,
  );
  const { period, hour12, minutePadded } = toClockParts(hour24, minute, language);
  const monthToken =
    language === "en" ? (EN_SHORT_MONTHS[month - 1] ?? String(month)) : String(month);

  return tWps("wps_date_time_format", language, [
    monthToken,
    String(day),
    period,
    hour12,
    minutePadded,
  ]);
}

/**
 * Format a clock time for compact approval-box and agent-thread entries:
 * - ko: `오후 2:31`
 * - en: `2:31 PM`
 */
export function formatAppTime(
  value: DateInput,
  language: UiLanguage = "ko",
  options: DateFormatOptions = {},
): string {
  const parsed = parseDateInput(value);
  if (!parsed) {
    return options.emptyFallback ?? "";
  }
  const fixed =
    options.fixedTime ??
    (options.useCaptureOverride ? readCaptureFixedTime() : null);
  if (fixed) {
    return fixed;
  }

  const { hour24, minute } = extractCalendarParts(parsed, options.timeZone);
  const { period, hour12, minutePadded } = toClockParts(hour24, minute, language);
  return tWps("wps_time_format", language, [period, hour12, minutePadded]);
}

/** Convenience helper returning the localized unknown-timestamp label on invalid input. */
export function formatHistoryDateTime(
  value: DateInput,
  language: UiLanguage = "ko",
  options: Omit<DateFormatOptions, "emptyFallback"> = {},
): string {
  return formatAppDateTime(value, language, {
    ...options,
    emptyFallback: tWps("wps_date_unknown", language),
  });
}
