import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";

import { Mark, Wordmark } from "../brand";
import { tWp1b } from "../i18n/v2/wp1b";
import type { UiLanguage } from "../i18n/vocabulary";
import "../tokens.css";
import { ApprovalBox } from "./ApprovalBox";
import { Button } from "./Button";
import { Keycap } from "./Keycap";
import { DiffLines, ListRow } from "./ListRow";
import { Menu, type MenuEntry } from "./Menu";
import { Popover } from "./Popover";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";
import { Tabs } from "./Tabs";
import { Tag } from "./Tag";
import { Tooltip } from "./Tooltip";
import { principleAttributes } from "./attributes";
import { ICON_NAMES, Icon } from "./icons";
import "./ui.css";

type ThemeMode = "light" | "dark";
type PaneId = "files" | "outline" | "blanks" | "find" | "history";
type PanelTabId = "changes" | "agent" | "check";
type ViewMode = "marks" | "clean" | "base";

function initialParams(): {
  theme: ThemeMode;
  lang: UiLanguage;
  overlay: string;
} {
  if (typeof window === "undefined") {
    return { theme: "light", lang: "ko", overlay: "inline" };
  }
  const params = new URLSearchParams(window.location.search);
  const theme: ThemeMode = params.get("theme") === "dark" ? "dark" : "light";
  const lang: UiLanguage = params.get("lang") === "en" ? "en" : "ko";
  const overlay = params.get("overlay") ?? "inline";
  return { theme, lang, overlay };
}

