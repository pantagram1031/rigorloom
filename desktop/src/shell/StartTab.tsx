/**
 * 시작 (D1 flow a, J1 defects 33–37): mark and wordmark, the boundary
 * sentence, three actions with keycaps, recent documents, and the sample list.
 * No cards, no icons, no drop zone (drop works on the whole window).
 */
import { useMemo, useState } from "react";

import { useKeyHint } from "./keys";
import { Mark } from "../brand";
import { S } from "../i18n/v2/shell";
import { useWorkspace } from "../store";
import type { CorpusFileEntry, Recent } from "../types";
import { corpusFormDisplayInfo, filterCorpusEntries, findSessionByPath, isHwpBackendAvailable, normalizePathKey, pathParentFolder } from "../workspace/openHelpers";
import { engineState, formatShellDate, pendingCount } from "./docInfo";
import { OPENABLE_EXTENSIONS, openRecent, openSample, pickAndOpenFile, pickFolder } from "./open";
import { recentTid, TID } from "./testids";
import { shortPath } from "./Shell";

export function StartTab() {
  const lang = useWorkspace((s) => s.language);
  const recents = useWorkspace((s) => s.recents);
  const corpus = useWorkspace((s) => s.corpusFiles);
  const capabilities = useWorkspace((s) => s.capabilities);
  const engine = useWorkspace((s) => engineState(s));
  const missing = engine === "missing";
  const [query, setQuery] = useState("");
  const openFileKey = useKeyHint("shell.openFile")?.join("+");
  const openFolderKey = useKeyHint("shell.openFolder")?.join("+");
  const [help, setHelp] = useState(false);
  const samples = useMemo(() => filterCorpusEntries(corpus, isHwpBackendAvailable(capabilities)), [corpus, capabilities]);

  const needle = query.trim().toLocaleLowerCase();
  const filterLabel = S.t("shell_start_filter", lang);
  const filteredSamples = needle ? samples.filter((entry) => {
    const { title, sourceLabel, filename } = corpusFormDisplayInfo(entry, lang);
    return [title, sourceLabel, filename].some((part) => part.toLocaleLowerCase().includes(needle));
  }) : samples;
  const filteredRecents = needle
    ? recents.filter((entry) => entry.name.toLocaleLowerCase().includes(needle))
    : recents;

  return (
    <div className="sh-start" data-testid={TID.start}>
      <div className="sh-start-col">
        <div className="sh-start-head">
          <Mark size={24} className="sh-start-mark" />
          <h1 className="sh-start-word">{S.t("shell_app_name", lang)}</h1>
        </div>

        {missing ? (
          <div className="sh-start-attn" role="alert" data-testid={TID.startEngineMissing}>
            <span>{S.t("shell_start_engine_missing", lang)}</span>
            <button type="button" className="sh-link" aria-expanded={help} onClick={() => setHelp((v) => !v)}>
              {S.t("shell_start_engine_help", lang)}
            </button>
            {help ? <code className="sh-mono sh-start-cmd">rigorloom install</code> : null}
          </div>
        ) : null}

        <div className="sh-start-actions">
          <button type="button" className="sh-start-row" data-testid={TID.startOpenFile} title={openFileKey} disabled={missing} onClick={() => void pickAndOpenFile()}>
            <span className="sh-start-row-main">
              <span className="sh-start-row-label">{S.t("shell_start_open_file", lang)}</span>
              <span className="sh-start-exts sh-mono">{OPENABLE_EXTENSIONS.map((e) => `.${e}`).join(" ")}</span>
            </span>
          </button>
          <button type="button" className="sh-start-row" data-testid={TID.startOpenFolder} title={openFolderKey} disabled={missing} onClick={() => void pickFolder()}>
            <span className="sh-start-row-label">{S.t("shell_start_open_folder", lang)}</span>
          </button>
        </div>

        <input type="search" className="sh-start-filter" aria-label={filterLabel} placeholder={filterLabel}
          data-testid="start-filter" value={query} onChange={(event) => setQuery(event.target.value)} />
        {filteredRecents.length > 0 ? <RecentList recents={filteredRecents} disabled={missing} /> : null}
      </div>

      <section className="sh-start-col sh-start-col--side" data-testid={TID.startSamples} aria-labelledby="sh-samples-h">
        <h2 className="sh-start-h" id="sh-samples-h">{S.t("shell_start_samples", lang)}</h2>
        <ul className="sh-start-list" data-testid="start-sample-list">
          {filteredSamples.map((entry, i) => (
            <SampleRow key={entry.path} entry={entry} index={i} disabled={missing} />
          ))}
        </ul>
        {needle && filteredSamples.length === 0 && filteredRecents.length === 0 ? (
          <p className="sh-start-empty" role="status">{S.t("shell_start_no_matches", lang)}</p>
        ) : null}
      </section>
    </div>
  );
}

