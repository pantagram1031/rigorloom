import { useRef, type KeyboardEvent } from "react";

import { openOperatorModal } from "../actions";
import type { UiLanguage } from "../i18n/vocabulary";
import { composerBlocker, setComposerDraft, useWorkspace } from "../store";
import { cancelRequest, clearContext, sendRequest } from "./actions";
import { Keycaps } from "./bits";
import { tp } from "./i18n";
import { eventIsComposing } from "./keys";
import { panelSlice } from "./state";

export type ComposerMode = "ready" | "test" | "disconnected" | "working" | "no_document";

/** The composer's state from the store's blocker and provider. */
export function composerMode(blocker: string | null, provider: string, hasDocument: boolean): ComposerMode {
  if (!hasDocument || blocker === "no_document") return "no_document";
  if (blocker === "busy") return "working";
  if (blocker !== null) return "disconnected";
  return provider === "mock" ? "test" : "ready";
}

export function Composer({ lang }: { lang: UiLanguage }) {
  const doc = useWorkspace((s) => s.activeSessionId);
  const blocker = useWorkspace(composerBlocker);
  const provider = useWorkspace((s) => s.provider.provider);
  const text = useWorkspace((s) => s.composerDraft.text);
  const context = panelSlice.use(doc, (s) => s.context);
  const mode = composerMode(blocker, provider, Boolean(doc));
  const ref = useRef<HTMLTextAreaElement | null>(null);

  if (mode === "disconnected" || mode === "no_document") {
    return (
      <div className="rp-composer rp-composer--off" data-testid="composer" data-state="disconnected">
        <span className="rp-composer-off">{tp("composer_disconnected", lang)}</span>
        <button type="button" className="rp-link" onClick={() => openOperatorModal()} data-testid="composer-connect">
          {tp("composer_connect", lang)}
        </button>
      </div>
    );
  }

  const send = async () => {
    const value = text.trim();
    if (!value || mode === "working") return;
    setComposerDraft("");
    const ok = await sendRequest(value);
    if (!ok) setComposerDraft(value);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (eventIsComposing(e)) return;
    e.stopPropagation();
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (mode === "working") void cancelRequest();
      else ref.current?.blur();
    }
  };

  return (
    <div className="rp-composer" data-testid="composer" data-state={mode}>
      {mode === "working" ? <div className="rp-composer-line" aria-hidden="true" /> : null}
      <div className="rp-composer-top">
        {mode === "test" ? <span className="rp-tag rp-tag--test" data-source="test">{tp("source_test", lang)}</span> : null}
        {context ? (
          <span className="rp-chip" data-testid="composer-context">
            {context}
            <button type="button" className="rp-chip-x" aria-label={tp("composer_context_remove", lang)} onClick={() => clearContext()}>
              ×
            </button>
          </span>
        ) : null}
        <Keycaps keys={["Ctrl", "L"]} />
      </div>
      <textarea
        ref={ref}
        className="rp-composer-input"
        rows={2}
        value={text}
        placeholder={mode === "test" ? tp("composer_placeholder_test", lang) : tp("composer_placeholder", lang)}
        aria-label={tp("composer_aria", lang)}
        onChange={(e) => setComposerDraft(e.target.value)}
        onKeyDown={onKey}
        data-testid="composer-input"
      />
      <div className="rp-composer-actions">
        {mode === "working" ? (
          <button type="button" className="rp-btn" onClick={() => void cancelRequest()} data-testid="composer-cancel">
            {tp("composer_cancel", lang)}
            <Keycaps keys={["Esc"]} />
          </button>
        ) : (
          <button type="button" className="rp-btn" onClick={() => void send()} disabled={!text.trim()} data-testid="composer-send">
            {tp("composer_send", lang)}
            <Keycaps keys={["Enter"]} />
          </button>
        )}
      </div>
    </div>
  );
}
