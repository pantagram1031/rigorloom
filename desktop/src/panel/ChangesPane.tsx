import { useCanvasSlice } from "../canvas/controller";
import { isComposingEvent } from "../shell/keys";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { errorCodeMessage, type UiLanguage } from "../i18n/vocabulary";
import {
  canDecide,
  filterChanges,
  gateState,
  tallyBySource,
  type ChangeFilter,
  type ChangeSetView,
  type GateState,
} from "../model/changes";
import { exportApplied } from "../actions";
import { useWorkspace } from "../store";
import {
  closeReturn,
  openApproval,
  openReturn,
  proposeAgainOnHead,
  returnProposal,
  setFilter,
  setTab,
} from "./actions";
import { ApprovalBox } from "../ui/ApprovalBox";
import { Keycap } from "../ui/Keycap";
import { Parts, proposerLine, sourceLabel } from "./bits";
import { ChangeItemRow } from "./ChangeItemRow";
import { clockTime, revisionName, tp } from "./i18n";
import { panelSlice, type AppliedRecord } from "./state";

// --- header -------------------------------------------------------------------------

function Filters({ view, filter, lang }: { view: ChangeSetView; filter: ChangeFilter; lang: UiLanguage }) {
  const c = gateState(view).counts;
  const entries: Array<[ChangeFilter, string, number]> = [
    ["all", tp("wp4_filter_all", lang), c.total],
    ["pending", tp("wp4_filter_pending", lang), c.pending],
    ["accepted", tp("wp4_filter_accepted", lang), c.accepted],
    ["rejected", tp("wp4_filter_rejected", lang), c.rejected],
  ];
  if (c.attn > 0) entries.push(["attn", tp("wp4_filter_attn", lang), c.attn]);
  return (
    <div className="rp-filters" role="group" aria-label={tp("wp4_filters_aria", lang)} data-testid="change-filters">
      {entries.map(([key, label, n]) => (
        <button
          key={key}
          type="button"
          className="rp-filter"
          aria-pressed={filter === key}
          onClick={() => setFilter(key)}
          data-testid={`filter-${key}`}
        >
          {label} <span className="rp-num">{n}</span>
        </button>
      ))}
    </div>
  );
}

// --- stale banner -----------------------------------------------------------------------

export function StaleBanner({ view, lang, pulse }: { view: ChangeSetView; lang: UiLanguage; pulse: number }) {
  if (!view.stale) return null;
  const base = revisionName(view.base.revision, lang);
  const current = revisionName(view.stale.current, lang);
  return (
    <div className="rp-stale" role="status" data-testid="stale-banner" data-pulse={pulse % 2 === 1 || undefined} key={pulse}>
      <p>{tp("wp4_stale_banner", lang, [base, current])}</p>
      <div className="rp-stale-actions">
        <button type="button" className="rp-btn" onClick={() => void proposeAgainOnHead()} data-testid="stale-repropose">
          {tp("wp4_stale_repropose", lang, [current])}
        </button>
        <button type="button" className="rp-btn" onClick={() => openReturn()} data-testid="stale-return">
          {tp("wp4_stale_return", lang)}
        </button>
      </div>
    </div>
  );
}

// --- return popover -------------------------------------------------------------------------

