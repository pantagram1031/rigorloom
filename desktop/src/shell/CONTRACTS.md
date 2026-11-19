# Shell contracts (WP2, C0)

Names are J1 §5's. Import paths:

| Need | Import | Notes |
|---|---|---|
| Mount UI | `registerSlot(name, Component, {order, title, when, owner})` from `shell/slots` | Ship `desktop/src/<dir>/register.ts`; the shell loads it with `import.meta.glob`. Slots: `canvas`, `rightPanel`, `pane:files/outline/blanks/find/history`, `stripStart`, `stripEnd`, `statusLeft`, `statusRight`, `narrowSheet`, `settings:<id>`. Components get `{sessionId}`. |
| Per-document state | `defineDocSlice(key, initial)` from `store` | `slice.get/set/patch/reset(sessionId)`, hooks `slice.use(sessionId, select?)`, `slice.useActive(select?)`. Keys are package-prefixed (`canvas.zoom`). |
| Read a document record | `useDoc(sessionId)`, `useActiveDoc()` from `store` | |
| Keys | `bindKey(id, run)` from `shell/keymap` for product keys; `keys.register({id, chords, when, run})` from `shell/keys` otherwise; `useKeyHint(id)` for keycaps | Contexts via `keys.defineContext(name, () => bool)`. Physical keys; nothing fires while composing; single keys never fire in inputs. |
| Palette and menu rows | `registerCommand({id, title, run, keyId?, when?, enabled?, menu?})` from `shell/commands` | |
| Strings | `defineStrings("<wp>", {<wp>_key: {ko, en}})` in `i18n/v2/<wp>.ts` | Keys package-prefixed; no clash with `vocabulary.ts`. |
| Test ids | `TID`, `tabTid`, `markTid`, `changeRowTid`, `statusTid` from `shell/testids` | |
| Server routes | `register_routes(router)` in `runtime/scripts/rt_workspace.py`, `rt_page.py`, `rt_ui_style.py` | `router.get(path, handler(bridge, query))`, `router.post(path, handler(bridge, body))`; `/api/` only, no core shadowing; same token/Host/body-cap guards. |

## Swapping a package shim for these

WP3 (`canvas/_shim.ts`) and WP4 (`panel/_shim.ts`) coded against local stand-ins. The real API accepts their shapes, with these differences:

| Shim call | Real API | Change needed |
|---|---|---|
| WP3 `slice.set(patch, sessionId?)` | `slice.set(sessionId, patch)` | Swap the arguments. Omitting the document (`undefined`) still means the active one. |
| WP3/WP4 `set(doc, partial)` merging into an object | same | None: object slices shallow-merge; an updater's result merges too. |
| WP4 `useActiveDoc(): string \| null` | `useActiveDoc(): DocState \| null` | Use `useActiveDoc()?.sessionId`, or `useWorkspace((s) => s.activeSessionId)`. |
| WP3 `useDoc(id): {sessionId, name, kind, sha256}` | `DocState` has those fields plus `slices` | None. |
| `keys.register({..., when: () => boolean})` | accepted | None. Predicate-scoped bindings are separate scopes for `conflicts()`; `keys.activeConflicts()` checks the live state. |
| WP3 chords `KeyV`, `Ctrl+Equal`, `when: "always"` | accepted | None. |
| `registerCommand({title: string})` | accepted (`string` or `(lang) => string`) | None. |
| WP4 keymap ids `panel.*`, `change.*`, `approval.open`, `composer.focus`, `checks.style` | listed in `shell/keymap.ts` with WP4's chords | Register with the same ids; the registration replaces the keymap entry. |
| WP3 `requestLeftPane(pane)` | `showLeftPane(pane)` from `shell/bindings` | Rename. |
| WP3/WP4 `registerSlot(name, C)` | same, plus options `{order, title, when, owner}` | None. `settings:agent` needs `{title: (lang) => ...}` for its nav label. |

Known overlap to settle between WP3 and WP4: both bind `J`/`K`/`Y`/`N`/`E`/`U` (and WP3 `Ctrl+Z`). Keep the predicates exclusive (`review` while the 변경 pane has focus, the mark toolbar otherwise) or let one package own the keys; `keys.activeConflicts()` in a test catches a state where both answer.

The desktop app's `docFolder` pref (set by 폴더 열기 and 설정 through `savePrefs`) is display-only. The runtime never reads it as the 문서 폴더, and nothing lists from it; a desktop listing must set the folder through `POST /api/doc-folder`, which checks it, as the browser build does.
