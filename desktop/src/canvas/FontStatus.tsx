import { useEffect, useId, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { wp3t } from "../i18n/v2/wp3";
import type { RasterSource } from "../model/enginePage";
import { FONT_SOURCE_LINK, substitutedFontRows, type FontCheckRow } from "../model/fontInstall";
import { collectPageFonts, resolveFontSubstitution } from "../model/page";
import { browserToken, isTauri } from "../runtime";
import { activeInspect, useWorkspace } from "../store";
import type { UiLanguage } from "../types";
import { setCanvasSlice } from "./controller";
import { requestPageFonts } from "./usePageRaster";

export function FontStatus({ sessionId, rev, language, source, narrow = false }: {
  sessionId: string; rev: string; language: UiLanguage; source: RasterSource | "projection"; narrow?: boolean;
}) {
  const inspect = useWorkspace(activeInspect);
  const render = useWorkspace((s) => s.render);
  const projection = useMemo(() => collectPageFonts(inspect, render, language), [inspect, render, language]);
  const candidates = useMemo(() => projection.entries.filter((row) => row.substituted), [projection]);
  const faces = useMemo(() => source === "projection" ?
    Array.from(new Set(candidates.map((row) => row.declared))).filter((name) => name.length <= 128).slice(0, 32) : [],
  [source, candidates]);

  const [report, setReport] = useState<{ source: typeof source; faces: FontCheckRow[] } | null>(null);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkFailed, setCheckFailed] = useState(false);
  const [openFailed, setOpenFailed] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const tauri = isTauri();

  useEffect(() => {
    if (!tauri && !browserToken()) return;
    const request = new AbortController();
    void requestPageFonts({ sessionId, rev, source, faces, refresh: false }, request.signal).then((reply) => {
      if (!request.signal.aborted && reply.rev === rev) setReport({ source, faces: reply.faces });
    }).catch(() => {});
    return () => {
      request.abort();
      pending.current?.abort();
    };
  }, [sessionId, rev, source, faces, tauri]);

  const checked = report?.source === source ? report.faces : null;
  const rows = substitutedFontRows(checked ?? [], (name) => source === "projection" ?
    candidates.find((row) => row.declared === name)?.resolved ?? resolveFontSubstitution(name, language).resolved : null);
  const missing = rows.some((row) => row.state === "missing");
  const unknown = rows.some((row) => row.state === "unknown");
  const other = checked ? checked.filter((row) => row.state === "other").map((row) => ({
    declared: row.declared,
    resolved: row.drawnWith ?? (source === "projection" ? resolveFontSubstitution(row.declared, language).resolved : null),
  })) : candidates;

  async function recheck() {
    const request = new AbortController();
    pending.current = request;
    setChecking(true);
    setCheckFailed(false);
    setOpenFailed(false);
    try {
      const reply = await requestPageFonts({ sessionId, rev, source, faces, refresh: true }, request.signal);
      if (request.signal.aborted || reply.rev !== rev) return;
      setReport({ source, faces: reply.faces });
      setCanvasSlice((slice) => ({ ...slice, fontRefresh: slice.fontRefresh + 1 }), sessionId);
    } catch {
      if (!request.signal.aborted) setCheckFailed(true);
    } finally {
      if (pending.current === request) {
        pending.current = null;
        setChecking(false);
      }
    }
  }

  return (
    <>
      {rows.length || open ? (
        <button ref={trigger} type="button"
          className={`rl-font-trigger rl-status-item${narrow ? " rl-font-trigger--narrow" : ""}`}
          data-testid="status-font-sub" aria-haspopup="dialog" aria-expanded={open} aria-controls={id}
          onClick={() => {
            dialog.current?.showModal();
            setOpen(true);
            setOpenFailed(false);
          }}>
          {rows.length ? wp3t("status_font_sub", language, [rows.length]) : wp3t("font_install_title", language)}
        </button>
      ) : other.length > 0 ? (
        <span className={`rl-status-item rl-status-item--attn${narrow ? " rl-font-trigger--narrow" : ""}`} data-testid="status-font-sub"
          title={other.map((row) => row.resolved ?
            wp3t("status_font_sub_detail", language, [row.declared, row.resolved]) : row.declared).join(", ")}>
          {wp3t("status_font_sub", language, [other.length])}
        </span>
      ) : null}
      <dialog ref={dialog} id={id} className="rl-font-panel" data-testid="font-install-panel"
        aria-labelledby={`${id}-title`} onClose={() => {
          setOpen(false);
          trigger.current?.focus();
        }}>
        <header className="rl-font-panel-header">
          <h2 id={`${id}-title`}>{wp3t("font_install_title", language)}</h2>
          <button type="button" className="rl-font-dismiss" aria-label={wp3t("font_install_close", language)}
            onClick={() => dialog.current?.close()}>×</button>
        </header>
        {rows.length ? (
          <>
            <p>{wp3t(missing ? "font_install_body" : "font_install_substituted", language)}</p>
            <dl className="rl-font-faces">
              {rows.map((row) => (
                <div key={row.declared}>
                  <dt>{row.declared}</dt>
                  <dd>{row.drawnWith ? wp3t("font_install_drawn_with", language, [row.drawnWith]) :
                    wp3t("font_install_drawn_unknown", language)}</dd>
                </div>
              ))}
            </dl>
          </>
        ) : null}
        <div role="status" className="rl-font-feedback">
          {checkFailed ? wp3t("font_install_unknown", language) :
            openFailed ? wp3t("font_install_open_failed", language) :
            checking || (open && checked === null) ? wp3t("font_install_checking", language) :
            unknown ? wp3t("font_install_unknown", language) :
            open && !rows.length ? wp3t("font_install_checked", language) : null}
        </div>
        <div className="rl-font-actions">
          {missing ? (tauri ? (
            <button type="button" className="rl-font-action rl-font-source"
              onClick={() => void invoke("open_hancom_font_source").catch(() => setOpenFailed(true))}>
              {wp3t("font_install_source", language)}
            </button>
          ) : (
            <a className="rl-font-action rl-font-source" {...FONT_SOURCE_LINK}>{wp3t("font_install_source", language)}</a>
          )) : null}
          <button type="button" className="rl-font-action" disabled={checking} onClick={() => void recheck()}>
            {wp3t("font_install_recheck", language)}
          </button>
        </div>
      </dialog>
    </>
  );
}