function SampleRow({ entry, index, disabled }: { entry: CorpusFileEntry; index: number; disabled: boolean }) {
  const lang = useWorkspace((s) => s.language);
  const info = corpusFormDisplayInfo(entry, lang);
  const ext = info.filename.split(".").pop()?.toUpperCase();
  return (
    <li>
      <button
        type="button"
        className="sh-start-item"
        disabled={disabled}
        data-testid={`start-sample-${index}`}
        data-file={info.filename}
        onClick={() => void openSample(entry)}
      >
        <span className="sh-start-ext sh-mono">{ext}</span>
        <span className="sh-start-item-title">{info.title}</span>
        <span className="sh-start-item-meta">{info.sourceLabel}</span>
      </button>
    </li>
  );
}

function RecentList({ recents, disabled }: { recents: Recent[]; disabled: boolean }) {
  const lang = useWorkspace((s) => s.language);
  return (
    <section className="sh-start-recent" aria-labelledby="sh-recent-h" data-testid={TID.startRecent}>
      <h2 className="sh-start-h" id="sh-recent-h">{S.t("shell_start_recent", lang)}</h2>
      <ul className="sh-start-list">
        {recents.slice(0, 8).map((r, i) => (
          <RecentRow key={r.path} recent={r} index={i} disabled={disabled} />
        ))}
      </ul>
    </section>
  );
}

function RecentRow({ recent, index, disabled }: { recent: Recent; index: number; disabled: boolean }) {
  const lang = useWorkspace((s) => s.language);
  const state = useWorkspace((s) => {
    const live = findSessionByPath(s.sessions, s.openedPaths, recent.path);
    if (!live) return S.t("shell_recent_original", s.language);
    const pending = pendingCount(s, live.sessionId);
    if (pending > 0) return S.t("shell_recent_pending", s.language, [pending]);
    const revisions = (s.candidates[live.sessionId] ?? []).filter((c) => Boolean(c.runId)).length;
    return revisions > 0 ? S.t("shell_recent_revision", s.language, [revisions]) : S.t("shell_recent_original", s.language);
  });
  // A sample form shows its catalogue title and 예시 양식, never its file name.
  const sample = useWorkspace((s) => {
    const key = normalizePathKey(recent.path);
    return s.corpusFiles.find((e) => e.path && (normalizePathKey(e.path) === key || key.endsWith(`/${normalizePathKey(e.path)}`))) ?? null;
  });
  const dot = recent.name.lastIndexOf(".");
  const stem = sample ? corpusFormDisplayInfo(sample, lang).title : dot > 0 ? recent.name.slice(0, dot) : recent.name;
  const ext = dot > 0 ? recent.name.slice(dot + 1) : "";
  const folder = sample ? S.t("shell_recent_sample", lang) : shortPath(pathParentFolder(recent.path));
  return (
    <li>
      <button type="button" className="sh-start-item sh-start-item--recent" data-testid={recentTid(index)} disabled={disabled} onClick={() => void openRecent(recent)}>
        <span className="sh-start-ext sh-mono">{ext}</span>
        <span className="sh-start-item-body">
          <span className="sh-start-item-title">{stem}</span>
          <span className="sh-start-item-meta">{folder}</span>
        </span>
        <span className="sh-start-item-end">
          <span className="sh-start-item-state">{state}</span>
          <span className="sh-start-item-meta">{formatShellDate(recent.openedUtc, lang)}</span>
        </span>
      </button>
    </li>
  );
}
