# HWP/HWPX platform and evidence matrix

Checked 2026-08-09 against the official/primary sources below. This matrix is
a routing boundary, not a parity claim: **supported** means that a product
documents the operation, not that it matches Hancom layout. **Unknown** is not
the same as unsupported. A capability probe never creates proof; only a
successful, artifact-hash-bound terminal receipt can create an evidence grade.

## Boundary vocabulary

- **Supported**: an authoritative source documents the operation and this
  skill has an executable route for the stated scope. It is not a claim of
  Hancom layout parity.
- **Partial**: a documented or reproducible subset is usable, but format,
  equation, layout, licensing, or automation limits require an advisory or
  structural-only route.
- **Unsupported**: an authoritative source explicitly refuses or does not
  provide the requested operation; the skill must not silently substitute a
  different backend.
- **Unknown/not-listed**: the checked sources do not establish current support
  for the requested scope. This is an evidence gap, not proof of impossibility.

## Executable receipt backends

These closed IDs are shared with `engine/scripts/document_evidence.py` and are
the only runtime backends that may appear in `output/proof/backend/receipt.json`:

| ID | Route | Evidence ceiling | Automatic proof rule |
|---|---|---|---|
| `xml_only` | Rigorloom byte-preserving HWPX/XML assembly | `structural_only` → `none` | XML success does not imply a render or Hancom proof. |
| `native_hancom_windows` | Windows Hancom desktop through COM | `native_render` → `hancom` | Requires actual COM execution and matching HWPX/PDF bytes; `hancom_com: true` alone is informational. |
| `oss_preview_libreoffice` | Named LibreOffice/H2Orestart preview | `advisory_render` → `advisory` | Requires a successful equation-safe runtime and matching HWPX/PDF bytes; no general parity claim. |
| `oss_preview_rhwp` | Pinned `rhwp` diagnostic SVG preview | `diagnostic_render` → `experimental-rhwp` | Requires successful named execution and a current HWPX/SVG binding; never a submission grade. |
| `certified_renderer` | Explicitly configured renderer with the existing certificate ladder | `certified_render` → `certified` | Requires certificate eligibility plus successful matching runtime bytes; HMAC/certificate semantics remain `render_cert`. |
| `none` | No renderer, refusal, or unknown route | `none` | Fail closed. |

Evidence classes and legacy grades are deliberately closed: `structural_only`
(`none`), `diagnostic_render` (`experimental-rhwp`), `advisory_render`
(`advisory`), `certified_render` (`certified`), and `native_render`
(`hancom`). Failure, refusal, not-run, missing output, or hash drift derives
`none`. For advisory/certified/diagnostic receipts, an attached quality result
must remain `passed`; a native receipt keeps its `hancom` renderer provenance
when the bounded glyph checker is `unknown` or `not_applicable` (for example,
an uninspectable Type3 font), and downgrades only on confirmed `failed`
quality. This provenance is not a readability or Hancom-parity certification;
Stage 6 still enforces convergence, deterministic layout/style HARDs, and
artifact hashes.

Receipt artifact roles are closed as well: `source_form`, `assembled_hwpx`,
`rendered_pdf`, and `diagnostic_svg`. Successful structural assembly records
exit code `0` but remains grade `none` until an executed renderer supplies a
matching render artifact.

## Product/support boundaries

