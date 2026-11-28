/**
 * The inline editor. A real `<input>` or `<textarea>`, mounted in the seat.
 *
 * Hangul composition belongs to the OS IME, so only a real text control gets
 * it cleanly: `onKeyDown` ignores `Enter`, `Tab`, and `Escape` while
 * `isComposing` or `keyCode === 229` so Korean syllable composition finishes
 * intact before committing.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { wp3t } from "../i18n/v2/wp3";
import {
  editorRunsForInitial,
  runColorSegments,
  type ColoredRun,
} from "../model/runColors.ts";
import { setState, useWorkspace } from "../store";

export interface SeatEditorProps {
  value: string;
  runs?: readonly ColoredRun[];
  onCommit: (next: string, reason?: "enter" | "blur") => void;
  onIdleCommit?: (next: string) => void;
  onValueChange?: (next: string) => void;
  onCompositionStart?: () => void;
  onCancel: () => void;
  className?: string;
  style?: React.CSSProperties;
  /**
   * Caret placement on mount:
   * - `"end"`: place caret at end of existing text (default for cells with text)
   * - `"select"`: select all
   * - `number`: exact UTF-16 offset
   * - `null`: snap to start (0)
   * - `undefined`: legacy default (`select`)
   */
  caret?: number | null | "end" | "select";
  multiline?: boolean;
  allowMultiline?: boolean;
  onMultilineChange?: (multi: boolean) => void;
  onCycleBlank?: (direction: 1 | -1, currentValue: string) => boolean | void;
  onEscapeExit?: () => void;
  ariaLabel?: string;
  placeholder?: string;
  fontCategory?: "serif" | "sans";
  fontFace?: string | null;
  readOnly?: boolean;
  readOnlyMessage?: string;
}

