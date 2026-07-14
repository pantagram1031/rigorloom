# Rigorloom Studio v2

Rigorloom Studio is a localhost-only, offline workspace dashboard. It shows all
report workspaces, stage and gate state, conformance, gate-check provenance,
events, humanization rounds, bundle previews, PDF output, and the machine's
Hancom/LibreOffice rendering capabilities. It has no CDN or network dependency.

```sh
python -m pip install -r studio/requirements.txt
python studio/main.py
```

The default contract is read-only. The server binds only to `127.0.0.1` and
does not call model providers or external services. Optional actions are hidden
and every action POST returns HTTP 403 unless `STUDIO_ALLOW_ACTIONS=1` is set.
Action mode can append an operator approval and invoke repository pipeline
commands, including the bundle and COM-free HWPX document backends, so enable
it only for a workspace you intend to operate. The HWPX button is disabled
unless the capability probe reports a renderer or `HWP_MASTER_SCRIPTS` is set.

### Render capabilities and proof grades

Studio runs `pipeline/scripts/render_probe.py` once per server process in a
separate Python subprocess with a 20-second timeout. The dashboard and workspace
detail show green/gray chips for Hancom COM, native `soffice`, WSL `soffice`,
and H2Orestart. If the probe module is absent, fails to import, times out, or
returns an unexpected payload, Studio shows one gray `probe n/a` chip and keeps
the rest of the dashboard usable.

For document proof state, Studio reads the newest `*verdict*.json` file under a
workspace's `output/` directory. PDF and deliverable panels are always labeled:

- `hancom`: green `제출급 증명`
- `advisory`: amber `참고용 렌더 (LibreOffice)`
- `none` or no verdict: gray `렌더 증명 없음`

The XML verdict panel also shows gappy pages, the `needs[]` count, and
`renderer_failed`. LibreOffice output is advisory evidence and is never shown
without that qualification.

### Action mode CSRF protection

When `STUDIO_ALLOW_ACTIONS=1`, Studio generates a random per-run action token
at startup (`secrets.token_urlsafe(16)`) and prints it once to the console as
`[studio] action token (send as X-Studio-Token header): <token>`. Every
`POST /action/...` request must carry that token in an `X-Studio-Token`
header, and a `Host` header starting with `127.0.0.1` or `localhost` —
otherwise the request is rejected with HTTP 403. This stops a hostile page
open in the same browser from silently POSTing actions to the local server.

The dashboard page (`/`) reads the current token from a `<meta
name="studio-action-token">` tag the server injects only into pages it
serves itself, and sends it automatically on every action click — no manual
step needed when using the bundled UI in a normal browser tab.

Environment variables:

- `STUDIO_WORKSPACE_ROOT`: workspace parent directory. Defaults to the repo's
  `workspaces/` directory when present, otherwise `~/rigorloom-workspaces`.
- `STUDIO_STAGES_YAML`: alternate stage-definition file used for stage order.
- `STUDIO_ALLOW_ACTIONS`: set exactly to `1` to expose and allow the five action
  endpoints. Any other value keeps Studio read-only.
- `STUDIO_ACTION_TOKEN`: override the generated action token (e.g. to keep a
  stable token across restarts). Only read when `STUDIO_ALLOW_ACTIONS=1`.

When available, `pipeline/scripts/workflow_lint.py` runs with `--json` and a
30-second timeout. Results are cached for 60 seconds per workspace. Missing or
unparseable lint output is displayed as `lint n/a`; it never prevents the
dashboard from rendering.