| Platform/tool | What is supported or documented | What is not proven here | Routing decision |
|---|---|---|---|
| Windows Hancom desktop | Native HWP/HWPX editing, conversion and PDF rendering; COM automation is the Windows path used by this skill. | A probe or installed application is not an execution receipt; license/EULA and version-specific fidelity still require the operator host. | Use `native_hancom_windows` only after successful COM execution and hash binding. |
| Hancom desktop on macOS | The official desktop support surface lists macOS products and interactive HWP/HWPX/PDF use. | Official macOS Automation/COM support is explicitly unavailable; no unattended automation contract is claimed. | `native_hancom_mac_ui` is a human/UI route only, not an executable proof backend. |
| Hancom desktop on Linux | No current native Linux desktop product/installer was listed in the checked official surface. | This does not prove that every commercial/server offering is impossible. | Unknown/not-listed; do not silently fall back to a native route. |
| Hancom Web Hwp / WebHWP | Official browser/server documentation exposes HWP/HWPX editing and save/conversion APIs. | It is proprietary, account/service-dependent, and its browser/server API is not desktop Automation. | `web_hancom` requires a future explicit adapter and receipt; unknown/refused today. |
| Hancom Docs Converter / HWP SDK | Vendor documentation advertises HWP/HWPX conversion and manipulation, including PDF/HTML. | Commercial purchase/inquiry, deployment, licensing, version, and local CLI parity are not established. | Do not auto-install or claim parity; use a future certified adapter only. |
| LibreOffice + H2Orestart | Cross-platform import/edit and PDF conversion can work for simple documents. | Upstream HWP filter warns newer HWP formats may silently corrupt; HWPX preservation/render parity is not proven; equations and complex layout have measured failures. | `oss_preview_libreoffice` is advisory only and must fail closed on unsupported equations/failed runtime. |
| `pyhwp` | AGPL parser/extractor for HWP v5-era input. | No supported writer or HWPX editing path; old/experimental ODT conversion does not establish document fidelity. | Parser-only; not a render/edit backend. |
| `hwplib` / `hwpxlib` | Apache-2 Java readers/writers provide structural HWP/HWPX operations. | No renderer/PDF proof and no broad Hancom parity certification. | Structural conversion quorum only; not an evidence backend. |
| `rhwp` | MIT open-source HWP/HWPX read/write/conversion and SVG diagnostics. | Upstream claims and small fixture probes do not establish universal fidelity; complex layout/PDF performance remain below the release ceiling. | `oss_preview_rhwp` is diagnostic and hard-blocked from submission. |
| T86 `hwp_diagnostic_candidate.py` | Explicit, pinned `rhwp export-hwpx` candidate under `work/stage-0/scratch/hwp-diagnostic`; no automatic discovery. | It is an independent diagnostic oracle with comparison `unknown`, render `not_run`, and proof `none`; the quarantined receipt is not an executable evidence backend. | Keep it outside `output/proof/backend/receipt.json`, `output/form_copy.hwpx`, Stage 0, and `new_report --ingress-receipt`; no pyhwp or LibreOffice fallback. |
| T87 `hwp_java_diagnostic_candidate.py` | Explicit Java launcher pin plus one fat JAR matching the shipped hwp2hwpx/hwplib/hwpxlib lock; fixed source bridge; bounded quarantine only. | Launcher rehash does not bind the surrounding JRE. JAR execution, package reopen, and structural counts do not prove independent semantic, page, native-Hancom, render, or submission parity. | Keep `runtime_binding=launcher_rehashed_runtime_unbound`, comparison `unknown`, render `not_run`, proof `none`; never feed the Java candidate/receipt to T85, Stage 0, backend evidence, or `new_report`. |
| T88 `hwp_semantic_oracle.py` | Receipt-only bounded content/object agreement between one allowlisted T86 `rhwp` candidate and one T87 lock-bound Java candidate; T85/T79 public verifiers run over captured bytes before the OPF-spine comparison. | Converter agreement is not source fidelity, native Hancom behavior, page/render parity, or submission evidence; current input drift or independent grammar refusal blocks. | Keep `paired_converter_bounded_content_object_v1`, the closed compared/not-compared coverage, `source_fidelity=not_established`, `runtime_binding=launcher_rehashed_runtime_unbound` on the Java leg, render `not_run`, proof `none`, submission false; no ingress/Stage 0/canonical/new_report use; `syhwp` deferred. |
| T89 `hwp_source_coverage.py` | Receipt-only bounded BodyText record/control inventory under the pre-created `work/stage-0/scratch/hwp-source-coverage` leaf; T85 preflight and exact HWP record/deflate checks run in memory. | BodyText coverage is not source fidelity, DocInfo semantic coverage, conversion parity, native execution, page/render parity, or submission evidence; no v1 eligible outcome. | Keep `rigorloom/hwp-source-coverage/v1`, `comparison:unknown`, `render:not_run`, `proof_grade:none`, and `submission_grade:false`; exit 3 for analyzed ineligible/unknown and refusal, never route the receipt to ingress, Stage 0, canonical output, rendering, or submission; syhwp is only a pinned target, not executed. |
| Poppler / MuPDF / Ghostscript | Cross-platform PDF parsing, rasterization, and PDF conversion utilities. | They do not edit or understand HWP/HWPX semantics. | `pdf_only` is a downstream PDF utility/refusal, never an HWP proof route. |

## Source register

- [Hancom HWP 5.0 binary format revision 1.3](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf)
- [Microsoft Compound Binary File header](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/05060311-bfce-4b12-874d-71fd4ce63aea) and [chain validation rules](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/9d33df18-7aee-4065-9121-4eabe41c29d4)
- [Hancom current product status (Windows/macOS product rows)](https://www.hancom.com/support/csCenter/prdStatus)
- [Hancom HWP Automation product/licence boundary](https://developer.hancom.com/hwpautomation)
- [Hancom macOS Automation explicitly unsupported](https://forum.developer.hancom.com/t/topic/2915)
- [Hancom WebHWP deployment structure](https://developer.hancom.com/en-us/webhwp/devguide/structure) and [save API](https://developer.hancom.com/webhwp/devguide/hwpctrl/methods/saveas)
- [Hancom Docs Converter overview](https://developer.hancom.com/docsconverter/overview) and [conversion modules](https://developer.hancom.com/docsconverter/guide/api/module)
- [Hancom HWP SDK](https://download.hancom.com/product/sdk/hwpSdk)
- [LibreOffice HWP filter warning (silent corruption for newer formats)](https://github.com/LibreOffice/core/blob/master/hwpfilter/README.md)
- [`pyhwp` repository](https://github.com/mete0r/pyhwp) and [PyPI package](https://pypi.org/project/pyhwp/)
- [`hwp2hwpx`](https://github.com/neolord0/hwp2hwpx), [`hwplib`](https://github.com/neolord0/hwplib), and [`hwpxlib`](https://github.com/neolord0/hwpxlib); T87 pins exact commits and an audited third-party fat-JAR mapping in its research note
- [`rhwp` English README](https://github.com/edwardkim/rhwp/blob/main/README_EN.md)
- [`rhwp` v0.8.2 source tree](https://github.com/edwardkim/rhwp/tree/v0.8.2), [release](https://github.com/edwardkim/rhwp/releases/tag/v0.8.2), and [CLI usage](https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md#cli-usage)
- [Poppler](https://poppler.freedesktop.org/), [MuPDF](https://mupdf.com/), and [Ghostscript](https://www.ghostscript.com/)

The source register above is the link list for the checked claims and dates;
the measured limitations are evidence context, not an automatic support
promise.
