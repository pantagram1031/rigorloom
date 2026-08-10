# T91 HWPX equation diagnostic

T91 is a receipt-only structural inventory with schema
`rigorloom/hwp-equation-diagnostic/v1`. It addresses two concrete false-green
paths: XML-prefix byte searches could miss a real equation or match a comment,
and conversion parity could erase meaning-bearing HwpEqn whitespace. It does not
claim to understand HwpEqn or to render an equation.

The scanner captures the source once, applies the existing strict HWPX
physical/OCF/OPF validator, then reads sections only in OPF-spine order. An
equation is the expanded QName
`{http://www.hancom.co.kr/hwpml/2011/paragraph}equation`, independent of prefix.
It must be a direct child of an official run and contain exactly one direct,
nonempty, text-only official script. Ambiguous, foreign, nested, missing, or
duplicate script grammar refuses.

The conversion-parity gate captures source and assembled bytes once, applies
this envelope check and exact NFC script comparison to those private snapshots,
binds a manifest-backed extraction to its recorded source SHA-256, compares an
opaque per-section semantic sequence in resolved OPF-spine order, then rebinds
both live inputs before returning. It therefore cannot hide a removed second
script behind the extractor's first-script view, accept a reversed spine whose
sections differ only by equation script, or mix evidence from different
generations of a file.

For the raw-HWP conversion mode, the parity gate also captures the HWP source,
runs the T85 CFB/FileHeader/security preflight before any adapter, then inspects
that private snapshot through the same serialized, bounded, privacy-safe COM
envelope. The envelope performs the exact tasklist precheck, never kills a
stale process, waits for natural shutdown, and the gate rebinds the live HWP
before returning. This does not turn conversion into render or semantic proof;
it only binds the recorded conversion comparison to one source generation.

Receipt-only publication treats the receipt as the last persistent state. The
final source and root checks run first; then the one-link receipt is re-read,
schema-validated, and identity-bound immediately before the owner token is
removed. Verification uses the same receipt-last ordering. This prevents a
same-inode overwrite during the final source/root callbacks from returning an
analyzed result for a receipt that is already invalid on disk.

The receipt publishes only source format/size/SHA-256, scanner identity,
section/equation counts, and closed evidence states. It publishes no equation
text, per-script hashes, IDs, member names, paths, command line, stdout, or
stderr. Even a structurally analyzed receipt keeps
`script_semantics:not_scanned`, execution/native/render `not_run`, comparison
`unknown`, proof `none`, and submission false. All analysis/refusal commands
exit 3; only help exits 0 and argparse usage exits 2.

The route is deliberately separate from the legacy internal rhwp proof helper.
T91 removes that helper from automatic backend selection because its historical
receipt/process surface is not the public quarantine contract.
LibreOffice/H2Orestart remains unavailable for equation-bearing HWPX. A future
operator-supplied rhwp SVG run may be diagnostic execution only; a Windows
Hancom run may establish native execution and artifact binding only. Neither
establishes semantic equality or submission proof without a separate native
render comparison.

Primary format references checked 2026-08-11:

- Hancom OWPML/HWPX format page:
  https://swlab.hancom.co.kr/support/downloadCenter/hwpOwpml
- Hancom HWP 5.0 equation record and script references:
  https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf
  and
  https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_%EC%88%98%EC%8B%9D_revision1.2.pdf

The format publication requires attribution and disclaims accuracy; these
references define the parsing boundary, not a Hancom parity claim.
