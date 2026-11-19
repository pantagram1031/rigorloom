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
import { setState, useWorkspace } from "../store";

export interface SeatEditorProps {
  value: string;
  onCommit: (next: string, reason?: "enter" | "blur") => void;
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
  onCycleBlank?: (direction: 1 | -1, currentValue: string) => void;
  onEscapeExit?: () => void;
  ariaLabel?: string;
  placeholder?: string;
  fontCategory?: "serif" | "sans";
  fontFace?: string | null;
}

export function SeatEditor({
  value,
  onCommit,
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
}: SeatEditorProps) {
  const language = useWorkspace((s) => s.language);
  const resolvedAriaLabel = ariaLabel ?? wp3t("seat_editor_label", language);
  const [text, setText] = useState(value);
  const [isMultiline, setIsMultiline] = useState(
    Boolean(initialMultiline || value.includes("\n")),
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const skipBlurRef = useRef(false);
  const switchingRef = useRef(false);
  const nextCaretRef = useRef<number | null>(null);

  const currentField = (): HTMLInputElement | HTMLTextAreaElement | null =>
    isMultiline ? textareaRef.current : inputRef.current;

  // A new value from outside (a proposal landing) refreshes the field only
  // while the person has not typed in it; their text is never replaced.
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (dirtyRef.current) return;
    setText(value);
    setIsMultiline(Boolean(initialMultiline || value.includes("\n")));
  }, [initialMultiline, value]);

  useEffect(() => {
    const el = currentField();
    if (!el) return;
    el.focus();
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
  }, [isMultiline]);

  const handleCompositionStart = () => {
    composing.current = true;
  };

  const handleCompositionEnd = (
    e: React.CompositionEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    composing.current = false;
    setState({ sawComposition: true });
    setText(e.currentTarget.value);
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
      if (e.shiftKey && allowMultiline && !isMultiline) {
        e.preventDefault();
        const el = inputRef.current;
        const start = el?.selectionStart ?? cur.length;
        const end = el?.selectionEnd ?? cur.length;
        const nextText =
          cur.length === 0 ? cur : `${cur.slice(0, start)}\n${cur.slice(end)}`;
        nextCaretRef.current = cur.length === 0 ? 0 : start + 1;
        switchingRef.current = true;
        setText(nextText);
        setIsMultiline(true);
        onMultilineChange?.(true);
        e.stopPropagation();
        return;
      }
      if (!isMultiline || e.ctrlKey || e.metaKey) {
        e.preventDefault();
        skipBlurRef.current = true;
        onCommit(cur, "enter");
        e.stopPropagation();
        return;
      }
      e.stopPropagation();
      return;
    }
    if (e.key === "Tab" && onCycleBlank) {
      e.preventDefault();
      skipBlurRef.current = true;
      onCycleBlank(e.shiftKey ? -1 : 1, cur);
      e.stopPropagation();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
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

  if (isMultiline) {
    return (
      <textarea
        ref={textareaRef}
        className={`${className} rl-seat-input--multiline`}
        data-testid="seat-input"
        value={text}
        style={mergedStyle}
        rows={Math.max(2, Math.min(10, text.split(/\r?\n/).length + 1))}
        placeholder={placeholder}
        aria-label={resolvedAriaLabel}
        onChange={(e) => {
          dirtyRef.current = true;
          setText(e.target.value);
        }}
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
      className={className}
      data-testid="seat-input"
      value={text}
      style={mergedStyle}
      placeholder={placeholder}
      aria-label={resolvedAriaLabel}
      onChange={(e) => {
          dirtyRef.current = true;
          setText(e.target.value);
        }}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
