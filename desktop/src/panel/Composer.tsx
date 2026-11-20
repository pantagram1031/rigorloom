import { useRef, type KeyboardEvent } from "react";

import { openSettings } from "../shell/bindings";
import { isComposingEvent } from "../shell/keys";
import type { UiLanguage } from "../i18n/vocabulary";
import { composerBlocker, composerDraftAfterSend, composerDraftOf, setComposerDraft, useComposerDraftText, useWorkspace } from "../store";
import { cancelRequest, clearContext, sendRequest } from "./actions";
import { Keycap } from "../ui/Keycap";
import { tp } from "./i18n";
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
  const text = useComposerDraftText();
  const context = panelSlice.use(doc, (s) => s.context);
  const mode = composerMode(blocker, provider, Boolean(doc));
  const ref = useRef<HTMLTextAreaElement | null>(null);

  if (mode === "disconnected" || mode === "no_document") {
    return (
      <div className="rp-composer rp-composer--off" data-testid="composer" data-state="disconnected">
        <span className="rp-composer-off">{tp("wp4_composer_disconnected", lang)}</span>
        <button type="button" className="rp-link" onClick={() => openSettings("settings:agent")} data-testid="composer-connect">
          {tp("wp4_composer_connect", lang)}
        </button>
      </div>
    );
  }

  const send = async () => {
    const value = text.trim();
    if (!value || mode === "working") return;
    // The draft belongs to the document it was typed for, even if the person
    // switches tabs while the send is in flight.
    const at = doc;
    setComposerDraft("", at);
    const ok = await sendRequest(value);
    if (!ok) setComposerDraft(composerDraftAfterSend(composerDraftOf(at).text, value, false), at);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingEvent(e.nativeEvent)) return;
    if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.stopPropagation();
      e.preventDefault();
      void send();
    } else if (e.key === "Escape") {
      e.stopPropagation();
      e.preventDefault();
      if (mode === "working") void cancelRequest();
      else ref.current?.blur();
    }
  };

  return (
    <div className="rp-composer" data-testid="composer" data-state={mode}>
      {mode === "working" ? <div className="rp-composer-line" aria-hidden="true" /> : null}
      <div className="rp-composer-top">
        {mode === "test" ? <span className="rp-tag rp-tag--test" data-source="test">{tp("wp4_source_test", lang)}</span> : null}
        {context ? (
          <span className="rp-chip" data-testid="composer-context">
            {context}
            <button type="button" className="rp-chip-x" aria-label={tp("wp4_composer_context_remove", lang)} onClick={() => clearContext()}>
              ×
            </button>
          </span>
        ) : null}
        <Keycap keys={["Ctrl", "L"]} />
      </div>
      <textarea
        ref={ref}
        className="rp-composer-input"
        rows={2}
        value={text}
        placeholder={mode === "test" ? tp("wp4_composer_placeholder_test", lang) : tp("wp4_composer_placeholder", lang)}
        aria-label={tp("wp4_composer_aria", lang)}
        onChange={(e) => setComposerDraft(e.target.value)}
        onKeyDown={onKey}
        data-testid="composer-input"
      />
      <div className="rp-composer-actions">
        {mode === "working" ? (
          <button type="button" className="rp-btn" onClick={() => void cancelRequest()} data-testid="composer-cancel">
            {tp("wp4_composer_cancel", lang)}
            <Keycap keys={["Esc"]} />
          </button>
        ) : (
          <button type="button" className="rp-btn" onClick={() => void send()} disabled={!text.trim()} data-testid="composer-send">
            {tp("wp4_composer_send", lang)}
            <Keycap keys={["Enter"]} />
          </button>
        )}
      </div>
    </div>
  );
}