export function ReturnPopover({ lang, connected }: { lang: UiLanguage; connected: boolean }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const id = setTimeout(() => ref.current?.focus(), 0);
    return () => clearTimeout(id);
  }, []);
  const submit = async (again: boolean, e?: FormEvent) => {
    e?.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await returnProposal(reason, again);
    } finally {
      setBusy(false);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingEvent(e.nativeEvent)) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      e.preventDefault();
      closeReturn();
    } else if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.stopPropagation();
      e.preventDefault();
      void submit(false);
    }
  };
  return (
    <form className="rp-pop" role="dialog" aria-label={tp("wp4_return_title", lang)} data-testid="return-popover" onSubmit={(e) => void submit(false, e)}>
      <h3 className="rp-pop-title">{tp("wp4_return_title", lang)}</h3>
      <label className="rp-pop-label" htmlFor="rp-return-reason">
        {tp("wp4_return_reason", lang)}
      </label>
      <textarea
        id="rp-return-reason"
        ref={ref}
        className="rp-input"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={onKey}
        data-testid="return-reason"
      />
      <div className="rp-pop-actions">
        <button type="button" className="rp-btn rp-btn--quiet" onClick={() => closeReturn()}>
          {tp("wp4_return_cancel", lang)}
          <Keycap keys={["Esc"]} />
        </button>
        {connected ? (
          <button type="button" className="rp-btn" disabled={busy || !reason.trim()} onClick={() => void submit(true)} data-testid="return-rerequest">
            {tp("wp4_return_rerequest", lang)}
          </button>
        ) : null}
        <button type="submit" className="rp-btn" disabled={busy} data-testid="return-confirm">
          {tp("wp4_return_confirm", lang)}
          <Keycap keys={["Enter"]} />
        </button>
      </div>
    </form>
  );
}

// --- footer -----------------------------------------------------------------------------

function blockText(gate: GateState, lang: UiLanguage): string | null {
  const b = gate.block;
  if (!b) return null;
  switch (b.kind) {
    case "remaining":
      return tp("wp4_gate_remaining", lang, [b.count]);
    case "hard":
      return tp("wp4_gate_hard", lang, [b.count]);
    case "none_accepted":
      return tp("wp4_gate_none_accepted", lang);
    case "stale":
      return tp("wp4_gate_stale", lang);
    case "busy":
      return tp("wp4_gate_busy", lang);
    case "diff_mismatch":
      return tp("wp4_gate_diff_mismatch", lang);
    case "failed":
      return errorCodeMessage(b.code, lang);
    case "checking":
      return tp("wp4_gate_checking", lang);
    default:
      return null;
  }
}

export function proposerText(view: ChangeSetView, lang: UiLanguage): string {
  return proposerLine(tallyBySource(view.items), lang);
}

export function checkText(view: ChangeSetView, lang: UiLanguage, guardState: string): string {
  if (guardState === "running") return tp("wp4_box_check_running", lang);
  if (view.items.some((it) => it.guard.status === "not_checked") && guardState !== "ready") return tp("wp4_box_check_not_run", lang);
  const c = gateState(view).counts;
  return tp("wp4_box_check_body", lang, [c.facts + (view.untied?.length ?? 0), c.attn]);
}

function GateFooter({
  view,
  lang,
  pulse,
  busy,
  guardState,
  returnOpen,
  connected,
}: {
  view: ChangeSetView;
  lang: UiLanguage;
  pulse: number;
  busy: boolean;
  guardState: string;
  returnOpen: boolean;
  connected: boolean;
}) {
  const gate = gateState(view, { busy });
  const reason = blockText(gate, lang);
  return (
    <footer className="rp-footer" data-testid="gate-footer">
      {returnOpen ? <ReturnPopover lang={lang} connected={connected} /> : null}
      <ApprovalBox
        lang={lang}
        data-testid="gate-box"
        propose={<Parts text={proposerText(view, lang)} />}
        check={<Parts text={checkText(view, lang, guardState)} />}
        approve={null}
      />
      {reason ? (
        <p className="rp-footer-reason" data-testid="gate-reason" data-pulse={pulse > 0 ? pulse % 2 : undefined} key={pulse}>
          {reason}
          {gate.block?.kind === "hard" ? (
            <button type="button" className="rp-link" onClick={() => setTab("checks")}>
              {tp("wp4_gate_hard_view", lang)}
            </button>
          ) : null}
        </p>
      ) : null}
      <div className="rp-footer-row">
        <button type="button" className="rp-btn" onClick={() => openReturn()} data-testid="return" disabled={busy}>
          {tp("wp4_act_return", lang)}
          <Keycap keys={["R"]} />
        </button>
        <button
          type="button"
          className="rp-btn rp-btn--primary"
          data-variant="primary"
          data-testid="approve"
          disabled={!gate.canApprove}
          aria-disabled={!gate.canApprove}
          onClick={() => openApproval()}
        >
          {tp("wp4_act_approve", lang)}
          <Keycap keys={["Ctrl", "Shift", "Enter"]} />
        </button>
      </div>
    </footer>
  );
}