export function SeatEditor({
  value,
  runs,
  onCommit,
  onIdleCommit,
  onValueChange,
  onCompositionStart,
  onCancel,
  className = "rl-seat-input",
  style,
  caret,
  multiline: initialMultiline = false,
  allowMultiline = false,
  onMultilineChange,
  onCycleBlank,
  onEscapeExit,
  ariaLabel,
  placeholder,
  fontCategory = "serif",
  fontFace,
  readOnly = false,
  readOnlyMessage,
}: SeatEditorProps) {
  const language = useWorkspace((s) => s.language);
  const resolvedAriaLabel = ariaLabel ?? wp3t("seat_editor_label", language);
  const resolvedValue = readOnly && readOnlyMessage ? readOnlyMessage : value;
  const [text, setText] = useState(resolvedValue);
  const [isMultiline, setIsMultiline] = useState(
    Boolean(initialMultiline || resolvedValue.includes("\n")),
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const initialValueRef = useRef(resolvedValue);
  const composing = useRef(false);
  const skipBlurRef = useRef(false);
  const switchingRef = useRef(false);
  const nextCaretRef = useRef<number | null>(null);
  const restoreSelectionRef = useRef<[number, number] | null>(null);
  // The coloured mirror is chosen once: on mount when the runs are known, or
  // when they arrive before the person has typed. Switching later would swap
  // the text control under a composition in progress.
  const [mirrored, setMirrored] = useState(() =>
    !readOnly && runColorSegments(editorRunsForInitial(runs, resolvedValue), resolvedValue) !== null);
  const editTimer = useRef<number | undefined>(undefined);
  const idleCommit = useRef(onIdleCommit);
  idleCommit.current = onIdleCommit;

  const clearEditTimer = () => window.clearTimeout(editTimer.current);
  useEffect(() => () => window.clearTimeout(editTimer.current), []);

  const syncMirrorScroll = (
    el: HTMLInputElement | HTMLTextAreaElement | null | undefined,
  ) => {
    const mirror = mirrorRef.current;
    if (!mirror || !el) return;
    if (typeof el.scrollTop === "number") mirror.scrollTop = el.scrollTop;
    if (typeof el.scrollLeft === "number") mirror.scrollLeft = el.scrollLeft;
  };

  const changeText = (next: string) => {
    if (readOnly) return;
    dirtyRef.current = true;
    setText(next);
    onValueChange?.(next);
    clearEditTimer();
    if (!composing.current && idleCommit.current) {
      editTimer.current = window.setTimeout(() => idleCommit.current?.(next), 300);
    }
  };

  const currentField = (): HTMLInputElement | HTMLTextAreaElement | null =>
    isMultiline ? textareaRef.current : inputRef.current;

  // A new value from outside (a proposal landing) refreshes the field only
  // while the person has not typed in it; their text is never replaced.
  const dirtyRef = useRef(false);
  if (!dirtyRef.current) {
    initialValueRef.current = resolvedValue;
  }
  useEffect(() => {
    if (dirtyRef.current) return;
    initialValueRef.current = resolvedValue;
    setText(resolvedValue);
    setIsMultiline(Boolean(initialMultiline || resolvedValue.includes("\n")));
  }, [initialMultiline, resolvedValue]);

  useEffect(() => {
    syncMirrorScroll(currentField());
  });

  const runsArrived = !readOnly &&
    runColorSegments(editorRunsForInitial(runs, initialValueRef.current), initialValueRef.current) !== null;
  useEffect(() => {
    if (mirrored || !runsArrived || dirtyRef.current || composing.current) return;
    const el = currentField();
    if (el && document.activeElement === el) {
      restoreSelectionRef.current = [el.selectionStart ?? el.value.length, el.selectionEnd ?? el.value.length];
      switchingRef.current = true;
    }
    setMirrored(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runsArrived, mirrored]);

  useEffect(() => {
    const el = currentField();
    if (!el) return;
    el.focus();
    if (switchingRef.current && restoreSelectionRef.current) {
      switchingRef.current = false;
      const [start, end] = restoreSelectionRef.current;
      restoreSelectionRef.current = null;
      const len = el.value.length;
      el.setSelectionRange(Math.min(start, len), Math.min(end, len));
      return;
    }
    if (switchingRef.current) {
      switchingRef.current = false;
      const pos = Math.max(
        0,
        Math.min(nextCaretRef.current ?? el.value.length, el.value.length),
      );
      nextCaretRef.current = null;
      el.setSelectionRange(pos, pos);
      return;
    }
    if (caret === "end") {
      const len = el.value.length;
      el.setSelectionRange(len, len);
      return;
    }
    if (caret === undefined || caret === "select") {
      el.select();
      return;
    }
    const at = Math.max(0, Math.min(caret ?? 0, el.value.length));
    el.setSelectionRange(at, at);
    // Focus/selection placement only runs on mount or single->multi switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMultiline, mirrored]);

  const handleCompositionStart = () => {
    composing.current = true;
    clearEditTimer();
    onCompositionStart?.();
  };

  const handleCompositionUpdate = (
    e: React.CompositionEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    composing.current = true;
    const el = e.currentTarget;
    if (el && typeof el.value === "string") {
      changeText(el.value);
    }
    syncMirrorScroll(el);
  };

  const handleCompositionEnd = (
    e: React.CompositionEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    composing.current = false;
    setState({ sawComposition: true });
    changeText(e.currentTarget.value);
    syncMirrorScroll(e.currentTarget);
  };

  const handleInput = (
    e: React.FormEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    const el = e.currentTarget;
    if (el && typeof el.value === "string" && el.value !== text) {
      changeText(el.value);
    }
    syncMirrorScroll(el);
  };

  const handleKeyDown = (
    e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    if (composing.current || e.nativeEvent.isComposing || e.keyCode === 229) {
      e.stopPropagation();
      return;
    }
    const cur = currentField()?.value ?? text;
    if (e.key === "Enter") {
      if (e.shiftKey && allowMultiline && !isMultiline && !readOnly) {
        e.preventDefault();
        const el = inputRef.current;
        const start = el?.selectionStart ?? cur.length;
        const end = el?.selectionEnd ?? cur.length;
        const nextText =
          cur.length === 0 ? cur : `${cur.slice(0, start)}\n${cur.slice(end)}`;
        nextCaretRef.current = cur.length === 0 ? 0 : start + 1;
        switchingRef.current = true;
        changeText(nextText);
        setIsMultiline(true);
        onMultilineChange?.(true);
        e.stopPropagation();
        return;
      }
      if (!isMultiline || e.ctrlKey || e.metaKey || readOnly) {
        e.preventDefault();
        clearEditTimer();
        skipBlurRef.current = true;
        if (readOnly) onCancel(); else onCommit(cur, "enter");
        e.stopPropagation();
        return;
      }
      e.stopPropagation();
      return;
    }
    if (e.key === "Tab" && onCycleBlank) {
      e.preventDefault();
      clearEditTimer();
      skipBlurRef.current = true;
      if (onCycleBlank(e.shiftKey ? -1 : 1, cur) === false) skipBlurRef.current = false;
      e.stopPropagation();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      clearEditTimer();
      skipBlurRef.current = true;
      if (onEscapeExit) {
        onEscapeExit();
      } else {
        onCancel();
      }
      e.stopPropagation();
      return;
    }
    e.stopPropagation();
  };

  const handleBlur = () => {
    if (switchingRef.current) return;
    if (skipBlurRef.current) {
      skipBlurRef.current = false;
      return;
    }
    clearEditTimer();
    if (readOnly) {
      onCancel();
      return;
    }
    onCommit(currentField()?.value ?? text, "blur");
  };

  const fallbackVar =
    fontCategory === "sans" ? "var(--font-page-sans)" : "var(--font-page-serif)";
  const computedFontFamily = fontFace
    ? `"${fontFace.replace(/"/g, "")}", ${fallbackVar}`
    : fallbackVar;

  const mergedStyle: React.CSSProperties = {
    fontFamily: computedFontFamily,
    ...style,
  };
  const effectiveClassName = readOnly ? `${className} rl-seat-input--readonly` : className;
  const effectivePlaceholder = readOnly ? (readOnlyMessage ?? placeholder) : placeholder;
  const validRuns = !readOnly ? editorRunsForInitial(runs, initialValueRef.current) : undefined;
  const runSegments = validRuns ? runColorSegments(validRuns, text) : null;
  const segments = mirrored ? (runSegments ?? [{ text, color: "inherit" }]) : null;

  if (!segments) {
    if (isMultiline) {
      return (
        <textarea
          ref={textareaRef}
          className={`${effectiveClassName} rl-seat-input--multiline`}
          data-testid="seat-input"
          data-readonly={readOnly ? "true" : undefined}
          readOnly={readOnly}
          aria-readonly={readOnly ? "true" : undefined}
          title={readOnlyMessage}
          value={text}
          style={mergedStyle}
          rows={Math.max(2, Math.min(10, text.split(/\r?\n/).length + 1))}
          placeholder={effectivePlaceholder}
          aria-label={resolvedAriaLabel}
          onChange={(e) => changeText(e.target.value)}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          onClick={(e) => e.stopPropagation()}
        />
      );
    }

    return (
      <input
        ref={inputRef}
        className={effectiveClassName}
        data-testid="seat-input"
        data-readonly={readOnly ? "true" : undefined}
        readOnly={readOnly}
        aria-readonly={readOnly ? "true" : undefined}
        title={readOnlyMessage}
        value={text}
        style={mergedStyle}
        placeholder={effectivePlaceholder}
        aria-label={resolvedAriaLabel}
        onChange={(e) => changeText(e.target.value)}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onClick={(e) => e.stopPropagation()}
      />
    );
  }

  const isEngineOverlay = className.includes("rl-engine-edit");
  const wrapClassName = isEngineOverlay
    ? "rl-seat-mirror-wrap rl-engine-edit"
    : "rl-seat-mirror-wrap";
  const wrapStyle: React.CSSProperties | undefined = isEngineOverlay
    ? {
        left: style?.left,
        top: style?.top,
        width: style?.width,
        minHeight: style?.minHeight,
      }
    : undefined;
  const controlStyle: React.CSSProperties = {
    ...mergedStyle,
    ...(isEngineOverlay ? { left: undefined, top: undefined, width: "100%" } : {}),
    position: "relative",
    background: "transparent",
    color: "transparent",
    caretColor: "var(--paper-ink)",
  };
  const mirrorStyle: React.CSSProperties = {
    ...mergedStyle,
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: "100%",
    height: "100%",
    whiteSpace: isMultiline ? "pre-wrap" : "pre",
  };
  const mirroredClassName = `${effectiveClassName} rl-seat-input--mirrored`;
  const mirror = (
    <div
      ref={mirrorRef}
      aria-hidden="true"
      data-testid="seat-mirror"
      className={`${effectiveClassName} rl-seat-mirror${isMultiline ? " rl-seat-input--multiline" : ""}`}
      style={mirrorStyle}
    >
      {segments.map((segment, index) => (
        <span key={index} style={{ color: segment.color }}>
          {segment.text}
        </span>
      ))}
      {isMultiline && text.endsWith("\n") ? "\n" : null}
    </div>
  );

  return (
    <div className={wrapClassName} style={wrapStyle}>
      {mirror}
      {isMultiline ? (
        <textarea
          ref={textareaRef}
          className={`${mirroredClassName} rl-seat-input--multiline`}
          data-testid="seat-input"
          data-readonly={readOnly ? "true" : undefined}
          readOnly={readOnly}
          aria-readonly={readOnly ? "true" : undefined}
          title={readOnlyMessage}
          value={text}
          style={controlStyle}
          rows={Math.max(2, Math.min(10, text.split(/\r?\n/).length + 1))}
          placeholder={effectivePlaceholder}
          aria-label={resolvedAriaLabel}
          onChange={(e) => {
            changeText((e.currentTarget ?? e.target).value);
            syncMirrorScroll(e.currentTarget);
          }}
          onInput={handleInput}
          onScroll={(e) => syncMirrorScroll(e.currentTarget)}
          onCompositionStart={handleCompositionStart}
          onCompositionUpdate={handleCompositionUpdate}
          onCompositionEnd={handleCompositionEnd}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <input
          ref={inputRef}
          className={mirroredClassName}
          data-testid="seat-input"
          data-readonly={readOnly ? "true" : undefined}
          readOnly={readOnly}
          aria-readonly={readOnly ? "true" : undefined}
          title={readOnlyMessage}
          value={text}
          style={controlStyle}
          placeholder={effectivePlaceholder}
          aria-label={resolvedAriaLabel}
          onChange={(e) => {
            changeText((e.currentTarget ?? e.target).value);
            syncMirrorScroll(e.currentTarget);
          }}
          onInput={handleInput}
          onScroll={(e) => syncMirrorScroll(e.currentTarget)}
          onCompositionStart={handleCompositionStart}
          onCompositionUpdate={handleCompositionUpdate}
          onCompositionEnd={handleCompositionEnd}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          onClick={(e) => e.stopPropagation()}
        />
      )}
    </div>
  );
}
