import { useEffect, useMemo, useState } from "react";
import {
  closeCommandPalette,
  exportApplied,
  loadCorpusFiles,
  navigateScreen,
  openApprovalDialog,
  openOperatorModal,
  openViaDialog,
  revisionNumberFor,
  setReturnPopoverOpen,
  toggleLanguage,
  togglePrintView,
  toggleTheme,
} from "../actions";
import { t, type VocabularyKey } from "../i18n/vocabulary";
import {
  activeSession,
  getState,
  headCandidate,
  setState,
  showToast,
  useWorkspace,
} from "../store";

interface PaletteItem {
  id: string;
  labelKey: VocabularyKey;
  labelText?: string;
  shortcut?: string;
  keywordsKey: VocabularyKey;
  run: () => void;
}

export function CommandPalette() {
  const open = useWorkspace((s) => s.commandPaletteOpen);
  const language = useWorkspace((s) => s.language);
  const theme = useWorkspace((s) => s.theme);
  const session = useWorkspace(activeSession);
  const draft = useWorkspace((s) => s.draft);
  const applied = useWorkspace((s) => s.applied);
  const head = useWorkspace(headCandidate);
  const exportRunId = applied?.runId ?? head?.runId ?? null;
  const exportRevNum = useWorkspace((s) =>
    revisionNumberFor(s, session?.sessionId, exportRunId),
  );

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const hasPlan = Boolean(session && draft.plan && draft.sessionId === session.sessionId);
  const canApprove = Boolean(hasPlan && draft.validation?.verdict === "pass");
  const canExport = Boolean(session && (applied?.runId ?? head?.runId));

  const commands = useMemo<PaletteItem[]>(() => {
    const items: PaletteItem[] = [
      {
        id: "open-doc",
        labelKey: "cmd_open_doc",
        shortcut: "Ctrl+O",
        keywordsKey: "cmd_kw_open_doc",
        run: () => {
          navigateScreen("open");
          void openViaDialog();
        },
      },
      {
        id: "open-builtin",
        labelKey: "cmd_open_builtin",
        keywordsKey: "cmd_kw_open_builtin",
        run: () => {
          navigateScreen("open");
          setState({
            openSamplesRevealNonce: getState().openSamplesRevealNonce + 1,
          });
          void loadCorpusFiles();
        },
      },
    ];

    if (session) {
      items.push({
        id: "go-review",
        labelKey: "cmd_go_review",
        shortcut: "Ctrl+1",
        keywordsKey: "cmd_kw_go_review",
        run: () => navigateScreen("review"),
      });
      items.push({
        id: "go-fill",
        labelKey: "cmd_go_fill",
        shortcut: "Ctrl+2",
        keywordsKey: "cmd_kw_go_fill",
        run: () => navigateScreen("fill"),
      });
      items.push({
        id: "go-history",
        labelKey: "cmd_go_history",
        shortcut: "Ctrl+3",
        keywordsKey: "cmd_kw_go_history",
        run: () => navigateScreen("history"),
      });
      items.push({
        id: "toggle-print-view",
        labelKey: "cmd_toggle_print_view",
        keywordsKey: "cmd_kw_toggle_print_view",
        run: () => togglePrintView(),
      });
    }

    if (canApprove) {
      items.push({
        id: "approve",
        labelKey: "cmd_approve",
        shortcut: "A",
        keywordsKey: "cmd_kw_approve",
        run: () => openApprovalDialog(),
      });
    }

    if (hasPlan) {
      items.push({
        id: "return",
        labelKey: "cmd_return",
        shortcut: "R",
        keywordsKey: "cmd_kw_return",
        run: () => {
          navigateScreen("review");
          setReturnPopoverOpen(true);
        },
      });
    }

    if (session) {
      items.push({
        id: "export",
        labelKey: "cmd_export",
        labelText:
          exportRevNum !== null
            ? t("action_export_revision", language, [exportRevNum])
            : undefined,
        shortcut: "Ctrl+E",
        keywordsKey: "cmd_kw_export",
        run: () => {
          if (!canExport) {
            showToast(t("export_no_revision_toast", language), 2600);
            return;
          }
          void exportApplied();
        },
      });
    }

    items.push(
      {
        id: "switch-language",
        labelKey: "cmd_switch_language",
        keywordsKey: "cmd_kw_switch_language",
        run: () => void toggleLanguage(),
      },
      {
        id: "change-theme",
        labelKey: "cmd_change_theme",
        keywordsKey: "cmd_kw_change_theme",
        run: () => {
          const order = ["auto", "light", "dark"] as const;
          const next = order[(order.indexOf(theme) + 1) % order.length];
          void toggleTheme(next);
        },
      },
      {
        id: "open-settings",
        labelKey: "cmd_open_settings",
        shortcut: "Ctrl+,",
        keywordsKey: "cmd_kw_open_settings",
        run: () => navigateScreen("settings"),
      },
      {
        id: "open-by-path",
        labelKey: "cmd_open_by_path_details",
        keywordsKey: "cmd_kw_open_by_path",
        run: () => {
          setState({ openDialogOpen: true });
          void loadCorpusFiles();
        },
      },
      {
        id: "operator-agent",
        labelKey: "cmd_operator_agent_details",
        keywordsKey: "cmd_kw_operator_agent",
        run: () => openOperatorModal(),
      },
    );

    return items;
  }, [session, hasPlan, canApprove, canExport, exportRevNum, theme, language]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((item) => {
      const label = (item.labelText ?? t(item.labelKey, language)).toLowerCase();
      const kwKo = t(item.keywordsKey, "ko").toLowerCase();
      const kwEn = t(item.keywordsKey, "en").toLowerCase();
      return label.includes(q) || kwKo.includes(q) || kwEn.includes(q);
    });
  }, [commands, query, language]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex((prev) =>
      filtered.length === 0 ? 0 : Math.min(prev, filtered.length - 1),
    );
  }, [filtered.length]);

  if (!open) return null;

  function runItem(item: PaletteItem | undefined) {
    if (!item) return;
    closeCommandPalette();
    item.run();
  }

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeCommandPalette();
      }}
    >
      <div
        className="palette-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t("action_command_palette", language)}
        data-testid="command-palette"
      >
        <div className="palette-search">
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (filtered.length > 0) {
                  setSelectedIndex((prev) => (prev + 1) % filtered.length);
                }
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                if (filtered.length > 0) {
                  setSelectedIndex((prev) => (prev - 1 + filtered.length) % filtered.length);
                }
              } else if (e.key === "Enter") {
                e.preventDefault();
                runItem(filtered[selectedIndex]);
              } else if (e.key === "Escape") {
                e.preventDefault();
                closeCommandPalette();
              }
            }}
            placeholder={t("palette_placeholder", language)}
            data-testid="command-palette-input"
          />
        </div>

        <div className="palette-list" role="listbox">
          {filtered.length === 0 ? (
            <div className="palette-empty">{t("palette_empty", language)}</div>
          ) : (
            filtered.map((item, idx) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={idx === selectedIndex}
                className={`palette-row${idx === selectedIndex ? " is-selected" : ""}`}
                data-testid={`palette-cmd-${item.id}`}
                onMouseEnter={() => setSelectedIndex(idx)}
                onClick={() => runItem(item)}
              >
                <span className="palette-row-label">
                  {item.labelText ?? t(item.labelKey, language)}
                </span>
                {item.shortcut ? (
                  <kbd className="palette-row-shortcut">{item.shortcut}</kbd>
                ) : null}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
