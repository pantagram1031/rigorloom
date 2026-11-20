import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { UiLanguage } from "../i18n/vocabulary";
import {
  canConfirm,
  gateState,
  isChangedFact,
  needsLook,
  rangeDigest,
  rangeText,
  requiredTicks,
  shortHash,
  tallyByOp,
  type ChangeItem,
  type ChangeSetView,
  type GuardFact,
} from "../model/changes";
import { useWorkspace } from "../store";
import { closeApproval, confirmApproval, prepareConfirmation, select, toggleTick } from "./actions";
import { ApprovalBox } from "../ui/ApprovalBox";
import { Keycap } from "../ui/Keycap";
import { Parts } from "./bits";
import { checkText, proposerText } from "./ChangesPane";
import { revisionName, tp } from "./i18n";
import { isComposingEvent } from "../shell/keys";
import { panelSlice } from "./state";

function factValue(v: string | null, lang: UiLanguage): string {
  return v && v.trim() ? v : tp("wp4_sheet_fact_value_none", lang);
}

function ClauseQuote({ fact }: { fact: GuardFact }) {
  const clause = fact.clause ?? "";
  const word = fact.word ?? "";
  const at = word ? clause.lastIndexOf(word) : -1;
  if (at < 0) return <q className="rp-quote">{clause}</q>;
  return (
    <q className="rp-quote">
      {clause.slice(0, at)}
      <u>{word}</u>
      {clause.slice(at + word.length)}
    </q>
  );
}

function ExpectedRow({ item, lang }: { item: ChangeItem; lang: UiLanguage }) {
  const [open, setOpen] = useState(false);
  const fact = item.guard.facts.find((f) => f.clause) ?? item.guard.facts[0] ?? null;
  return (
    <li className="rp-sheet-expected" data-testid={`sheet-expected-${item.n}`}>
      <div className="rp-sheet-expected-head">
        <button type="button" className="rp-link rp-link--plain" onClick={() => select(item.id)}>
          <span className="rp-num">{item.n}</span> {tp("wp4_sheet_expected_row", lang, [item.label, item.opName])}
        </button>
        {fact ? (
          <button type="button" className="rp-link" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="expected-toggle">
            {open ? tp("wp4_sheet_expected_hide", lang) : tp("wp4_sheet_expected_view", lang)}
          </button>
        ) : null}
      </div>
      {open && fact ? (
        <div className="rp-sheet-expected-body">
          {fact.sentence ? <p className="rp-sentence">{fact.sentence}</p> : null}
          {fact.clause ? <ClauseQuote fact={fact} /> : null}
        </div>
      ) : null}
    </li>
  );
}

function CopyHash({ label, value, lang, testId }: { label: string; value: string; lang: UiLanguage; testId: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rp-kv">
      <span className="rp-kv-k">{label}</span>
      <code className="rp-mono" title={value} data-testid={testId}>
        {shortHash(value)}
      </code>
      <button
        type="button"
        className="rp-link"
        data-testid={`${testId}-copy`}
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(
            () => setCopied(true),
            () => setCopied(false),
          );
        }}
      >
        {copied ? tp("wp4_sheet_copied", lang) : tp("wp4_sheet_copy", lang)}
      </button>
    </div>
  );
}

