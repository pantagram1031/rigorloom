/**
 * The entrance. 700 ms, once per launch, skippable by click.
 *
 * It exists because the measured cold start is about 1.5 s to a usable window
 * (spike finding 4) and that time has to be spent somewhere. A blank pane
 * spends it looking broken; the mark weaving itself spends it saying an
 * application started. The panes then rise in a 60 ms stagger, so the layout
 * assembles rather than appearing.
 *
 * It never replays. `entranceDone` lives in the store and a view switch does
 * not touch it — re-running the entrance on every navigation is exactly the
 * "website" tell this slice is removing.
 */
import { useEffect, useState } from "react";

import { Logo } from "./Logo";

const TOTAL_MS = 700;
const FADE_MS = 260;

export function Splash({
  note,
  onDone,
  /** Screenshot support: hold the entrance open instead of letting it finish. */
  frozen = false,
}: {
  note: string;
  onDone: () => void;
  frozen?: boolean;
}) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (frozen) return;
    const start = window.setTimeout(() => setLeaving(true), TOTAL_MS);
    const end = window.setTimeout(onDone, TOTAL_MS + FADE_MS);
    return () => {
      window.clearTimeout(start);
      window.clearTimeout(end);
    };
  }, [onDone, frozen]);

  return (
    <div
      className={`splash${leaving ? " leaving" : ""}`}
      data-testid="splash"
      onClick={frozen ? undefined : onDone}
      role="presentation"
      title="눌러서 건너뛰기"
    >
      <Logo size={72} draw />
      <div className="wordmark">Rigorloom</div>
      <p className="note">{note}</p>
    </div>
  );
}
