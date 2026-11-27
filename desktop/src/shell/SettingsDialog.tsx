/**
 * 설정 (Ctrl+,): a centred 640 px dialog. Sections 일반 and 폴더 are the
 * shell's; packages add sections through `settings:<id>` slots (WP4 registers
 * `settings:agent`). 개발 appears only in development builds.
 */
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { useEffect, useRef, useState } from "react";

import { setLanguage, switchWorkspaceRoot, toggleTheme } from "../actions";
import { t as vt } from "../i18n/vocabulary";
import { S } from "../i18n/v2/shell";
import * as rt from "../runtime";
import { useWorkspace } from "../store";
import { openV1 } from "./bindings";
import { Btn } from "./parts";
import { setShell, useShell, type SettingsSection } from "./shellState";
import { Slot, useSlotsVersion } from "./Slot";
import { slotEntries, slotNames, type SlotName } from "./slots";
import { TID } from "./testids";

/** A section's nav label: the registration's title, else a known name; never the raw slot id. */
function sectionLabel(name: SlotName, lang: "ko" | "en"): string {
  const title = slotEntries(name)[0]?.title?.(lang);
  if (title) return title;
  if (name === "settings:agent") return S.t("shell_settings_agent", lang);
  return S.t("shell_settings_title", lang);
}

export function SettingsDialog() {
  const open = useShell((s) => s.settingsOpen);
  if (!open) return null;
  return <SettingsBody />;
}

