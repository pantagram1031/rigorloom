# -*- coding: utf-8 -*-
"""figstyle.py — deterministic matplotlib look from a figure_style pack.

Library + tiny CLI. The MODULE imports only the stdlib: matplotlib is imported
lazily INSIDE the functions that actually need it, so `import figstyle` and
`python figstyle.py --dump` work on a CI box with no matplotlib installed.

Public API:
  resolve_rcparams(pack) -> dict   pure-python rcParams mapping (dump-friendly)
  apply(pack=None)                 push the resolved rcParams into matplotlib
  parula()                         a matplotlib LinearSegmentedColormap
  legend_out(ax, **kw)             thin-boxed legend placed below the axes

CLI:
  python figstyle.py --dump [--pack <file>]   print resolved rcParams as JSON
"""
import sys, json, argparse
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_DEFAULTS_DIR = _SCRIPTS_DIR.parent / "references" / "preference_packs" / "defaults"
DEFAULT_FIGURE_PACK = _DEFAULTS_DIR / "figure_style.json"

# sans-serif fallback chain (Korean-capable fonts first, then portable ones).
_SANS_FALLBACK = ["Malgun Gothic", "NanumGothic", "DejaVu Sans", "Arial", "sans-serif"]

# Parula control points — public-domain reproduction of the MATLAB parula
# colormap sampled at ~10 anchors, RGB in 0..1, evenly spaced for linear
# segmentation between anchors.
_PARULA_ANCHORS = [
    (0.2081, 0.1663, 0.5292),
    (0.2115, 0.2938, 0.7530),
    (0.1959, 0.4222, 0.8828),
    (0.1707, 0.5340, 0.8574),
    (0.1132, 0.6280, 0.7896),
    (0.0759, 0.7178, 0.6866),
    (0.2178, 0.7789, 0.5502),
    (0.5300, 0.8081, 0.3593),
    (0.8393, 0.7973, 0.2039),
    (0.9769, 0.9839, 0.0805),
]


def default_pack():
    return json.loads(DEFAULT_FIGURE_PACK.read_text(encoding="utf-8"))


def load_pack(path):
    """Load a figure_style pack via personalization_ctl.load_pack_file."""
    import personalization_ctl
    return personalization_ctl.load_pack_file(Path(path))


def resolve_rcparams(pack=None):
    """Pure-python: merge pack over the public default and return a plain
    rcParams-shaped dict. 'axes.prop_cycle' is represented as {'color': [...]}
    (a plain dict) so it is JSON-dumpable without matplotlib; apply() converts
    it to a real cycler. No matplotlib import here."""
    base = default_pack()
    if pack:
        merged = dict(base)
        merged.update({k: v for k, v in pack.items() if v is not None})
    else:
        merged = base

    box = merged.get("spines", "box") == "box"
    bg = merged.get("background", "#ffffff")
    tick_dir = merged.get("tick_direction", "out")
    legend = merged.get("legend", {}) or {}
    font_family = merged.get("font_family", "sans-serif")
    rc = {
        "figure.dpi": merged.get("dpi", 300),
        "savefig.dpi": merged.get("dpi", 300),
        "figure.facecolor": bg,
        "axes.facecolor": bg,
        "savefig.facecolor": bg,
        "axes.edgecolor": "#000000",
        "axes.linewidth": 0.8,
        "axes.spines.top": box,
        "axes.spines.right": box,
        "axes.spines.left": True,
        "axes.spines.bottom": True,
        "axes.grid": True,
        "grid.color": merged.get("grid_color", "#d9d9d9"),
        "grid.linewidth": 0.6,
        "xtick.direction": tick_dir,
        "ytick.direction": tick_dir,
        "axes.unicode_minus": False,
        "font.family": font_family,
        "font.sans-serif": _SANS_FALLBACK,
        "legend.frameon": bool(legend.get("frame", True)),
        "legend.framealpha": 1.0,
        "axes.prop_cycle": {"color": merged.get("color_cycle", [])},
    }
    return rc


def apply(pack=None):
    """Push the resolved rcParams into matplotlib. Imports matplotlib lazily."""
    import matplotlib
    from cycler import cycler
    rc = resolve_rcparams(pack)
    prop = rc.pop("axes.prop_cycle", None)
    matplotlib.rcParams.update(rc)
    if prop and prop.get("color"):
        matplotlib.rcParams["axes.prop_cycle"] = cycler(color=prop["color"])
    return rc


def parula():
    """Return the parula colormap (LinearSegmentedColormap). Lazy mpl import."""
    from matplotlib.colors import LinearSegmentedColormap
    n = len(_PARULA_ANCHORS)
    positions = [i / (n - 1) for i in range(n)]
    cdict = {"red": [], "green": [], "blue": []}
    for pos, (r, g, b) in zip(positions, _PARULA_ANCHORS):
        cdict["red"].append((pos, r, r))
        cdict["green"].append((pos, g, g))
        cdict["blue"].append((pos, b, b))
    return LinearSegmentedColormap("parula", cdict)


def legend_out(ax, **kwargs):
    """Place a thin-boxed legend below the axes (outside the plotting area)."""
    opts = dict(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3,
                frameon=True, framealpha=1.0, edgecolor="#000000", borderpad=0.4)
    opts.update(kwargs)
    leg = ax.legend(**opts)
    if leg is not None and leg.get_frame() is not None:
        leg.get_frame().set_linewidth(0.6)
    return leg


def main():
    ap = argparse.ArgumentParser(description="figure_style pack -> matplotlib rcParams")
    ap.add_argument("--dump", action="store_true", help="print resolved rcParams as JSON (no matplotlib)")
    ap.add_argument("--pack", default=None, help="figure_style pack file (default = public default)")
    a = ap.parse_args()
    pack = load_pack(a.pack) if a.pack else None
    if a.dump:
        print(json.dumps(resolve_rcparams(pack), ensure_ascii=False, indent=2))
        return 0
    ap.error("nothing to do: pass --dump (apply() is a library call)")


if __name__ == "__main__":
    raise SystemExit(main())
