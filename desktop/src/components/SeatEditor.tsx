/**
 * The inline editor. A real `<input>`, mounted in the seat.
 *
 * ONE COMPONENT, TWO SURFACES, and that is the point. 본문 보기 mounts it in
 * the table cell; 페이지 보기 mounts it in the rectangle the runtime placed on
 * the rendered page. Same element, same IME behaviour, same commit path, same
 * `fill_cell` op, same review queue — which is what makes "editing on the page"
 * a new surface rather than a second editor with its own bugs.
 *
 * It lived inside `TextView` until the runtime placed its first real seat and a
 * page click opened an edit state with no field on screen to type into: the
 * overlay had `beginEdit`'s state and the only input element in the app was in
 * a component 페이지 보기 does not mount. Extracting it was the fix, and copying
 * it would have been the defect.
 *
 * That it is a real input element is the whole design, not an implementation
 * detail: Hangul composition belongs to the IME, and only a real text field
 * gets it. A 두벌식 sequence composes in place, the preedit syllable is visible
 * while it is being built, and Backspace decomposes rather than deletes. A
 * keydown-driven buffer would receive the jamo separately and reassemble them
 * wrongly; a contenteditable would fight the composition events. The spike
 * proved this with real scan codes (M13/M14) and `scripts/ime.ps1` re-proves it
 * against this field.
 *
 * `onKeyDown` deliberately ignores Enter while `isComposing` is true. Pressing
 * Enter to CONFIRM a composing syllable is a normal part of typing Korean, and
 * a handler that committed the edit there would end the edit halfway through
 * the user's word.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { setState } from "../store";

export function SeatEditor({
  value,
  onCommit,
  onCancel,
  className = "seat-input",
  style,
  caret,
  multiline: initialMultiline = false,
  allowMultiline = false,
  onMultilineChange,
  onCycleBlank,
  onEscapeExit,
  ariaLabel = "이 자리에 넣을 값",
  placeholder,
}: {
  value: string;
  onCommit: (next: string, reason?: "enter" | "blur") => void;
  onCancel: () => void;
  /** The page surface sizes its field from the seat's rect; the tree does not. */
  className?: string;
  style?: React.CSSProperties;
  /**
   * Where the caret goes, as a character offset the RUNTIME resolved from its
   * own per-character boxes (`charX`, §12.2). `undefined` selects the whole
   * value, which is what a seat wants: an empty cell being filled has nothing
   * to stand inside. `null` means the line carried no character boxes and the
   * click SNAPPED to the front — the same visible result as offset 0 and a
   * different fact, which is why the caller keeps them apart and says which.
   */
  caret?: number | null;
  /** Render a `<textarea>` directly for multi-line values (`lines`). */
  multiline?: boolean;
  /** Allow Shift+Enter in single-line mode to switch cleanly into `<textarea>`. */
  allowMultiline?: boolean;
  onMultilineChange?: (multi: boolean) => void;
  /** Optional blank cycling on Tab / Shift+Tab (Fill mode). */
  onCycleBlank?: (direction: 1 | -1, currentValue: string) => void;
  /** Optional Esc override to return focus to the page sheet container (Ruling H). */
  onEscapeExit?: () => void;
  ariaLabel?: string;
  placeholder?: string;
}) {
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

  useEffect(() => {
    setIsMultiline(Boolean(initialMultiline || value.includes("\n")));
  }, [initialMultiline, value]);

  useEffect(() => {
    const el = currentField();
    if (!el) return;
    el.focus();
    if (switchingRef.current) {
      switchingRef.current = false;
      const pos = Math.max(0, Math.min(nextCaretRef.current ?? el.value.length, el.value.length));
      nextCaretRef.current = null;
      el.setSelectionRange(pos, pos);
      return;
    }
    if (caret === undefined) {
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
    // Recorded so the IME harness can tell a composed string from
    // characters injected straight into the field: both look the same in
    // the value, and only one of them exercised the IME.
    setState({ sawComposition: true });
    // The composed syllable arrives here on some IMEs without a further
    // input event, so read it off the element rather than trusting state.
    setText(e.currentTarget.value);
  };

  const handleKeyDown = (
    e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    if (composing.current || e.nativeEvent.isComposing) {
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
    // Every other key, modifiers included, belongs to the field.
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

  if (isMultiline) {
    return (
      <textarea
        ref={textareaRef}
        className={`${className} seat-input--multiline`}
        data-testid="seat-input"
        value={text}
        style={style}
        rows={Math.max(2, Math.min(6, text.split(/\r?\n/).length + 1))}
        placeholder={placeholder}
        aria-label={ariaLabel}
        onChange={(e) => setText(e.target.value)}
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
      style={style}
      placeholder={placeholder}
      aria-label={ariaLabel}
      onChange={(e) => setText(e.target.value)}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