export function UiGallery() {
  const init = initialParams();
  const [theme, setTheme] = useState<ThemeMode>(init.theme);
  const [lang, setLang] = useState<UiLanguage>(init.lang);
  const [leftTab, setLeftTab] = useState<PaneId>("blanks");
  const [rightTab, setRightTab] = useState<PanelTabId>("changes");
  const [viewMode, setViewMode] = useState<ViewMode>("marks");
  const [selectedRow, setSelectedRow] = useState<number>(8);
  const [factConfirmed, setFactConfirmed] = useState<boolean>(true);
  const [menuOpen, setMenuOpen] = useState<boolean>(init.overlay === "menu" || init.overlay === "inline");
  const [popOpen, setPopOpen] = useState<boolean>(init.overlay === "popover" || init.overlay === "inline");
  const [dialogOpen, setDialogOpen] = useState<boolean>(init.overlay === "dialog");
  const [returnReason, setReturnReason] = useState<string>("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = lang;
  }, [theme, lang]);

  const inlineOverlays = init.overlay === "inline";

  const menuItems: readonly MenuEntry[] = [
    {
      id: "open-file",
      label: tWp1b("demo_menu_open", lang),
      shortcut: ["Ctrl", "O"],
    },
    {
      id: "open-folder",
      label: tWp1b("demo_menu_folder", lang),
      shortcut: ["Ctrl", "Shift", "O"],
    },
    { kind: "separator", id: "sep-1" },
    {
      id: "export",
      label: tWp1b("demo_export", lang),
      shortcut: ["Ctrl", "E"],
    },
    {
      id: "settings",
      label: tWp1b("demo_menu_settings", lang),
      shortcut: ["Ctrl", ","],
    },
  ];

  return (
    <div className="rl-gallery" data-testid="ui-gallery">
      <header className="rl-gallery-topbar" {...principleAttributes({ docked: true })}>
        <div className="rl-gallery-brand">
          <Mark size={16} />
          <Wordmark />
          <span className="rl-gallery-title">· {tWp1b("gallery_title", lang)}</span>
        </div>

        <div className="rl-gallery-controls">
          <Tooltip
            label={tWp1b("demo_tooltip_left", lang)}
            shortcut={["Alt", "1"]}
            open={init.overlay === "tooltip" ? true : undefined}
          >
            <Button
              variant="ghost"
              iconOnly
              aria-label={tWp1b("demo_tooltip_left", lang)}
            >
              <Icon name="panelLeft" size={16} />
            </Button>
          </Tooltip>
          <Tooltip label={tWp1b("demo_tooltip_right", lang)} shortcut={["Alt", "6"]}>
            <Button
              variant="ghost"
              iconOnly
              aria-label={tWp1b("demo_tooltip_right", lang)}
            >
              <Icon name="panelRight" size={16} />
            </Button>
          </Tooltip>

          <Segmented<ThemeMode>
            ariaLabel={tWp1b("gallery_title", lang)}
            value={theme}
            onChange={setTheme}
            options={[
              { value: "light", label: tWp1b("gallery_theme_light", lang) },
              { value: "dark", label: tWp1b("gallery_theme_dark", lang) },
            ]}
          />

          <Segmented<UiLanguage>
            ariaLabel={tWp1b("gallery_lang_ko", lang)}
            value={lang}
            onChange={setLang}
            options={[
              { value: "ko", label: tWp1b("gallery_lang_ko", lang) },
              { value: "en", label: tWp1b("gallery_lang_en", lang) },
            ]}
          />
        </div>
      </header>

      <main className="rl-gallery-grid">
        {/* 1. Buttons & Keycaps */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_buttons", lang)}</h2>
          <div className="rl-gallery-cluster">
            <Button variant="outline" shortcut="Y">
              {tWp1b("demo_accept", lang)}
            </Button>
            <Button variant="outline" shortcut="N">
              {tWp1b("demo_exclude", lang)}
            </Button>
            <Button variant="outline" shortcut="E">
              {tWp1b("demo_edit", lang)}
            </Button>
            <Button variant="ghost" shortcut="R">
              {tWp1b("demo_return", lang)}
            </Button>
          </div>

          <div className="rl-gallery-cluster">
            <Button variant="outline" size="lg" shortcut={["Ctrl", "E"]}>
              {tWp1b("demo_export", lang)}
            </Button>
            <Button variant="outline" size="lg" shortcut="Enter">
              {tWp1b("demo_send", lang)}
            </Button>
            <Button variant="outline" disabled shortcut="Y">
              {tWp1b("demo_accept", lang)}
            </Button>
          </div>

          <div className="rl-gallery-cluster">
            <Button variant="outline" size="touch">
              {tWp1b("demo_accept", lang)}
            </Button>
            <Keycap keys={["Ctrl", "K"]} />
            <Keycap keys={["Ctrl", "Shift", "Enter"]} />
            <Keycap keys="Esc" />
          </div>
        </section>

        {/* 2. Tags & Provenance */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_tags", lang)}</h2>
          <div className="rl-gallery-cluster">
            <Tag tone="agent" source="agent">
              {tWp1b("demo_source_agent", lang)}
            </Tag>
            <Tag tone="outline" source="user">
              {tWp1b("demo_source_user", lang)}
            </Tag>
            <Tag tone="attn" source="test">
              {tWp1b("demo_source_test", lang)}
            </Tag>
            <Tag tone="outline" source="revert">
              {tWp1b("demo_source_revert", lang)}
            </Tag>
          </div>

          <div className="rl-gallery-cluster">
            <Tag tone="fact">{tWp1b("demo_tag_fact", lang)}</Tag>
            <Tag tone="attn">{tWp1b("demo_tag_attn", lang, [1])}</Tag>
            <Tag tone="neutral">{tWp1b("demo_tag_numbers", lang)}</Tag>
            <Tag tone="neutral">{tWp1b("demo_tag_prefilled", lang)}</Tag>
            <Tag tone="agent" accentCount numeric>
              24
            </Tag>
          </div>

          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_tabs", lang)}</h2>
          <Tabs<PaneId>
            ariaLabel={tWp1b("gallery_sec_tabs", lang)}
            value={leftTab}
            onChange={setLeftTab}
            items={[
              { id: "files", label: tWp1b("demo_pane_files", lang) },
              { id: "outline", label: tWp1b("demo_pane_outline", lang) },
              { id: "blanks", label: tWp1b("demo_pane_blanks", lang) },
              { id: "find", label: tWp1b("demo_pane_find", lang) },
              { id: "history", label: tWp1b("demo_pane_history", lang) },
            ]}
          />

          <Tabs<PanelTabId>
            ariaLabel={tWp1b("demo_panel_changes", lang)}
            value={rightTab}
            onChange={setRightTab}
            items={[
              {
                id: "changes",
                label: tWp1b("demo_panel_changes", lang),
                count: 24,
                countTone: "accent",
              },
              { id: "agent", label: tWp1b("demo_panel_agent", lang) },
              {
                id: "check",
                label: tWp1b("demo_panel_check", lang),
                count: 1,
                countTone: "attn",
                dot: "attn",
              },
            ]}
          />

          <div className="rl-gallery-cluster">
            <Segmented<ViewMode>
              ariaLabel={tWp1b("demo_seg_marks", lang)}
              value={viewMode}
              onChange={setViewMode}
              options={[
                { value: "marks", label: tWp1b("demo_seg_marks", lang) },
                { value: "clean", label: tWp1b("demo_seg_clean", lang) },
                { value: "base", label: tWp1b("demo_seg_base", lang) },
              ]}
            />
          </div>
        </section>

        {/* 3. ListRow & ChangeRow densities */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_rows", lang)}</h2>
          <div>
            <ListRow
              density="tree"
              title={tWp1b("demo_outline_heading", lang)}
              trailing="1–4"
              onActivate={() => setSelectedRow(1)}
            />
            <ListRow
              density="tree"
              indent={1}
              selected={selectedRow === 1}
              title={tWp1b("demo_outline_body", lang)}
              trailing="5–8"
              onActivate={() => setSelectedRow(1)}
            />
            <ListRow
              density="change"
              index={5}
              barTone="accepted"
              source="agent"
              title={tWp1b("demo_row_agency", lang)}
              meta={`${tWp1b("demo_row_op_fill", lang)} · ${tWp1b("demo_source_agent", lang)}`}
              subtitle={tWp1b("demo_row_agency_val", lang)}
              trailing={tWp1b("demo_row_accepted", lang)}
              selected={selectedRow === 5}
              onActivate={() => setSelectedRow(5)}
            />
            <ListRow
              density="change"
              index={8}
              barTone="agent"
              source="agent"
              selected={selectedRow === 8}
              title={tWp1b("demo_row_body", lang)}
              meta={`${tWp1b("demo_row_op_fill", lang)} · ${tWp1b("demo_source_agent", lang)}`}
              trailing={<Tag tone="neutral">{tWp1b("demo_tag_numbers", lang)}</Tag>}
              onActivate={() => setSelectedRow(8)}
            >
              <DiffLines
                beforeLabel={tWp1b("demo_row_before", lang)}
                afterLabel={tWp1b("demo_row_after", lang)}
                before={tWp1b("demo_row_body", lang)}
                after={tWp1b("demo_row_body_after", lang)}
              />
              <div className="rl-gallery-cluster">
                <Button variant="outline" shortcut="Y">
                  {tWp1b("demo_accept", lang)}
                </Button>
                <Button variant="outline" shortcut="N">
                  {tWp1b("demo_exclude", lang)}
                </Button>
                <Button variant="outline" shortcut="E">
                  {tWp1b("demo_edit", lang)}
                </Button>
              </div>
            </ListRow>
            <ListRow
              density="change"
              index={22}
              barTone="fact"
              fact
              source="agent"
              selected={selectedRow === 22}
              title={tWp1b("demo_row_term", lang)}
              meta={`${tWp1b("demo_row_op_replace", lang)} · ${tWp1b("demo_source_agent", lang)}`}
              subtitle={tWp1b("demo_row_term_diff", lang)}
              trailing={<Tag tone="fact">{tWp1b("demo_tag_fact", lang)}</Tag>}
              onActivate={() => setSelectedRow(22)}
            />
          </div>
        </section>

        {/* 4. ApprovalBox & Docked Sheet (holds the ONE primary ink button in the window) */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_approval", lang)}</h2>

          <ApprovalBox
            lang={lang}
            compact
            propose={tWp1b("demo_source_agent", lang)}
            check={tWp1b("demo_box_check_val", lang, [0, 1])}
            approve={tWp1b("demo_box_approved_val", lang)}
          />

          <Sheet
            open
            placement="right"
            lang={lang}
            title={tWp1b("demo_sheet_title", lang, [24])}
            subtitle={tWp1b("demo_sheet_sub", lang)}
            onClose={() => setDialogOpen(false)}
            footer={
              <>
                <Button variant="outline" shortcut="Esc">
                  {tWp1b("demo_cancel", lang)}
                </Button>
                <Button
                  variant="primary"
                  size="lg"
                  shortcut="Enter"
                  disabled={!factConfirmed}
                >
                  {tWp1b("demo_approve", lang)}
                </Button>
              </>
            }
          >
            <ApprovalBox
              lang={lang}
              hasChangedFact
              propose={tWp1b("demo_box_propose_val", lang, [24])}
              check={tWp1b("demo_box_check_val", lang, [1, 1])}
            />
            <div className="rl-gallery-fact-callout" {...principleAttributes({ fact: true })}>
              <div className="rl-gallery-kv">
                <span>{tWp1b("demo_row_term", lang)}</span>
                <Tag tone="fact">{tWp1b("demo_tag_fact", lang)}</Tag>
              </div>
              <div>{tWp1b("demo_row_term_diff", lang)}</div>
            </div>
            <label className="rl-checkbox-row">
              <input
                type="checkbox"
                className="rl-checkbox"
                checked={factConfirmed}
                onChange={(e) => setFactConfirmed(e.target.checked)}
              />
              <span>{tWp1b("demo_fact_confirm", lang)}</span>
            </label>
            <div className="rl-gallery-kv">
              <span>{tWp1b("demo_sheet_base_label", lang)}</span>
              <span className="rl-gallery-kv-val">{tWp1b("demo_sheet_base_val", lang)}</span>
            </div>
            <div className="rl-gallery-kv">
              <span>{tWp1b("demo_sheet_next_label", lang)}</span>
              <span className="rl-gallery-kv-val">{tWp1b("demo_sheet_next_val", lang)}</span>
            </div>
          </Sheet>
        </section>

        {/* 5. Floating layers: Menu & Popover */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_overlays", lang)}</h2>
          <div className="rl-gallery-cluster">
            <Menu
              open={menuOpen}
              onOpenChange={setMenuOpen}
              inline={inlineOverlays}
              ariaLabel={tWp1b("menu_app_label", lang)}
              items={menuItems}
              trigger={
                !inlineOverlays ? (
                  <Button
                    variant="outline"
                    onClick={() => setMenuOpen((prev) => !prev)}
                  >
                    {tWp1b("menu_app_label", lang)}
                  </Button>
                ) : undefined
              }
            />
          </div>

          <div className="rl-gallery-cluster">
            <Popover
              open={popOpen}
              onOpenChange={setPopOpen}
              inline={inlineOverlays}
              align="start"
              ariaLabel={tWp1b("demo_return", lang)}
              trigger={
                !inlineOverlays ? (
                  <Button
                    variant="outline"
                    shortcut="R"
                    onClick={() => setPopOpen((prev) => !prev)}
                  >
                    {tWp1b("demo_return", lang)}
                  </Button>
                ) : undefined
              }
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--s-8)" }}>
                <label
                  htmlFor="gallery-return-reason"
                  style={{ fontSize: "var(--text-sm)", color: "var(--text-2)" }}
                >
                  {tWp1b("demo_pop_return_label", lang)}
                </label>
                <input
                  id="gallery-return-reason"
                  className="rl-input"
                  value={returnReason}
                  onChange={(e) => setReturnReason(e.target.value)}
                />
                <div className="rl-gallery-cluster">
                  <Button variant="outline">{tWp1b("demo_return", lang)}</Button>
                  <Button variant="outline">{tWp1b("demo_pop_return_rerequest", lang)}</Button>
                </div>
              </div>
            </Popover>
          </div>
        </section>

        {/* 6. 28-glyph Icon Set (16 px + 20 px) & Shipped Brand Mark */}
        <section className="rl-gallery-panel" {...principleAttributes({ docked: true })}>
          <h2 className="rl-gallery-sec-head">{tWp1b("gallery_sec_icons", lang)}</h2>
          <div className="rl-gallery-cluster">
            <Mark size={16} />
            <Mark size={20} />
            <Mark size={32} />
            <Wordmark />
          </div>
          <div className="rl-gallery-icon-grid">
            {ICON_NAMES.map((iconName) => (
              <div key={iconName} className="rl-gallery-icon-cell" title={iconName}>
                <Icon name={iconName} size={16} />
                <Icon name={iconName} size={20} />
              </div>
            ))}
          </div>
        </section>
      </main>

      <Sheet
        open={dialogOpen}
        placement="dialog"
        lang={lang}
        title={tWp1b("demo_menu_settings", lang)}
        onClose={() => setDialogOpen(false)}
        footer={
          <Button variant="outline" shortcut="Esc" onClick={() => setDialogOpen(false)}>
            {tWp1b("demo_cancel", lang)}
          </Button>
        }
      >
        <div>{tWp1b("demo_cmd_find", lang)}</div>
      </Sheet>
    </div>
  );
}

export function mountUiGallery(rootElement: HTMLElement): void {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <UiGallery />
    </React.StrictMode>,
  );
}
