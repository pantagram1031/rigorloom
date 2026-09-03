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
import { useEffect, useRef, useState } from "react";

import { setState } from "../store";

export function SeatEditor({
  value,
  onCommit,
  onCancel,
  className = "seat-input",
  style,
  caret,
}: {
  value: string;
  onCommit: (next: string) => void;
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
}) {
  const [text, setText] = useState(value);
  const field = useRef<HTMLInputElement>(null);
  const composing = useRef(false);

  useEffect(() => {
    field.current?.focus();
    if (caret === undefined) {
      field.current?.select();
      return;
    }
    const at = Math.max(0, Math.min(caret ?? 0, value.length));
    field.current?.setSelectionRange(at, at);
    // On mount only: re-running this on every keystroke would drag the cursor
    // back to where the click landed, mid-word.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <input
      ref={field}
      className={className}
      data-testid="seat-input"
      value={text}
      style={style}
      aria-label="이 자리에 넣을 값"
      onChange={(e) => setText(e.target.value)}
      onCompositionStart={() => {
        composing.current = true;
      }}
      onCompositionEnd={(e) => {
        composing.current = false;
        // Recorded so the IME harness can tell a composed string from
        // characters injected straight into the field: both look the same in
        // the value, and only one of them exercised the IME.
        setState({ sawComposition: true });
        // The composed syllable arrives here on some IMEs without a further
        // input event, so read it off the element rather than trusting state.
        setText((e.target as HTMLInputElement).value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          if (composing.current || e.nativeEvent.isComposing) return;
          e.preventDefault();
          onCommit(field.current?.value ?? text);
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
        // Every other key, modifiers included, belongs to the field.
        e.stopPropagation();
      }}
      onBlur={() => onCommit(field.current?.value ?? text)}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
