import { type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  loadCorpusFiles,
  openPath,
  openUploadedFile,
  openViaDialog,
  refreshSessions,
  selectSession,
} from "../actions";
import { DetailDisclosure } from "../components/DetailDisclosure";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import * as rt from "../runtime";
import { getState, setState, useWorkspace } from "../store";
import type { CorpusFileEntry, RuntimeError } from "../types";
import {
  buildOpenRecentItems,
  computeFileSha256,
  corpusFormDisplayInfo,
  filterCorpusEntries,
  findSessionByFile,
  findSessionByPath,
  isHwpBackendAvailable,
  isHwpFilename,
  isHwpGuidanceErrorCode,
  isMissingSourceErrorCode,
  isSupportedDocumentFilename,
  pathBasename,
  resolveOpenErrorMessage,
  type OpenRecentItem,
} from "../workspace/openHelpers";
import "./open.css";

interface DropzoneNotice {
  kind: "hwp_help" | "error";
  message: string;
  filename?: string;
  error?: RuntimeError | null;
}

interface RowOpenError {
  itemKey: string;
  message: string;
  detail: string;
}

export function OpenView() {
  const language = useWorkspace((s) => s.language);
  const sessions = useWorkspace((s) => s.sessions);
  const recents = useWorkspace((s) => s.recents);
  const openedPaths = useWorkspace((s) => s.openedPaths);
  const draft = useWorkspace((s) => s.draft);
  const candidates = useWorkspace((s) => s.candidates);
  const applyOutcomes = useWorkspace((s) => s.applyOutcomes);
  const capabilities = useWorkspace((s) => s.capabilities);
  const corpusFiles = useWorkspace((s) => s.corpusFiles);
  const corpusFilesPhase = useWorkspace((s) => s.corpusFilesPhase);
  const openSamplesRevealNonce = useWorkspace((s) => s.openSamplesRevealNonce);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const samplesSectionRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);

  const [localDragOver, setLocalDragOver] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState<string | null>(null);
  const [notice, setNotice] = useState<DropzoneNotice | null>(null);
  const [rowError, setRowError] = useState<RowOpenError | null>(null);
  const [sampleError, setSampleError] = useState<{ message: string; error: RuntimeError | null } | null>(
    null,
  );
  const [samplesOpenOverride, setSamplesOpenOverride] = useState<boolean | null>(null);

  useEffect(() => {
    void loadCorpusFiles();
    void refreshSessions();
  }, []);

  useEffect(() => {
    if (openSamplesRevealNonce === 0) return;
    setSamplesOpenOverride(true);
    const frameId = window.requestAnimationFrame(() => {
      samplesSectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [openSamplesRevealNonce]);

  const hwpAvailable = useMemo(
    () => isHwpBackendAvailable(capabilities),
    [capabilities],
  );

  const items = useMemo(
    () =>
      buildOpenRecentItems({
        sessions,
        recents,
        openedPaths,
        draft,
        candidates,
        applyOutcomes,
        language,
      }),
    [sessions, recents, openedPaths, draft, candidates, applyOutcomes, language],
  );

  const visibleSamples = useMemo(
    () => filterCorpusEntries(corpusFiles, hwpAvailable),
    [corpusFiles, hwpAvailable],
  );

  const samplesOpen = samplesOpenOverride ?? items.length === 0;

  function triggerFilePicker() {
    setNotice(null);
    if (rt.isTauri()) {
      void handleTauriOpenDialog();
      return;
    }
    const input = fileInputRef.current;
    if (!input) return;
    input.value = "";
    input.click();
  }

  async function handleTauriOpenDialog() {
    if (busyRef.current) return;
    busyRef.current = true;
    setNotice(null);
    setRowError(null);
    setSampleError(null);
    setState({ inspectError: null });
    try {
      const sid = await openViaDialog();
      if (sid === null) {
        const err = getState().inspectError;
        if (err) {
          applyDropzoneRuntimeError(err);
        }
      }
    } finally {
      busyRef.current = false;
    }
  }

  function applyDropzoneRuntimeError(err: RuntimeError, filename?: string) {
    if (isHwpGuidanceErrorCode(err.code)) {
      setNotice({
        kind: "hwp_help",
        message: t("open_hwp_help_body", language),
        filename,
        error: err,
      });
      return;
    }
    setNotice({
      kind: "error",
      message: resolveOpenErrorMessage(err, language),
      filename,
      error: err,
    });
  }

  async function handleSelectedFile(file: File) {
    if (busyRef.current) return;
    setNotice(null);
    setRowError(null);
    setSampleError(null);

    if (!isSupportedDocumentFilename(file.name)) {
      setNotice({
        kind: "error",
        message: t("open_drop_unsupported", language),
        filename: file.name,
        error: null,
      });
      return;
    }

    if (isHwpFilename(file.name) && !hwpAvailable) {
      setNotice({
        kind: "hwp_help",
        message: t("open_hwp_help_body", language),
        filename: file.name,
        error: null,
      });
      return;
    }

    busyRef.current = true;
    setLoadingLabel(file.name);
    setState({ inspectError: null });
    try {
      const sha256 = await computeFileSha256(file);
      const current = getState();
      const existing = findSessionByFile(
        current.sessions,
        current.openedPaths,
        file.name,
        file.size,
        sha256,
      );
      if (existing) {
        await selectSession(existing.sessionId);
        return;
      }

      const sid = await openUploadedFile(file);
      if (sid === null) {
        const err = getState().inspectError;
        if (err) {
          applyDropzoneRuntimeError(err, file.name);
        } else {
          setNotice({
            kind: "error",
            message: t("open_drop_unsupported", language),
            filename: file.name,
            error: null,
          });
        }
      }
    } finally {
      setLoadingLabel(null);
      busyRef.current = false;
    }
  }

  function onFileInputChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      void handleSelectedFile(file);
    }
    e.target.value = "";
  }

  function onDropzoneDragOver(e: DragEvent<HTMLElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
    if (!localDragOver) {
      setLocalDragOver(true);
    }
  }

  function onDropzoneDragLeave(e: DragEvent<HTMLElement>) {
    e.preventDefault();
    e.stopPropagation();
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) {
      setLocalDragOver(false);
    }
  }

  function onDropzoneDrop(e: DragEvent<HTMLElement>) {
    e.preventDefault();
    e.stopPropagation();
    setLocalDragOver(false);
    setState({ dragOver: false });
    const file = e.dataTransfer?.files?.[0];
    if (file) {
      void handleSelectedFile(file);
    }
  }

  async function handleOpenRecent(item: OpenRecentItem) {
    if (busyRef.current) return;
    setNotice(null);
    setRowError(null);
    setSampleError(null);

    if (item.liveSessionId) {
      busyRef.current = true;
      try {
        await selectSession(item.liveSessionId);
      } finally {
        busyRef.current = false;
      }
      return;
    }

    const current = getState();
    const existing = findSessionByPath(
      current.sessions,
      current.openedPaths,
      item.fullPath,
    );
    if (existing) {
      busyRef.current = true;
      try {
        await selectSession(existing.sessionId);
      } finally {
        busyRef.current = false;
      }
      return;
    }

    if (isHwpFilename(item.fullPath || item.rawName) && !hwpAvailable) {
      setNotice({
        kind: "hwp_help",
        message: t("open_hwp_help_body", language),
        filename: item.rawName,
        error: null,
      });
      return;
    }

    busyRef.current = true;
    setLoadingLabel(item.rawName);
    setState({ inspectError: null });
    try {
      const sid = await openPath(item.fullPath);
      if (sid === null) {
        const err = getState().inspectError;
        if (err && isHwpGuidanceErrorCode(err.code)) {
          applyDropzoneRuntimeError(err, item.rawName);
          return;
        }
        const message = isMissingSourceErrorCode(err?.code)
          ? errorCodeMessage("artifact_missing", language)
          : resolveOpenErrorMessage(err, language);
        setRowError({
          itemKey: item.key,
          message,
          detail: err?.detail || err?.message || item.fullPath,
        });
      }
    } finally {
      setLoadingLabel(null);
      busyRef.current = false;
    }
  }

  async function handleOpenSample(entry: CorpusFileEntry) {
    if (busyRef.current) return;
    setNotice(null);
    setRowError(null);
    setSampleError(null);

    const filename = pathBasename(entry.path || entry.name);
    if (isHwpFilename(filename) && !hwpAvailable) {
      setNotice({
        kind: "hwp_help",
        message: t("open_hwp_help_body", language),
        filename,
        error: null,
      });
      return;
    }

    const current = getState();
    const existing = findSessionByPath(
      current.sessions,
      current.openedPaths,
      entry.path,
    );
    if (existing) {
      busyRef.current = true;
      try {
        await selectSession(existing.sessionId);
      } finally {
        busyRef.current = false;
      }
      return;
    }

    busyRef.current = true;
    setLoadingLabel(corpusFormDisplayInfo(entry, language).title);
    setState({ inspectError: null });
    try {
      const sid = await openPath(entry.path);
      if (sid === null) {
        const err = getState().inspectError;
        if (err && isHwpGuidanceErrorCode(err.code)) {
          applyDropzoneRuntimeError(err, filename);
          return;
        }
        setSampleError({
          message: resolveOpenErrorMessage(err, language),
          error: err,
        });
      }
    } finally {
      setLoadingLabel(null);
      busyRef.current = false;
    }
  }

  function handleBuiltinFormsAction() {
    const nextOpen = samplesOpenOverride === null ? true : !samplesOpen;
    const targetOpen = !samplesOpen ? true : nextOpen;
    setSamplesOpenOverride(targetOpen);
    if (targetOpen) {
      requestAnimationFrame(() => {
        samplesSectionRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      });
    }
  }

  const busy = loadingLabel !== null;

  return (
    <main className="open-view" data-testid="open-view">
      <div className="open-container">
        <header className="open-header">
          <h1>{t("open_title", language)}</h1>
          <p className="open-subtitle">{t("open_subtitle", language)}</p>
        </header>

        <section
          className={`open-dropzone${localDragOver ? " is-drag-over" : ""}`}
          data-testid="open-dropzone"
          aria-label={t("open_title", language)}
          onDragOver={onDropzoneDragOver}
          onDragLeave={onDropzoneDragLeave}
          onDrop={onDropzoneDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".hwpx,.hwp"
            className="open-file-input"
            data-testid="open-file-input"
            aria-hidden="true"
            tabIndex={-1}
            onChange={onFileInputChange}
          />

          <p className="open-dropzone-title">{t("open_drop_prompt", language)}</p>
          <p className="open-dropzone-sub">{t("open_drop_sub", language)}</p>

          <div className="open-dropzone-actions">
            <button
              type="button"
              className="open-btn-primary"
              data-testid="open-choose-file"
              disabled={busy}
              aria-busy={busy}
              onClick={triggerFilePicker}
            >
              {t("open_choose_file", language)}
            </button>
            <button
              type="button"
              className="open-btn-secondary"
              data-testid="welcome-open-form"
              aria-expanded={samplesOpen}
              aria-controls="open-samples-section"
              onClick={handleBuiltinFormsAction}
            >
              {t("open_builtin_forms", language)}
            </button>
          </div>

          {loadingLabel !== null && (
            <div
              className="open-dropzone-status"
              role="status"
              aria-live="polite"
              data-testid="open-upload-progress"
            >
              <span className="open-status-primary">{t("browser_open_loading", language)}</span>
              <span className="open-status-file">{loadingLabel}</span>
            </div>
          )}

          {notice?.kind === "hwp_help" && (
            <div
              className="open-notice open-notice--hwp"
              role="status"
              aria-live="polite"
              data-testid="open-hwp-help"
            >
              <p className="open-notice-title">{t("open_hwp_help_title", language)}</p>
              <p className="open-notice-body">{t("open_hwp_help_body", language)}</p>
              <p className="open-notice-steps">{t("open_hwp_help_steps", language)}</p>
              {notice.error && (
                <div className="open-notice-details">
                  <DetailDisclosure label={t("detail_label", language)}>
                    <p className="open-tech-line">
                      {notice.error.code}
                      {notice.error.detail || notice.error.message
                        ? `: ${notice.error.detail || notice.error.message}`
                        : ""}
                    </p>
                  </DetailDisclosure>
                </div>
              )}
            </div>
          )}

          {notice?.kind === "error" && (
            <div
              className="open-notice open-notice--error"
              role="alert"
              data-testid="open-upload-error"
            >
              <p className="open-notice-body">{notice.message}</p>
              {notice.error && (notice.error.detail || notice.error.message) && (
                <div className="open-notice-details">
                  <DetailDisclosure label={t("detail_label", language)}>
                    <p className="open-tech-line">
                      {notice.error.code}: {notice.error.detail || notice.error.message}
                    </p>
                  </DetailDisclosure>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="open-recents" aria-label={t("open_recent_title", language)}>
          <div className="open-recents-head">
            <h2>{t("open_recent_title", language)}</h2>
            <p className="open-recents-hint">{t("open_recent_hint", language)}</p>
          </div>

          {items.length === 0 ? (
            <div className="open-empty" data-testid="open-empty-recent">
              {t("open_empty_recent", language)}
            </div>
          ) : (
            <div className="open-recent-list" data-testid="open-recent-list" role="list">
              {items.map((item) => {
                const thisRowError =
                  rowError && rowError.itemKey === item.key ? rowError : null;
                return (
                  <div key={item.key} className="open-recent-item" role="listitem">
                    <button
                      type="button"
                      className="open-recent-row"
                      data-testid={`open-recent-item-${item.rawName}`}
                      title={item.fullPath || item.rawName}
                      disabled={busy}
                      onClick={() => void handleOpenRecent(item)}
                    >
                      <span className="open-recent-name">
                        <span className="open-recent-basename">{item.rawName}</span>
                        {item.parentFolder && (
                          <span className="open-recent-parent">
                            {" "}
                            ({item.parentFolder})
                          </span>
                        )}
                      </span>
                      <span className="open-recent-meta">
                        {item.formattedTime && (
                          <span className="open-recent-time">{item.formattedTime}</span>
                        )}
                        {item.badge && (
                          <span
                            className={`open-badge open-badge--${item.badge.kind}`}
                            data-testid={`open-recent-badge-${item.badge.kind}`}
                          >
                            {item.badge.label}
                          </span>
                        )}
                      </span>
                    </button>

                    {thisRowError && (
                      <div
                        className="open-row-error"
                        role="alert"
                        data-testid={`open-recent-error-${item.rawName}`}
                      >
                        <span className="open-row-error-text">{thisRowError.message}</span>
                        <button
                          type="button"
                          className="open-row-retry-btn"
                          data-testid={`open-recent-retry-${item.rawName}`}
                          onClick={triggerFilePicker}
                        >
                          {t("open_choose_file", language)}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section
          ref={samplesSectionRef}
          id="open-samples-section"
          className="open-samples"
          data-testid="open-samples-section"
          aria-label={t("open_sample_form_label", language)}
        >
          <div className="open-samples-head">
            <h2>{t("open_sample_form_label", language)}</h2>
            <button
              type="button"
              className="open-samples-toggle"
              data-testid="open-samples-toggle"
              aria-expanded={samplesOpen}
              aria-controls="open-samples-body"
              onClick={() => setSamplesOpenOverride(!samplesOpen)}
            >
              {t(samplesOpen ? "open_samples_hide" : "open_samples_show", language)}
            </button>
          </div>

          {samplesOpen && (
            <div id="open-samples-body" className="open-samples-body">
              {sampleError && (
                <div
                  className="open-notice open-notice--error open-samples-error"
                  role="alert"
                  data-testid="open-sample-error"
                >
                  <p className="open-notice-body">{sampleError.message}</p>
                  {sampleError.error && (sampleError.error.detail || sampleError.error.message) && (
                    <div className="open-notice-details">
                      <DetailDisclosure label={t("detail_label", language)}>
                        <p className="open-tech-line">
                          {sampleError.error.code}:{" "}
                          {sampleError.error.detail || sampleError.error.message}
                        </p>
                      </DetailDisclosure>
                    </div>
                  )}
                </div>
              )}

              {visibleSamples.length === 0 ? (
                <div className="open-empty" data-testid="open-empty-corpus">
                  {corpusFilesPhase === "starting"
                    ? t("browser_open_loading", language)
                    : t("browser_open_empty_corpus", language)}
                </div>
              ) : (
                <div className="open-sample-list" data-testid="open-sample-list" role="list">
                  {visibleSamples.map((entry) => {
                    const info = corpusFormDisplayInfo(entry, language);
                    return (
                      <button
                        key={entry.path}
                        type="button"
                        role="listitem"
                        className="open-sample-row"
                        data-testid={`open-sample-item-${info.filename}`}
                        title={info.filename}
                        disabled={busy}
                        onClick={() => void handleOpenSample(entry)}
                      >
                        <span className="open-sample-title">{info.title}</span>
                        <span className="open-sample-meta">
                          <span className="open-sample-source">{info.sourceLabel}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
