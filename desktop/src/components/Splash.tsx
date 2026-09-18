/**
 * The entrance. Tied to Home readiness, skippable by click, once per launch.
 *
 * It exists because the measured cold start spends time in WebView2 and the
 * sidecar before a person can use the window. A blank pane spends that time
 * looking broken; the mark weaving itself spends it saying an application
 * started. The timer is a cap, not the dismiss rule — dismiss happens when
 * Home is ready to show, or when the person clicks.
 *
 * It never replays. `entranceDone` lives in the store and a view switch does
 * not touch it — re-running the entrance on every navigation is exactly the
 * "website" tell this slice is removing. Smoke `hold-entrance` pins it open.
 */
import { useEffect, useState } from "react";

import { Logo } from "./Logo";

const TOTAL_MS = 160;
const FADE_MS = 200;

export function Splash({
  note,
  onDone,
  /** Screenshot support: hold the entrance open instead of letting it finish. */
  frozen = false,
  /** Home is mounted and may be uncovered. Not a wall-clock timer. */
  ready = false,
}: {
  note: string;
  onDone: () => void;
  frozen?: boolean;
  ready?: boolean;
}) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (frozen) return;
    if (!ready) {
      const cap = window.setTimeout(onDone, TOTAL_MS + FADE_MS);
      return () => window.clearTimeout(cap);
    }
    setLeaving(true);
    onDone();
    return undefined;
  }, [onDone, frozen, ready]);

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
