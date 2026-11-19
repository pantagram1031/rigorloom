/**
 * The data-testid list (D1 §8 day-1 contracts). Tests and the smoke address the
 * UI through these names only; packages use the helpers so the spelling never
 * drifts.
 *
 * Owned by WP2. Packages own the elements, not the names: add a name here in a
 * one-line cross-WP edit rather than inventing a local spelling.
 */
export const TID = {
  // shell (WP2)
  shell: "shell",
  titlebar: "titlebar",
  appMenu: "app-menu",
  tabbar: "tabbar",
  tabStart: "tab-start",
  tabAdd: "tab-add",
  tabList: "tab-list",
  paletteField: "palette-field",
  toggleLeft: "toggle-left",
  toggleRight: "toggle-right",
  leftPane: "left-pane",
  paneTabs: "pane-tabs",
  rightPanel: "right-panel",
  canvas: "canvas",
  docStrip: "doc-strip",
  statusbar: "statusbar",
  start: "start",
  startOpenFile: "start-open-file",
  startOpenFolder: "start-open-folder",
  startSamples: "start-samples",
  startRecent: "start-recent",
  startEngineMissing: "start-engine-missing",
  dropOutline: "drop-outline",
  docFailed: "doc-failed",
  docOpening: "doc-opening",
  palette: "palette",
  paletteInput: "palette-input",
  settingsDialog: "settings-dialog",
  filesPane: "files-pane",

  // canvas (WP3)
  paper: "paper",
  viewSwitch: "view-switch",
  stepper: "stepper",
  markToolbar: "mark-toolbar",

  // panel and gate (WP4)
  approve: "approve",
  approveSheet: "approve-sheet",
  approveConfirm: "approve-confirm",
  return: "return",
  composer: "composer",
  staleBanner: "stale-banner",

  // history (WP5)
  exportButton: "export",
} as const;

export type TestId = (typeof TID)[keyof typeof TID];

/** `tab-<sessionId>` for a document tab. */
export const tabTid = (sessionId: string) => `tab-${sessionId}`;
/** `tab-close-<sessionId>`. */
export const tabCloseTid = (sessionId: string) => `tab-close-${sessionId}`;
/** `pane-tab-<id>` for a left pane tab (`files`, `outline`, `blanks`, `find`, `history`). */
export const paneTabTid = (id: string) => `pane-tab-${id}`;
/** `mark-<n>` for the page mark of change n (WP3). */
export const markTid = (n: number | string) => `mark-${n}`;
/** `change-row-<n>` for change n in the 변경 pane (WP4). */
export const changeRowTid = (n: number | string) => `change-row-${n}`;
/** `status-<name>`: `status-page`, `status-seat`, `status-chars`, `status-engine`, `status-agent`, `status-saved`, `status-zoom`, `status-findings`, `status-fonts`, `status-changes`. */
export const statusTid = (name: string) => `status-${name}`;
/** `recent-<index>` on the Start tab. */
export const recentTid = (i: number) => `recent-${i}`;
/** `palette-row-<id>`. */
export const paletteRowTid = (id: string) => `palette-row-${id}`;