export function AppliedFooter({ applied, lang }: { applied: AppliedRecord; lang: UiLanguage }) {
  return (
    <footer className="rp-footer" data-testid="applied-footer">
      <ApprovalBox
        lang={lang}
        data-testid="gate-box-filled"
        hasChangedFact={applied.checked && applied.facts > 0}
        propose={<Parts text={proposerLine(applied.sources, lang)} />}
        check={<Parts text={applied.checked ? tp("wp4_box_check_body", lang, [applied.facts, applied.attn]) : tp("wp4_box_check_not_run", lang)} />}
        approve={
          <span data-testid="gate-approved">
            <Parts text={tp("wp4_box_approved_direct", lang, [clockTime(applied.atUtc, lang)])} />
          </span>
        }
      />
      <div className="rp-footer-row rp-footer-row--applied">
        <span className="rp-footer-status" data-testid="applied-status">
          {tp("wp4_applied_status", lang, [applied.revision])}
          <span className="rp-sep">·</span>
          <button type="button" className="rp-link" onClick={() => void exportApplied()} data-testid="applied-export">
            {tp("wp4_applied_export", lang)}
          </button>
          <Keycap keys={["Ctrl", "E"]} />
        </span>
      </div>
    </footer>
  );
}

// --- pane ------------------------------------------------------------------------------------

export function ChangesPane({
  view,
  lang,
  guardState,
  connected,
}: {
  view: ChangeSetView | null;
  lang: UiLanguage;
  guardState: string;
  connected: boolean;
}) {
  const doc = useWorkspace((s) => s.activeSessionId);
  const { selectedChangeId } = useCanvasSlice(doc);
  const st = panelSlice.use(doc, (s) => s);
  const busy = st.confirmPhase !== "idle" && st.confirmPhase !== "failed";

  if (!view) {
    return (
      <div className="rp-pane rp-pane--changes" data-testid="changes-pane">
        <div className="rp-scroll">
          {st.returned ? (
            <div className="rp-thread-row rp-thread-row--static" data-testid="returned-row">
              {tp("wp4_returned_row", lang, [st.returned.count])}
            </div>
          ) : null}
          <p className="rp-empty">{tp("wp4_changes_empty", lang)}</p>
        </div>
        {st.applied ? <AppliedFooter applied={st.applied} lang={lang} /> : null}
      </div>
    );
  }

  const visible = filterChanges(view.items, st.filter);
  const locked = !canDecide(view) || busy;
  const agentish = view.items.some((it) => it.source === "agent" || it.source === "test");

  return (
    <div className="rp-pane rp-pane--changes" data-testid="changes-pane" data-stale={view.stale ? "" : undefined}>
      <StaleBanner view={view} lang={lang} pulse={st.pulse} />
      <Filters view={view} filter={st.filter} lang={lang} />
      <div className="rp-scroll">
        {agentish ? (
          <button type="button" className="rp-thread-row" onClick={() => setTab("agent")} data-testid="thread-row">
            <span>{sourceLabel(view.provenance.mock ? "test" : "agent", lang)}</span>
            {view.createdUtc ? (
              <>
                <span className="rp-sep">·</span>
                <span>{clockTime(view.createdUtc, lang)}</span>
              </>
            ) : null}
            <span className="rp-sep">·</span>
            <span>{tp("wp4_thread_row", lang, [view.items.length])}</span>
          </button>
        ) : null}
        {visible.length === 0 ? (
          <p className="rp-empty">{tp("wp4_changes_filter_empty", lang)}</p>
        ) : (
          <ul className="rp-list" data-testid="change-list" tabIndex={0}>
            {visible.map((item) => (
              <ChangeItemRow key={item.id} item={item} selected={item.id === selectedChangeId} lang={lang} locked={locked} />
            ))}
          </ul>
        )}
      </div>
      <GateFooter
        view={view}
        lang={lang}
        pulse={st.pulse}
        busy={busy}
        guardState={guardState}
        returnOpen={st.returnOpen}
        connected={connected}
      />
    </div>
  );
}
