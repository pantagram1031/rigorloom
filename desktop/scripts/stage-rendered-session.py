"""Put a session on disk that already HAS its rendered PDF, and say so loudly.

WHY THIS EXISTS, and what it does and does not claim.

`document/pageGeometry` reads text positions out of a PDF that Hancom laid out.
The only way to get one from an HWPX at runtime is `document/renderPrepare`,
which drives Hancom over COM — and on this machine that call does not return a
PDF. It is not broken in an interesting way: a Hancom instance is already
running, and the Runtime's rule 2 is that it refuses (`com_busy`) rather than
terminating somebody else's session. So a smoke that waits for a live convert
measures a queue, not a feature.

The substitution is the one `runtime/README.md` already names for everything
around the convert step: a PREBUILT PDF stands in for the conversion. What makes
it evidence rather than staging is where that PDF comes from —
`tests/corpus/forms/render/<slug>.pdf` is the output of
`engine/scripts/com_backend.py convert --file converted/<slug>.hwpx --to
render/<slug>.pdf`, run against the very HWPX this session is opened from,
under Hancom 13.0.0.2986, and recorded with its provenance in
`docs/research/xc1-conversion-bench.md` §4. It is a real Hancom rendering of
these exact bytes. The only thing substituted is WHEN Hancom ran.

Nothing here is invented and nothing here is drawn by hand: no rect, no address,
no mapping. The Runtime reads the PDF itself and answers for itself; this script
only puts the file where `renderPrepare` would have put it, writes the same meta
record `renderPrepare` writes, and stamps `producedBy` with the truth so the
substitution is visible in the app's own source line rather than hidden in a
harness.

    python desktop/scripts/stage-rendered-session.py --root R --hwpx A --pdf B

Prints the sessionId on stdout. Exit 0 staged, 2 could not.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

PRODUCED_BY = (
    "tests/corpus/forms/render — engine/scripts/com_backend.py convert under "
    "Hancom 13.0.0.2986 (xc1-conversion-bench §4), substituted for a live "
    "document/renderPrepare because this machine refuses com_busy"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--hwpx", required=True)
    parser.add_argument("--pdf", required=True)
    args = parser.parse_args()

    hwpx, pdf = Path(args.hwpx), Path(args.pdf)
    if not hwpx.is_file():
        print(f"no such form: {hwpx}", file=sys.stderr)
        return 2
    if not pdf.is_file():
        print(f"no such render: {pdf}", file=sys.stderr)
        return 2

    from rt_core import RuntimeCore
    from rt_session import sha256_file
    import rt_convert

    core = RuntimeCore(args.root)
    session_id = core.open_path(str(hwpx.resolve()))["sessionId"]
    session = core.store.get(session_id)
    session.ensure_dirs()

    # Exactly where rt_convert puts one, so `existing_pdf` finds it by its own
    # rules — including the source-hash binding, which is the check that stops
    # one document's pages being served as another's.
    target = session.dir / "derived" / "source.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, target)
    digest, size = sha256_file(target)
    rt_convert._write_meta(session, {
        "path": "derived/source.pdf",
        "sha256": digest,
        "bytes": size,
        "producedBy": PRODUCED_BY,
        "producedUtc": "2026-08-06T23:05:53Z",
        "sourceSha256": session.meta["sourceSha256"],
    })
    print(session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
