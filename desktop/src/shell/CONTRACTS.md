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
