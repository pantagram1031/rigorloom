# Desktop reference screenshots (R6)

PNGs live next to this file. Captured from the vite dev-mock at
`http://localhost:5184` with Chrome headless via CDP (no extra npm deps).

## States

- `home` — welcome / recents
- `workspace` — document workspace, inspector on 선택
- `review` — 검토 with one queued hunk on 표 0 R0C14
- `history` — 기록
- `agent` — 에이전트
- `popover` — ⋯ 자세히 verification popover

Each state has 1280×800 and 1920×1080, light and dark
(`prefers-color-scheme`).

## Recapture

With the mock already serving on 5184:

```bash
npx vite --port 5184 --strictPort
node docs/demo/desktop/capture.mjs
```

Demo GIF (home → recent → agent plan → review → approve → apply → receipt), 1280×800, assembled with Pillow:

```bash
npx vite --port 5184 --strictPort
node docs/demo/desktop/capture.mjs gif
```

If Chrome is missing, Edge works with the same flags:

```bash
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --screenshot=docs/demo/desktop/home-1280x800-light.png --window-size=1280,800 http://localhost:5184
```

That Edge `--screenshot` flag only dumps the first paint (Home after splash).
Interactive states (검토 queue, 자세히 popover) need the CDP script above.
