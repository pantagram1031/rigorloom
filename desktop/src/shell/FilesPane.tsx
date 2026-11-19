/**
 * 파일 pane: 열린 문서, the 문서 폴더 tree (when the workspace listing is
 * served), and 예시 양식. A single click opens an italic preview tab that the
 * next click reuses; double-click or Enter pins it (J1 §3 IA).
 */
import { useEffect, useMemo, useState } from "react";

import { S } from "../i18n/v2/shell";
import { useWorkspace } from "../store";
import type { SlotProps } from "./slots";
import { corpusFormDisplayInfo, filterCorpusEntries, isHwpBackendAvailable } from "../workspace/openHelpers";
import { docTitle } from "./docInfo";
import { isOpenable, openSample } from "./open";
import { FileName } from "./parts";
import { listWorkspace, type WorkspaceListing } from "./rpc";
import { getShell, useShell } from "./shellState";
import { activateTab, openDocumentPath, pinTab } from "./tabs";
import { TID } from "./testids";

export function FilesPane(_props: SlotProps) {
  const lang = useWorkspace((s) => s.language);
  const tabs = useShell((s) => s.tabs);
  const active = useShell((s) => s.activeTab);
  const corpus = useWorkspace((s) => s.corpusFiles);
  const capabilities = useWorkspace((s) => s.capabilities);
  const workspace = useWorkspace((s) => s);
  const samples = useMemo(() => filterCorpusEntries(corpus, isHwpBackendAvailable(capabilities)), [corpus, capabilities]);
  const [listing, setListing] = useState<WorkspaceListing | null>(null);

  useEffect(() => {
    let live = true;
    void listWorkspace().then((l) => {
      if (live) setListing(l);
    });
    return () => {
      live = false;
    };
  }, []);

  const docs = tabs.filter((t) => t.kind === "doc");

  return (
    <div className="sh-files" data-testid={TID.filesPane}>
      <h3 className="sh-tree-head">{S.t("shell_files_open_docs", lang)}</h3>
      <ul className="sh-tree" role="tree">
        {docs.map((t) =>
          t.kind === "doc" ? (
            <li key={t.id} role="treeitem" aria-selected={t.id === active}>
              <button type="button" className="sh-tree-row" data-selected={t.id === active || undefined} onClick={() => activateTab(t.id)}>
                <FileName name={docTitle(workspace, t.sessionId)} />
              </button>
            </li>
          ) : null,
        )}
      </ul>

      {listing ? (
        <>
          <h3 className="sh-tree-head" title={listing.root}>{S.t("shell_files_doc_folder", lang)}</h3>
          {listing.entries.length === 0 ? (
            <p className="sh-tree-empty">{S.t("shell_files_empty", lang)}</p>
          ) : (
            <ul className="sh-tree" role="tree">
              {listing.entries
                .filter((e) => e.kind === "dir" || isOpenable(e.name))
                .map((e) => (
                  <li key={e.path} role="treeitem">
                    <button
                      type="button"
                      className="sh-tree-row"
                      data-kind={e.kind}
                      disabled={e.kind === "dir"}
                      onClick={() => void openDocumentPath(`${listing.root}/${e.path}`, { name: e.name, preview: true })}
                      onDoubleClick={() => pinTab(getShell().activeTab)}
                    >
                      <FileName name={e.name} />
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </>
      ) : null}

      <h3 className="sh-tree-head">{S.t("shell_files_samples", lang)}</h3>
      <ul className="sh-tree" role="tree">
        {samples.map((entry) => {
          const info = corpusFormDisplayInfo(entry, lang);
          return (
            <li key={entry.path} role="treeitem">
              <button type="button" className="sh-tree-row" onClick={() => void openSample(entry)} title={info.filename}>
                <span className="sh-fname">{info.title}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
