import { useEffect, useMemo, useState } from "react";
import {
  closeCommandPalette,
  exportApplied,
  loadCorpusFiles,
  navigateScreen,
  openApprovalDialog,
  openOperatorModal,
  openViaDialog,
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
  shortcut?: string;
  keywords: string;
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
        keywords: "열기 파일 선택 open file",
        run: () => {
          navigateScreen("open");
          void openViaDialog();
        },
      },
      {
        id: "open-builtin",
        labelKey: "cmd_open_builtin",
        keywords: "예시 양식 열기 기본 open form example",
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
        keywords: "검토 화면 이동 review",
        run: () => navigateScreen("review"),
      });
      items.push({
        id: "toggle-print-view",
        labelKey: "cmd_toggle_print_view",
        keywords: "인쇄 화면 문서 보기 print view",
        run: () => togglePrintView(),
      });
    }

    if (canApprove) {
      items.push({
        id: "approve",
        labelKey: "cmd_approve",
        shortcut: "A",
        keywords: "승인 적용 approve",
        run: () => openApprovalDialog(),
      });
    }

    if (hasPlan) {
      items.push({
        id: "return",
        labelKey: "cmd_return",
        shortcut: "R",
        keywords: "돌려보내기 반려 return",
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
        shortcut: "Ctrl+E",
        keywords: "내보내기 저장 export",
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
        keywords: "언어 한국어 영어 language",
        run: () => void toggleLanguage(),
      },
      {
        id: "change-theme",
        labelKey: "cmd_change_theme",
        keywords: "화면 테마 밝게 어둡게 theme",
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
        keywords: "설정 settings",
        run: () => setState({ settingsOpen: true }),
      },
      {
        id: "open-by-path",
        labelKey: "cmd_open_by_path_details",
        keywords: "경로 자세히 열기 path details",
        run: () => {
          setState({ openDialogOpen: true });
          void loadCorpusFiles();
        },
      },
      {
        id: "operator-agent",
        labelKey: "cmd_operator_agent_details",
        keywords: "에이전트 연결 작업 기록 자세히 agent log details",
        run: () => openOperatorModal(),
      },
    );

    return items;
  }, [session, hasPlan, canApprove, canExport, theme, language]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((item) => {
      const label = t(item.labelKey, language).toLowerCase();
      return label.includes(q) || item.keywords.toLowerCase().includes(q);
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
                <span className="palette-row-label">{t(item.labelKey, language)}</span>
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
