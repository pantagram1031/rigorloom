# Rigorloom Studio v2

Rigorloom Studio is a localhost-only, offline workspace dashboard. It shows all
report workspaces, stage and gate state, conformance, gate-check provenance,
events, humanization rounds, bundle previews, and PDF output. It has no CDN or
network dependency.

```sh
python -m pip install -r studio/requirements.txt
python studio/main.py
```

The default contract is read-only. The server binds only to `127.0.0.1` and
does not call model providers or external services. Optional actions are hidden
and every action POST returns HTTP 403 unless `STUDIO_ALLOW_ACTIONS=1` is set.
Action mode can append an operator approval and invoke repository pipeline
commands, so enable it only for a workspace you intend to operate.

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
- `STUDIO_ALLOW_ACTIONS`: set exactly to `1` to expose and allow the four action
  endpoints. Any other value keeps Studio read-only.
- `STUDIO_ACTION_TOKEN`: override the generated action token (e.g. to keep a
  stable token across restarts). Only read when `STUDIO_ALLOW_ACTIONS=1`.

When available, `pipeline/scripts/workflow_lint.py` runs with `--json` and a
30-second timeout. Results are cached for 60 seconds per workspace. Missing or
unparseable lint output is displayed as `lint n/a`; it never prevents the
dashboard from rendering.