export function ApprovalSheet({ view, lang, guardState }: { view: ChangeSetView; lang: UiLanguage; guardState: string }) {
  const doc = useWorkspace((s) => s.activeSessionId);
  const sessionSha = useWorkspace((s) => s.sessions.find((x) => x.sessionId === s.activeSessionId)?.source.sha256 ?? "");
  const st = panelSlice.use(doc, (s) => s);
  const accepted = view.items.filter((it) => it.decision === "accepted");
  const facts = accepted.filter(isChangedFact);
  const untied = view.untied ?? [];
  const expected = accepted.filter((it) => it.guard.status === "expected" && needsLook(it));
  const ticks = requiredTicks(view);
  const busy = st.confirmPhase === "pruning" || st.confirmPhase === "requesting" || st.confirmPhase === "applying";
  const gate = gateState(view);
  const ready = canConfirm(view, st.ticks, gate) && !busy;
  const rootRef = useRef<HTMLElement | null>(null);
  const resultRevision = Math.max(view.base.revision, view.stale?.current ?? 0) + 1;

  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  // The sheet as rendered asks the bridge for its single-use confirmation
  // token, bound to this document, plan and base.
  useEffect(() => {
    prepareConfirmation();
  }, [doc, view.id, view.planHash, view.base.sha256]);

  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (isComposingEvent(e.nativeEvent)) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeApproval();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      const target = e.target as HTMLElement;
      // A focused button or link keeps its own Enter.
      if (target.tagName === "BUTTON" && !target.hasAttribute("data-confirm")) return;
      e.preventDefault();
      e.stopPropagation();
      if (ready) void confirmApproval();
    }
  };

  const confirmLabel =
    st.confirmPhase === "pruning" || st.confirmPhase === "requesting"
      ? tp("wp4_step_checking", lang)
      : st.confirmPhase === "applying"
        ? tp("wp4_step_applying", lang)
        : tp("wp4_sheet_confirm", lang);

  return (
    <section
      ref={rootRef}
      className="rp-sheet"
      role="dialog"
      aria-modal="false"
      aria-label={tp("wp4_sheet_aria", lang)}
      tabIndex={-1}
      onKeyDown={onKey}
      data-testid="approve-sheet"
      data-docked=""
    >
      <header className="rp-sheet-head">
        <div>
          <h2 className="rp-sheet-title">{tp("wp4_sheet_title", lang, [accepted.length])}</h2>
          <p className="rp-sheet-tally">
            {tallyByOp(accepted)
              .map((t) => tp("wp4_sheet_tally_item", lang, [t.opName, t.count]))
              .join(" · ")}
          </p>
        </div>
        <button type="button" className="rp-btn rp-btn--quiet" onClick={() => closeApproval()} aria-label={tp("wp4_sheet_close", lang)}>
          <Keycap keys={["Esc"]} />
        </button>
      </header>

      <div className="rp-sheet-body">
        <ApprovalBox
          lang={lang}
          data-testid="sheet-box"
          hasChangedFact={ticks.includes("facts")}
          propose={proposerText({ ...view, items: accepted }, lang)}
          check={<Parts text={checkText(view, lang, guardState)} />}
          approve={null}
        />

        {ticks.includes("facts") ? (
          <div className="rp-sheet-facts" data-fact="" data-testid="sheet-facts">
            <ul>
              {facts.map((it) =>
                it.guard.facts
                  .filter((f) => !f.expected)
                  .map((f, i) => (
                    <li key={`${it.id}-${i}`}>
                      <button type="button" className="rp-link rp-link--plain" onClick={() => select(it.id)}>
                        <span className="rp-num">{it.n}</span>{" "}
                        {tp("wp4_sheet_fact_row", lang, [it.label, factValue(f.before, lang), factValue(f.after, lang)])}
                      </button>
                    </li>
                  )),
              )}
              {untied.map(({ paragraph, before, after }) => (
                <li key={paragraph} data-testid={`sheet-untied-${paragraph}`}>
                  {tp("wp4_sheet_untied_row", lang, [paragraph, after || before])}
                </li>
              ))}
            </ul>
            <label className="rp-tick">
              <input
                type="checkbox"
                checked={st.ticks.includes("facts")}
                onChange={() => toggleTick("facts")}
                data-testid="tick-facts"
              />
              {tp("wp4_sheet_tick_facts", lang)}
            </label>
          </div>
        ) : null}

        {expected.length > 0 ? (
          <ul className="rp-sheet-expected-list" data-testid="sheet-expected">
            {expected.map((it) => (
              <ExpectedRow key={it.id} item={it} lang={lang} />
            ))}
          </ul>
        ) : null}

        {ticks.includes("test") ? (
          <div className="rp-sheet-test" data-testid="sheet-test">
            <label className="rp-tick">
              <input type="checkbox" checked={st.ticks.includes("test")} onChange={() => toggleTick("test")} data-testid="tick-test" />
              <span className="rp-tag rp-tag--test">{tp("wp4_source_test", lang)}</span>
              {tp("wp4_sheet_tick_test", lang)}
            </label>
          </div>
        ) : null}

        <div className="rp-kvs">
          <div className="rp-kv">
            <span className="rp-kv-k">{tp("wp4_sheet_base", lang)}</span>
            <span className="rp-kv-v">{revisionName(view.base.revision, lang)}</span>
          </div>
          <div className="rp-kv">
            <span className="rp-kv-k">{tp("wp4_sheet_result", lang)}</span>
            <span className="rp-kv-v">{revisionName(resultRevision, lang)}</span>
          </div>
          <details className="rp-details" data-testid="sheet-details">
            <summary>{tp("wp4_sheet_details", lang)}</summary>
            <CopyHash label={tp("wp4_sheet_doc_hash", lang)} value={view.base.sha256 || sessionSha} lang={lang} testId="hash-doc" />
            <CopyHash label={tp("wp4_sheet_plan_hash", lang)} value={view.planHash} lang={lang} testId="hash-plan" />
          </details>
        </div>

        <ol className="rp-digest" aria-label={tp("wp4_sheet_digest_aria", lang)} data-testid="sheet-digest">
          {rangeDigest(accepted).map((row) => (
            <li key={row.firstId}>
              <button type="button" className="rp-digest-row" onClick={() => select(row.firstId)}>
                <span className="rp-num">{rangeText(row.from, row.to)}</span>
                <span className="rp-digest-label">{row.labels.slice(0, 3).join(" · ")}</span>
                <span className="rp-digest-ops">{row.opNames.join(" · ")}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>

      <footer className="rp-sheet-foot">
        {gate.block?.kind === "diff_mismatch" ? (
          <p className="rp-sheet-error" role="alert">{tp("wp4_sheet_diff_mismatch", lang)}</p>
        ) : null}
        <p className="rp-sheet-note" data-testid="guard-scope">
          {guardState === "unavailable" ? tp("wp4_sheet_guard_skipped", lang) : tp("wp4_sheet_guard_scope", lang)}
        </p>
        <p className="rp-sheet-note" data-testid="sheet-effect">
          {tp("wp4_sheet_effect", lang)}
        </p>
        {st.confirmPhase === "failed" && st.confirmError ? (
          <p className="rp-sheet-error" role="alert" data-testid="sheet-error">
            {st.confirmError}
          </p>
        ) : null}
        <div className="rp-sheet-actions">
          <button type="button" className="rp-btn" onClick={() => closeApproval()} disabled={busy} data-testid="approve-cancel">
            {tp("wp4_sheet_cancel", lang)}
            <Keycap keys={["Esc"]} />
          </button>
          <button
            type="button"
            className="rp-btn rp-btn--primary"
            data-variant="primary"
            data-confirm=""
            data-testid="approve-confirm"
            disabled={!ready}
            aria-busy={busy || undefined}
            onClick={() => void confirmApproval()}
          >
            {confirmLabel}
            {busy ? null : <Keycap keys={["Enter"]} />}
          </button>
        </div>
      </footer>
    </section>
  );
}
