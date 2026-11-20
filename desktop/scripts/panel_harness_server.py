"""Serve the WP4 panel harness through the real ``rigorloom ui`` bridge.

Dev only: the bundle comes from ``vite.panel-harness.config.ts`` in a
temporary directory; the bridge serves the style route through its own
extension hook. Usage: panel_harness_server.py DIST ROOT PORT
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_ui  # noqa: E402


def main() -> int:
    dist = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    rt_ui.BridgeApplication._ui_dist_dir = lambda self: dist  # type: ignore[method-assign]

    def render_index_html(self) -> bytes:
        html = (dist / "panel-harness.html").read_text(encoding="utf-8")
        return rt_ui._inject_bootstrap(html, {"token": self.token, "root": str(self.current_root())}).encode("utf-8")

    rt_ui.BridgeApplication.render_index_html = render_index_html  # type: ignore[method-assign]
    return rt_ui.run_ui(root=root, port=port, no_open=True, explicit_root=True)


if __name__ == "__main__":
    raise SystemExit(main())