function SettingsBody() {
  useSlotsVersion();
  const lang = useWorkspace((s) => s.language);
  const section = useShell((s) => s.settingsSection ?? "general");
  const ref = useRef<HTMLDivElement>(null);
  const extra = slotNames("settings:");

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[data-settings-nav] button[aria-selected="true"]')?.focus();
  }, [section]);

  const sections: Array<{ id: SettingsSection; label: string }> = [
    { id: "general", label: S.t("shell_settings_general", lang) },
    ...extra.map((name) => ({ id: name as SettingsSection, label: sectionLabel(name, lang) })),
    { id: "folders", label: S.t("shell_settings_folders", lang) },
  ];

  return (
    <div className="sh-scrim" onMouseDown={(e) => e.target === e.currentTarget && setShell({ settingsOpen: false })}>
      <div
        className="sh-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sh-settings-title"
        data-testid={TID.settingsDialog}
        ref={ref}
        onKeyDown={(e) => {
          if (e.key !== "Tab") return;
          // Keep focus inside the dialog.
          const items = Array.from(ref.current?.querySelectorAll<HTMLElement>("button, input, select, [tabindex='0']") ?? []).filter(
            (el) => !el.hasAttribute("disabled"),
          );
          if (items.length === 0) return;
          const first = items[0];
          const last = items[items.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }}
      >
        <header className="sh-dialog-head">
          <h2 id="sh-settings-title" className="sh-dialog-title">{S.t("shell_settings_title", lang)}</h2>
          <Btn variant="quiet" onClick={() => setShell({ settingsOpen: false })} testId="settings-close">
            {S.t("shell_settings_close", lang)} <kbd className="sh-key">Esc</kbd>
          </Btn>
        </header>
        <div className="sh-dialog-body">
          <nav className="sh-settings-nav" data-settings-nav role="tablist" aria-orientation="vertical">
            {sections.map((s) => (
              <button
                type="button"
                key={s.id}
                role="tab"
                aria-selected={section === s.id}
                className="sh-settings-navrow"
                data-testid={`settings-nav-${String(s.id).replace(":", "-")}`}
                onClick={() => setShell({ settingsSection: s.id })}
              >
                {s.label}
              </button>
            ))}
          </nav>
          <div className="sh-settings-content" role="tabpanel">
            {section === "general" ? <GeneralSection /> : null}
            {section === "folders" ? <FolderSection /> : null}
            {section !== "general" && section !== "folders" ? <Slot name={section as SlotName} sessionId={null} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  testId,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (v: T) => void;
  label: string;
  testId: string;
}) {
  return (
    <div className="sh-seg" role="radiogroup" aria-label={label} data-testid={testId}>
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          className="sh-seg-item"
          data-testid={`${testId}-${o.value}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function GeneralSection() {
  const lang = useWorkspace((s) => s.language);
  const theme = useWorkspace((s) => s.theme);
  // The canvas status line is behind this dialog, so a refused switch is also
  // said here, next to the control that was pressed.
  const [editorRefused, setEditorRefused] = useState(false);
  return (
    <div className="sh-settings-rows">
      <div className="sh-settings-row">
        <span className="sh-settings-label">{S.t("shell_settings_language", lang)}</span>
        <Segmented
          value={lang}
          label={S.t("shell_settings_language", lang)}
          testId="settings-language"
          options={[
            { value: "ko", label: S.t("shell_settings_lang_ko", lang) },
            { value: "en", label: S.t("shell_settings_lang_en", lang) },
          ]}
          onChange={(v) => void setLanguage(v)}
        />
      </div>
      <div className="sh-settings-row">
        <span className="sh-settings-label">{S.t("shell_settings_theme", lang)}</span>
        <Segmented
          value={theme}
          label={S.t("shell_settings_theme", lang)}
          testId="settings-theme"
          options={[
            { value: "auto", label: S.t("shell_settings_theme_system", lang) },
            { value: "light", label: S.t("shell_settings_theme_light", lang) },
            { value: "dark", label: S.t("shell_settings_theme_dark", lang) },
          ]}
          onChange={(v) => void toggleTheme(v)}
        />
      </div>
      <div className="sh-settings-row sh-settings-row--stack">
        <div className="sh-settings-row-head">
          <span className="sh-settings-label">{S.t("shell_settings_editor", lang)}</span>
          <Segmented
            value="v2"
            label={S.t("shell_settings_editor", lang)}
            testId="settings-editor"
            options={[
              { value: "v2", label: S.t("shell_settings_editor_v2", lang) },
              { value: "v1", label: S.t("shell_settings_editor_v1", lang, ["v1"]) },
            ]}
            onChange={(v) => {
              if (v !== "v1") return;
              setEditorRefused(false);
              void openV1().then((switched) => {
                if (!switched) setEditorRefused(true);
              });
            }}
          />
        </div>
        <span className="sh-settings-note" data-testid="settings-editor-note">
          {S.t("shell_settings_editor_note", lang)}
        </span>
        {editorRefused ? (
          <span
            className="sh-settings-note sh-settings-note--refused"
            role="status"
            data-testid="settings-editor-refused"
          >
            {S.t("shell_status_finish_edit_first", lang)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function FolderSection() {
  const lang = useWorkspace((s) => s.language);
  const root = useWorkspace((s) => s.root);
  const docFolder = useShell((s) => s.docFolder);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(root ?? "");
  const [error, setError] = useState<string | null>(null);
  const tauri = rt.isTauri();

  async function change(next: string) {
    const result = await switchWorkspaceRoot(next);
    if (result.ok) {
      setEditing(false);
      setError(null);
    } else {
      setError(result.error?.message ?? null);
    }
  }

  return (
    <div className="sh-settings-rows">
      <div className="sh-settings-row sh-settings-row--stack">
        <span className="sh-settings-label">{S.t("shell_settings_work_folder", lang)}</span>
        <span className="sh-settings-note">{S.t("shell_settings_work_folder_note", lang)}</span>
        {editing && !tauri ? (
          <div className="sh-settings-inline">
            <input
              className="sh-input sh-mono"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label={S.t("shell_settings_work_folder", lang)}
              data-testid="settings-folder-input"
            />
            <Btn onClick={() => void change(value)} testId="settings-folder-apply">{vt("settings_folder_apply", lang)}</Btn>
          </div>
        ) : (
          <div className="sh-settings-inline">
            <span className="sh-mono sh-path" data-testid="settings-folder-path">{root}</span>
            <Btn
              testId="settings-folder-change"
              onClick={async () => {
                if (tauri) {
                  const chosen = await openDialog({ multiple: false, directory: true });
                  if (typeof chosen === "string") await change(chosen);
                } else {
                  setValue(root ?? "");
                  setEditing(true);
                }
              }}
            >
              {vt("settings_folder_change", lang)}
            </Btn>
          </div>
        )}
        {error ? <span className="sh-settings-error" role="alert">{error}</span> : null}
      </div>
      {tauri ? (
        <div className="sh-settings-row sh-settings-row--stack">
          <span className="sh-settings-label">{S.t("shell_settings_doc_folder", lang)}</span>
          <div className="sh-settings-inline">
            <span className="sh-mono sh-path">{docFolder ?? ""}</span>
            <Btn
              onClick={async () => {
                const chosen = await openDialog({ multiple: false, directory: true });
                if (typeof chosen === "string") {
                  setShell({ docFolder: chosen });
                  void rt.savePrefs({ docFolder: chosen }).catch(() => {});
                }
              }}
            >
              {vt("settings_folder_change", lang)}
            </Btn>
          </div>
        </div>
      ) : null}
    </div>
  );
}
