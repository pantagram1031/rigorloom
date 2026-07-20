# Linux HWP/HWPX tooling: interoperability and rendering fidelity

**Research date:** 2026-07-19 through 2026-07-20<br>
**Target release:** rigorloom v0.15<br>
**Test hosts:** Windows 11 with WSL2 (Ubuntu 24.04.2 LTS, kernel `5.15.167.4-microsoft-standard-WSL2`) and Pantadex on OCI `VM.Standard.A1.Flex` (ARM64, 4 OCPUs, 24 GiB, Ubuntu 24.04.4 LTS)<br>
**Decision status:** enough evidence for a v0.15 architecture decision; not enough evidence to replace Hancom as the release-fidelity oracle

## Decision

Pure Linux replacements now exist for **editing, HWP/HWPX conversion, and preview rendering**. They do not yet replace Hancom for release-fidelity rendering. For v0.15, keep rigorloom's direct, loss-preserving HWPX XML backend as the canonical editor; add `rhwp` 0.7.19 behind an experimental feature flag for `.hwp` ingress, HWP/HWPX editing, conversion, structural diagnostics, and fast SVG previews; and evaluate the independent Java `hwplib` + `hwp2hwpx` + `hwpxlib` path as a conversion quorum. Windows Hancom COM can therefore become optional for routine content operations, but should remain the final render/acceptance oracle until a corpus proves otherwise. Require `--verify`, `--verify-pages`, preservation of the original input, and a Hancom-rendered acceptance corpus before accepting a converted file.

Do not make LibreOffice plus H2Orestart the canonical renderer. It is useful as a best-effort Linux PDF path, but the tested three-page document still had roughly 645 px worst-case word-anchor displacement at 96 dpi after the equation-image workaround. The workaround restored conversion; it did not restore layout fidelity. `rhwp` is also not ready to be the final renderer: its exact reproduction of the existing calibration reached 676.33 px render-tree displacement, and its complex PDF export did not finish within four minutes.

Keep the Java family as the independent second route. On Pantadex ARM64, `hwplib` 1.1.10, `hwpxlib` 1.0.9, and `hwp2hwpx` 1.0.0 all built in 53.89 seconds in a disposable JDK 8 container after three scratch-only compatibility changes. Both HWP-to-HWPX conversions and both HWPX rewrites reopened in Hancom with zero word displacement and zero changed raster channels at 300 dpi. That is promising but still only a two-document synthetic corpus.

Do not make Hancom-under-emulation a v0.15 dependency. Hangover 11.9 on Pantadex successfully ran an x86_64 Windows COM client and activated three `IDispatch` Automation classes, so COM emulation is technically possible without KVM. The warm container peaked at 92,499,968 bytes and completed in 4.35 seconds, so capacity is not the blocker. The custom image was 1.095 GB, one fresh-prefix repeat stalled, and an actual licensed Hancom installer was unavailable; Hancom compatibility and licensing therefore remain untested.

Evaluate Hancom's paid Linux/server offering only after the operator approves vendor contact or a purchase. No public, free official Linux desktop installer was found, so none was installed.

## Feasibility matrix

Legend: **Yes** means the capability was exercised or an explicit API exists; **partial** means import/extraction or experimental behavior only; **no** means no viable path was found; **unverified** means vendor documentation claims it but no eligible installer/license was available.

| Toolchain | Edit `.hwp` | Edit `.hwpx` | Convert | Linux rendering fidelity | Integration effort | Evidence and disposition |
|---|---:|---:|---|---|---|---|
| rigorloom direct HWPX backend | No | **Yes** | No binary-HWP conversion | None by itself | Low; already integrated | Keep as canonical editor. Section XML is rewritten without using an office suite. |
| Windows Hancom COM reference | **Yes** | **Yes** | **Yes** | **Reference** | Existing Windows-side dependency | Keep as release oracle, not a Linux solution. No Windows software was installed during this research. |
| `rhwp` 0.7.19 | **Yes, experimental** | **Yes, experimental** | **Yes:** HWP to HWPX; HWP/HWPX to HWP; SVG/PDF | Low on complex calibration; useful diagnostic SVG | Medium | Minimal HWP-to-HWPX and HWP reserialization were Hancom-pixel-identical. Complex layout and PDF performance remain blockers. Recommended experimental ingress/diagnostics. |
| `@rhwp/core` 0.7.19 on Pantadex ARM64 | **Yes, experimental** | **Yes, experimental** | **Yes:** HWP/HWPX cross-export; SVG | Same renderer ceiling as `rhwp`; font-sensitive | Low-medium; Node/WASM, 34 MB installed | All four fixtures edited, cross-exported, and reopened. Three-page SVG preview completed in 2.24 s at 318 MB peak RSS. No x86 emulation needed. |
| `hwplib` 1.1.10 + `hwp2hwpx` 1.0.0 + `hwpxlib` 1.0.9 | **Yes** through `hwplib` | **Yes** through `hwpxlib` | **Yes:** HWP to HWPX; HWP/HWPX rewrite | None | Medium-high; JVM and three build compatibility changes | Pantadex ARM64 build and read/write/convert probes succeeded. Four Hancom reference renders were pixel-identical at 300 dpi. Advance as independent conversion quorum. |
| Hangover 11.9 + FEX/Box64 on ARM64 | Only if the Windows application works | Only if the Windows application works | Application-dependent | **Unverified for Hancom** | High; 1.095 GB image plus Wine lifecycle work | Generic x86_64 COM/`IDispatch` succeeded at 92.5 MB peak container memory. One fresh prefix stalled; no Hancom installer/license was available. Do not make production-critical. |
| LibreOffice 26.2.4 full archive + H2Orestart 0.7.13 | Import/edit through Writer only; not preservation-safe | Import/edit through Writer only; not preservation-safe | **Yes**, when import succeeds | Low on complex calibration | Medium | Minimal equations worked. Complex native-equation document still failed; image substitution converted but max displacement was 645.08 px at 96 dpi. Advisory fallback only. |
| Ubuntu LibreOffice 24.2.7 + H2Orestart 0.7.13, without Math | Partial import | Partial import | Text-only/simple documents | Not measurable for native equations because conversion fails | Low | Minimal text converted; both `.hwp` and `.hwpx` equations failed with `Unspecified Application Error`. |
| Hancom Linux/server viewer or HWP SDK | **Unverified** | **Unverified** | Vendor claims HWP/HWPX to PDF/HTML and document manipulation | Potentially highest Linux path, unmeasured | High: commercial evaluation and service integration | Public pages require purchase/inquiry; no free eligible installer or public CLI contract found. |
| Hancom Docs web | Interactive | Interactive | Service-dependent | Likely Hancom engine, unmeasured | High for automation; account/upload dependency | Not a headless local toolchain. No test because it requires an account and uploads documents. |
| `pyhwp` 0.1b15 | No; read/extract only | No | Experimental HWP-to-ODT | None | Medium, with old Python assumptions | Reads version 5.1.1.0; text extraction lost table cell/equation content; ODT conversion failed RelaxNG validation. Reject for v0.15. |
| OpenHWP commit `c605402f` | HWP read; no HWP write | Library advertises HWPX XML read/write | No finished end-to-end HWP-to-HWPX command | None | High | 558 workspace tests passed, but shipped sample fixtures are omitted and the local extraction probe lost content. Watch, do not integrate. |
| `libhwp` 0.2.0 | No; reader only | No | No | None | Low to try, high to repair | Both sanitized HWP files panicked in the Rust parser. Reject. |
| `unhwp` 0.5.3 | No; extraction only | No | Text/Markdown extraction | None | Low | Best tested extractor for table text, but equations were omitted in both formats. Useful only for indexing/search. |

## Ranked v0.15 recommendation

### 1. Canonical path: direct HWPX editing plus Hancom release oracle

Keep the current architecture:

1. Edit HWPX directly and preserve unsupported XML.
2. Run structural/content checks on Linux.
3. Produce the release PDF and final HWP/HWPX acceptance render with Windows Hancom COM.

This is the only tested path that combines controlled editing with reference rendering. Linux-only rendering should remain an advisory signal in v0.15, not a release gate.

### 2. Experimental `.hwp` ingress: pin `rhwp` 0.7.19

Use `rhwp export-hwpx INPUT.hwp OUTPUT.hwpx --verify --verify-pages`, then feed the HWPX into the existing backend. On both one-page sanitized fixtures, `rhwp` 0.7.18 and 0.7.19 reported one page and no IR difference; Hancom reopened the generated HWPX files and produced PDFs with zero word-anchor displacement and a zero changed-pixel ratio at 300 dpi.

Pantadex does not need an ARM64 CLI release for this path. The `@rhwp/core` 0.7.19 WebAssembly package ran directly under ARM64 Node 20, edited all four fixtures, exported both native and cross-format outputs, reopened every output, and rendered SVG. The four-document probe took 1.98 seconds with 304,052 KiB peak RSS. The three-page sanitized surrogate took 2.24 seconds with 318,364 KiB peak RSS; individual SVG calls took 86.54, 74.48, and 22.87 ms. Minimal equation SVG hashes were identical to the earlier x86_64 outputs. Complex SVG hashes differed from the prior CLI outputs, so server font/measurement configuration must be pinned and this remains a preview path.

The result is not yet a general round-trip guarantee. Before enabling it by default, build a sanitized acceptance corpus covering multi-section documents, nested tables, headers/footers, footnotes/endnotes, floating shapes, images, equations, fields, tracked objects, and legacy HWP 5 revisions. A failure must preserve the original `.hwp` and stop canonical editing.

### 3. Independent conversion quorum: evaluate the pure-Java family

`hwplib` has an active HWP 5 reader/writer API and a long history of targeted format fixes. Pair it with [`hwp2hwpx`](https://github.com/neolord0/hwp2hwpx) and [`hwpxlib`](https://github.com/neolord0/hwpxlib) for a second, pure-Java HWP-to-HWPX route. Current commits `d9e073d` (`hwplib`), `50ae71b` (`hwp2hwpx`), and `7c159a6` (`hwpxlib`) built and ran natively on Pantadex ARM64 in Docker. `hwplib` preserved extracted text in both HWP rewrites; `hwp2hwpx` preserved the `<hp:equation>` and `x^2 + y^2 = 1` script; and `hwpxlib` rewrote both HWPX fixtures. All four Java outputs reopened in Hancom with 0.0 px maximum word displacement and 0 changed raster channels out of 26,077,200 at 300 dpi.

Use the Java path as an independent parser/writer/conversion oracle, not as the renderer. Its build needs modernization: Java 17 rejected the removed `javax.xml.bind` API, all three projects still declare Java source level 7, and `hwplib` contains an unused `com.sun.jmx.snmp` import. The successful scratch build used JDK 8, changed source/target 7 to 8, and removed that one unused import. No patches were made to the repository under test.

### 4. Linux previews: `rhwp` SVG first, LibreOffice/H2Orestart second

`rhwp export-svg` rendered the three-page surrogate in 1.57 seconds and gives inspectable geometry, making it useful for fast diagnostics. Its PDF export is not currently dependable on complex documents: 0.7.19 timed out after 240 seconds without font paths and after 180 seconds with HCR Batang, HCR Dotum, and HancomEQN paths.

LibreOffice/H2Orestart can remain an explicitly non-authoritative PDF fallback. Preflight it for a complete LibreOffice install including Math, and fail with a specific message when H2Orestart hits unsupported HWPX metadata or native equations. Never replace equations in the canonical document; create a separately named render surrogate and record that equation semantics were lost.

### 5. Commercial option: request a Hancom Linux/server evaluation only with approval

Hancom's public product pages describe server/Linux document-viewing and conversion products, and the HWP SDK page advertises HWPX creation/manipulation and HWP/HWPX conversion. The pages route to purchase or introduction inquiries. No public current version, price, free Linux installer, or guaranteed standalone command-line interface was found. This path may be the only realistic way to obtain Hancom-grade Linux rendering, but it is a procurement decision rather than an open-source integration task.

### 6. Do not ship Hancom under Hangover yet

The Pantadex probe disproves the claim that ARM64 cannot run Windows COM at all: Hangover/FEX successfully executed a PE32+ x86_64 client and activated `Shell.Application`, `WScript.Shell`, and `Scripting.Dictionary` through `IDispatch`. However, that proves Wine OLE/COM plumbing, not Hancom Office. An actual test would require an authorized Hancom Windows installer, a compatible license/EULA, silent-install parameters, and then a real `HwpFrame.HwpObject` activation/render test. Until the operator supplies those, this route is a reversible research option rather than a v0.15 recommendation.

## Track A: rendering fidelity

### Important correction to the 676 px baseline

The known `676.33 px` result is reproducible, but it is **not** a LibreOffice-versus-Hancom PDF pixel measurement. It is `rhwp render-diff` comparing render-tree bounding boxes between a line-segment-stripped HWPX and the Hancom-saved HWPX. The command reports 3 versus 3 pages, structural mismatch on two pages, and a maximum displacement of 676.33 px on page 1:

```text
페이지 수: A=3 B=3
최대 변위: 676.33 px (page 1)
임계 초과 페이지: 3 / 구조 불일치 페이지: 2 (임계 1.00px)
page 0: max=637.33 mean=132.51 nodes=136/122 [STRUCT]
         TextLine: 41 -> 37; TextRun: 81 -> 71
page 1: max=676.33 mean=119.41 nodes=203/221 [STRUCT]
         TextLine: 44 -> 52; TextRun: 110 -> 120
status: STRUCT_MISMATCH
```

The LibreOffice measurements below use a separate, documented metric: unique-word center displacement after normalizing candidate PDF coordinates to the Hancom PDF page size. Values from the two metrics must not be compared as if they were identical.

### Minimal H2Orestart equation failure

The sanitized minimal document contains one `<hp:equation>` with script `x^2 + y^2 = 1`.

| Input | Ubuntu LO 24.2.7 + distro H2O 0.7.13 | Official full LO 26.2.4 + upstream H2O 0.7.13 |
|---|---|---|
| `minimal-text.hwpx` | Success, PDF 17,361 bytes | Success, PDF 18,655 bytes |
| `minimal-text.hwp` | Success, PDF 17,361 bytes | Success, PDF 18,655 bytes |
| `minimal-equation.hwpx` | Exit 1, `Unspecified Application Error` | Success, PDF 28,364 bytes |
| `minimal-equation.hwp` | Exit 1, `Unspecified Application Error` | Success, PDF 28,364 bytes |

The Ubuntu install has `libreoffice-core` and `libreoffice-writer` but not `libreoffice-math`. A parser-only Java probe against the same H2Orestart JAR succeeds:

```text
detect=true
version=5110
sections=1
```

H2Orestart's `ConvEquation.java` constructs the equation as a UNO `com.sun.star.text.TextEmbeddedObject` and assigns LibreOffice Math class ID `078B7ABA-54FC-457F-8551-6147e776a997`. The evidence therefore places the minimal LO 24 failure after HWPX parsing, at or after embedded Math-object creation. The full LO 26 archive includes the component and succeeds. This comparison is operationally useful but not a controlled version-only benchmark because both LibreOffice version and package completeness changed.

### Upstream status

The tested distro package and the newest upstream release are both H2Orestart 0.7.13. The upstream `.oxt` SHA-256 was `726230215dabe450bd617f9acac52376fd76f57c77158bd03b3ef9fe0c7e64fd`, matching the downloaded release asset. Installing that exact upstream release in a fresh LO 24 user profile did not change the minimal-equation failure.

Upstream issue [#16](https://github.com/ebandal/H2Orestart/issues/16) describes an older equation-related null failure and was closed after a 0.5.9 fix. It does not explain this minimal case: the current parser succeeds, and a complete LibreOffice stack converts the document. No open issue matching the current missing-Math/package behavior was found. H2Orestart remains active; [0.7.13 was released on 2026-06-27](https://github.com/ebandal/H2Orestart/releases/tag/v0.7.13).

The full three-page HWPX exposed a separate H2Orestart parser defect before equations were reached. `HwpRecord_BorderFill.java:147` dereferences optional `threeD`, `shadow`, and related attributes without defaults. A throwaway compatibility copy that added `threeD="0"`, `shadow="0"`, `centerLine="NONE"`, and `breakCellSeparateLine="0"` passed the parser. That patch must not be applied to the canonical file merely to accommodate an importer.

### Equation-as-image workaround

The proof-of-concept replaces each equation control with a transparent PNG sized to the original control box. It writes a separate HWPX, records the number of replacements, and explicitly marks equation semantics as lost.

Minimal result:

| Candidate vs Hancom reference | Matched unique words | Max displacement at 300 dpi | Median |
|---|---:|---:|---:|
| LO 26 native equation | 8 | 64.39 px | 22.21 px |
| LO 26 equation image | 8 | 64.39 px | 22.21 px |
| LO 24 equation image | 8 | 99.76 px | 32.60 px |

The image workaround restored LO 24 conversion but did not improve same-version LO 26 layout at all.

Full three-page result, after producing a render surrogate, adding H2Orestart's missing BorderFill defaults, and replacing eight equations:

| Stack | PDF result | Pages | Word matches | Max displacement at 96 dpi | p95 | Median |
|---|---|---:|---:|---:|---:|---:|
| LO 24 + images | Success, 312,005 bytes | 3 | 467 | 655.04 px | 439.46 px | 168.94 px |
| LO 26 + images | Success, 309,378 bytes | 3 | 481 | 645.08 px | 463.12 px | 168.35 px |
| LO 24 + native equations | Failure | — | — | — | — | — |
| LO 26 + native equations | Failure | — | — | — | — | — |

The best measured workaround is therefore **image substitution for availability only**. It restores PDF generation and page count, but worst-case positioning remains unacceptable and native equation editability/accessibility is lost. Because the native complex file produces no PDF, no same-document native-versus-image fidelity improvement can be claimed.

Text-only controls also show that LO 26 is directionally better but not faithful: max displacement fell from 122.17 px on LO 24 to 82.30 px on LO 26 at 300 dpi, while median displacement fell from 32.60 to 20.89 px.

## Track B: binary HWP 5 support

### `rhwp`

`rhwp` is active: 0.7.18 was the pinned experimental release and [0.7.19 was released on 2026-07-17](https://github.com/edwardkim/rhwp/releases/tag/v0.7.19). The repository was updated during this research window. The downloaded release hashes were:

```text
v0.7.18  70101216a84044ea2492d45269b8ac1fd3ec6b7661506238fc8b0f0c43a8b6e1
v0.7.19  fe3dc818a44f2bc4d4a001311514ed399d46a1e752b3df0d6e9e2f2ac8058402
```

Capabilities exercised:

- HWP and HWPX parsing, including the minimal equation.
- HWP-to-HWPX with `--verify --verify-pages` on both fixtures.
- HWP-to-HWP reserialization with `convert ... --verify --verify-pages` on both fixtures.
- SVG export of a complex three-page surrogate.
- PDF export of one-page fixtures.
- IR and render-tree difference diagnostics.

The HWP-to-HWPX files and reserialized HWP files all reopened in Hancom. Each resulting Hancom PDF had zero unique-word displacement and zero changed raster channels against its original reference at 300 dpi. This is strong evidence for the chosen fixtures, not evidence of universal losslessness.

The realistic ceiling for v0.15 is experimental import/conversion and diagnostic rendering. The current [English README](https://github.com/edwardkim/rhwp/blob/main/README_EN.md) describes a broad read/write and rendering foundation, but the measured complex-layout displacement and PDF timeouts rule out a final-fidelity renderer today.

### `hwplib`

Current source commit `d9e073d6899d947f8f583492e00a5e1062381d7e` dates to 2026-07-13, and its `pom.xml` reports version 1.1.10. The [project](https://github.com/neolord0/hwplib) provides HWPReader, HWPWriter, text extraction, and editing examples under Apache-2.0.

Probe output (the extractor also prepended a spurious `aaaaa` marker to the first paragraph):

```text
minimal-text.hwp:
  input=16384 output=6144 sections=1 written=true
  text includes Synthetic..., Second paragraph..., Key Value alpha 1.25 beta 2.50

minimal-equation.hwp:
  input=14848 output=6144 sections=1 written=true
  text includes Synthetic HWPX equation probe, x^2 + y^2 = 1, End...

Hancom PDF comparison at 300 dpi:
  minimal-text:     16 unique words, max displacement 0.0 px, changed-channel ratio 0.0
  minimal-equation:  9 unique words, max displacement 0.0 px, changed-channel ratio 0.0
```

Build caveat: source level 7 fails on current JDKs; Java 17 also lacks the `javax.xml.bind` API used by `hwplib`. A WSL attempt became unresponsive during the Maven lifecycle. The independent Pantadex run resolved the ambiguity: after changing source/target 7 to 8 and removing the unused `com.sun.jmx.snmp.agent.SnmpUserDataFactory` import, JDK 8/Maven 3.9.16 completed `hwplib`, `hwpxlib`, and `hwp2hwpx` installs in 16.557, 12.657, and 5.872 seconds respectively. The entire disposable container invocation took 53.89 seconds. These were throwaway source-tree changes, not repository changes or proposed upstream fixes.

### `hwp2hwpx` and `hwpxlib`

The [`hwp2hwpx`](https://github.com/neolord0/hwp2hwpx) converter is pure Java and depends on the same maintainer's HWP and HWPX object models. Commit `50ae71bbaf98ec7a00192f72492d6a130a755ac1` from 2026-06-25 converted both sanitized HWP files to HWPX on Pantadex ARM64. Commit `7c159a6a3d7dc85c0eab6da2a32dd052403a052c` of [`hwpxlib`](https://github.com/neolord0/hwpxlib) rewrote both native HWPX fixtures. Every output passed `unzip -t` and reopened through the corresponding Java reader.

The HWP and HWPX text extractors use different control/newline conventions, so raw extracted strings were not a valid cross-format equality metric. Direct XML inspection confirmed that the converted equation retained `<hp:equation>` and `<hp:script>x^2 + y^2 = 1`. The stronger Hancom oracle then rendered all four outputs. Each had the original page count, 0.0 px maximum unique-word displacement, and a 0.0 changed-channel ratio at 300 dpi. This establishes a second viable HWP-to-HWPX path for the two fixtures; it does not establish broad format coverage.

### `pyhwp`

Tested `pyhwp` 0.1b15 with Python 3.12.3, `six` 1.17.0, and `lxml` 6.0.2 in a user-local virtual environment. The package omitted a required `six` dependency, so it was installed explicitly.

```text
$ hwp5proc version minimal-text.hwp
5.1.1.0

$ hwp5txt minimal-text.hwp
Synthetic HWP and HWPX conversion probe.
Second paragraph with 12345.
<표>

$ hwp5txt minimal-equation.hwp
Synthetic HWPX equation probe
End of synthetic probe.

$ hwp5odt --output /tmp/pyhwp-probe.odt minimal-text.hwp
exit=1 bytes=591
ValidationFailed: RelaxNG
```

The text extractor recognized a table marker but omitted its cell contents, omitted the equation, and emitted repeated undefined `UnderlineStyle` value 15 warnings. No HWP or HWPX write path exists. The [PyPI release](https://pypi.org/project/pyhwp/) remains a beta from 2015; current [repository](https://github.com/mete0r/pyhwp) master is commit `83239f0d3bdf438b2c9f7dcff455a6e841154a39` from 2023-04-10 and documents older Python support and experimental ODT conversion.

### Other open-source libraries

**OpenHWP.** Commit `c605402ffae2f241baab06c9010a68faf1415d63` from 2025-12-13 passed `cargo test --workspace` with 558 tests. The repository explains that copyrighted sample files are excluded. Its capability table says HWP read/no write and HWPX read/write, but the HWP-to-IR-to-HWPX example stops before a finished conversion/writer call. A local Rust probe parsed both minimal HWP files but extracted only a truncated prefix and lost most table/equation content. [Repository](https://github.com/openhwp/openhwp).

**libhwp.** PyPI 0.2.0 built locally for CPython 3.12, but both minimal files raised a Rust/PyO3 panic over unread record bytes (`46 vs 48` for text, `58 vs 60` for equation). It is a reader only and the latest public package dates to 2022. [PyPI](https://pypi.org/project/libhwp/).

**unhwp.** Version 0.5.3 parsed the text fixture and preserved its table well in Markdown, but prepended the same spurious `aaaaa` marker seen in another extractor and omitted equation content from both HWP and HWPX. It is a maintained extractor, not an editor, converter, or renderer. [Repository](https://github.com/iyulab/unhwp).

Two tested open-source convert-to-HWPX-then-edit routes are now worth advancing: `rhwp`, and the Java `hwplib` + `hwp2hwpx` + `hwpxlib` family. Both must remain gated by a representative Hancom corpus. The other surveyed libraries do not supply a verified end-to-end route today.

## Track C: official Hancom Linux offerings

Desk research used only public official pages:

- The [integrated document viewer](https://www.hancom.com/product/solution/officesolution/docViewer) advertises server-side document conversion/viewing and Linux support, with annual, perpetual, site, or service licensing handled by inquiry.
- [Hancom Docs Converter](https://developer.hancom.com/docsconverter/overview) documents a REST-style conversion service rather than a public local `soffice`-like executable. Its [conversion matrix](https://developer.hancom.com/docsconverter/guide/api/module) explicitly lists HWP/HWPX to PDF, PDF/A, HTML, JPG, PNG, text, and ODT, plus HWP to HWPX.
- The [HWP SDK](https://download.hancom.com/product/sdk/hwpSdk) advertises reading/manipulating HWPX and converting HWP/HWPX to PDF/HTML, but routes availability through purchase.
- [WebHWP's Linux deployment architecture](https://developer.hancom.com/en-us/webhwp/devguide/structure) and [`SaveAs`](https://developer.hancom.com/webhwp/devguide/hwpctrl/methods/saveas) API expose another official server/browser route capable of HWP, HWPX, and PDF output, but it is not a free local CLI replacement and its web API intentionally differs from desktop Automation.
- An [official developer-forum deployment answer](https://forum.developer.hancom.com/t/api/577) describes Linux/Docker deployment on CentOS 7, RHEL 8.6, and Ubuntu 20.x, but says the product must be purchased and exposes a service rather than documenting a free standalone converter.
- Hancom's [desktop support page](https://support.hancom.com/e17a839b-0b57-4a17-9527-5cc265bada0b) lists Windows/macOS desktop products; Hancom Docs is browser-based.

No free current official Linux desktop installer was found. No installer was downloaded or run, and no account was created, in accordance with the stop rule. Public pages did not provide a current Linux product version, offline/headless CLI syntax, price, or CI/redistribution terms.

## Pantadex deployment check: native Linux versus Windows COM emulation

Pantadex is an OCI `VM.Standard.A1.Flex` instance with four ARM64 Neoverse-N1 OCPUs, 24 GiB RAM, Ubuntu 24.04.4, Docker 29.5.3, and no `/dev/kvm`. [OCI's instance-launch documentation](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm) states that Windows images are not supported on A1/A2 shapes. A nested Windows VM is therefore not a realistic same-host option; the practical choices are native ARM64 code, user-mode x86_64 emulation, or a separate x86_64 Windows worker.

### Native ARM64 result

The native result is strong for data operations and preview throughput:

| Probe | Result | Wall time | Peak RSS |
|---|---|---:|---:|
| npm install `@rhwp/core@0.7.19 @napi-rs/canvas@1.0.2` | Success; 34 MB installed | 2.07 s | 124,296 KiB |
| Four HWP/HWPX parse-edit-render-cross-export-reopen cases | All succeeded; marker survived every native and cross-format export | 1.98 s | 304,052 KiB |
| Three-page sanitized SVG render | 3/3 pages; calls 86.54/74.48/22.87 ms | 2.24 s process total | 318,364 KiB |
| Java build (`hwplib`, `hwpxlib`, `hwp2hwpx`) | All three `BUILD SUCCESS` | 53.89 s container total | not measured at cgroup level |
| Java rewrite/convert/reopen | Six output routes succeeded | 1.71 s container total | not measured at cgroup level |

This removes the need to emulate COM for `.hwp` ingestion, `.hwp`/`.hwpx` editing, HWP-to-HWPX conversion, and SVG preview. It does **not** remove the font and layout problem: the complex ARM/WASM SVG bytes differed from the prior x86_64 CLI SVGs, and both are still below Hancom fidelity on the existing calibration.

### Hangover/FEX result

[`Hangover`](https://github.com/AndreRH/hangover) runs x86/x64 Windows applications on ARM64 Wine and uses [FEX](https://github.com/FEX-Emu/FEX) for x86_64 execution. [Release 11.9](https://github.com/AndreRH/hangover/releases/tag/hangover-11.9)'s Ubuntu 24.04 ARM64 archive was 287,129,600 bytes with GitHub-published SHA-256 `0c66e48800c03d32c3c22029b5053cef3d61376aedcf44eaddf82dce63e410dd`. A custom Ubuntu container containing Hangover, Xvfb, and a MinGW-built PE32+ test client was 1,094,718,945 bytes.

The resource-capped runtime used `--cpus=2 --memory=8g --pids-limit=512 --network=none`. The client initialized OLE and activated three Automation objects:

```text
host_arch=aarch64
wine_version=wine-11.9 (Hangover)
windows_pointer_bits=64 windows_processor_architecture=9
coinitialize_hr=0x00000000
progid=Shell.Application ... activated=true ... typeinfo_count=1
progid=WScript.Shell ... activated=true ... typeinfo_count=1
progid=Scripting.Dictionary ... activated=true ... typeinfo_count=1
activated_count=3
```

The warm run completed in 4.35 seconds. During an intentional 15-second hold, Docker reported 67.55 MiB current memory and the cgroup reported a 92,499,968-byte peak, with 57 processes. Cold Wine-prefix initialization took 17.10 to 20.22 seconds. One new-prefix retry stalled for more than two minutes before COM activation and the exact disposable container had to be stopped; the preserved warm prefix was repeatable.

Conclusion: generic COM emulation is **not too resource-exhausting** for Pantadex, but it is less deterministic and operationally much heavier than the native paths. It also does not prove that Hancom Office installs, licenses, starts headlessly, renders correctly, or permits this deployment. No Hancom installer was used because the public route requires purchase/account approval. Do not replace the current Windows oracle with this until an operator-authorized installer and EULA review permit a real `HwpFrame.HwpObject` test.

## Reproduction

All generated fixtures and helper scripts are under the ignored directory `scratch/linux-hwp-poc/`. They contain only synthetic documents or the repository's sanitized public calibration artifacts. The canonical repository stayed unchanged apart from this report.

### 1. Variables and environment inventory

PowerShell:

```powershell
$Repo = Join-Path $env:USERPROFILE 'dev\rigorloom'
$Poc = "$Repo\scratch\linux-hwp-poc"
git -C $Repo rev-parse HEAD
wsl.exe -- lsb_release -ds
wsl.exe -- uname -r
wsl.exe -- /usr/bin/soffice --version
wsl.exe -- dpkg-query -W libreoffice-core libreoffice-writer libreoffice-h2orestart
wsl.exe -- dpkg-query -W libreoffice-math
```

Key output:

```text
Ubuntu 24.04.2 LTS
5.15.167.4-microsoft-standard-WSL2
LibreOffice 24.2.7.2 420(Build:2)
libreoffice-core       4:24.2.7-0ubuntu0.24.04.5
libreoffice-writer     4:24.2.7-0ubuntu0.24.04.5
libreoffice-h2orestart 0.7.13-1
dpkg-query: no packages found matching libreoffice-math
```

### 2. Recreate the synthetic fixtures on the existing Windows Hancom side

`empty-hwpx.hwpx` is the sanitized empty template copied from the installed H2Orestart examples. `minimal-*.ops.json` are included in the scratch directory.

```powershell
$Com = Join-Path $env:USERPROFILE '.agents\skills\hwp-master\scripts\com_backend.py'

python $Com edit --file "$Poc\empty-hwpx.hwpx" `
  --ops "$Poc\minimal-text.ops.json" `
  --save-as "$Poc\minimal-text.hwpx" `
  --export-pdf "$Poc\minimal-text-com.pdf"
python $Com convert --file "$Poc\minimal-text.hwpx" --to "$Poc\minimal-text.hwp"

python $Com edit --file "$Poc\empty-hwpx.hwpx" `
  --ops "$Poc\minimal-equation.ops.json" `
  --save-as "$Poc\minimal-equation.hwpx" `
  --export-pdf "$Poc\minimal-equation-com.pdf"
python $Com convert --file "$Poc\minimal-equation.hwpx" --to "$Poc\minimal-equation.hwp"
```

These commands use an already-installed Windows Hancom/pyhwpx stack. They do not install anything on Windows.

### 3. LibreOffice/H2Orestart matrix

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
LO24=/usr/bin/soffice
LO26=/home/pantagram/.local/share/rigorloom-linux-hwp/lo-26.2.4-root/opt/libreoffice26.2/program/soffice

for stem in minimal-text.hwpx minimal-text.hwp minimal-equation.hwpx minimal-equation.hwp; do
  "$ROOT/run_soffice_probe.sh" "$LO24" "$ROOT/$stem" \
    "$ROOT/run-lo24-${stem//./-}" "$ROOT/profiles/lo24-${stem//./-}"
  "$ROOT/run_soffice_probe.sh" "$LO26" "$ROOT/$stem" \
    "$ROOT/run-lo26-${stem//./-}" "$ROOT/profiles/lo26-${stem//./-}"
done
```

Representative failing output:

```text
LibreOffice 24.2.7.2 420(Build:2)
Error: Please verify input parameters... (SfxBaseModel::impl_store ...)
Unspecified Application Error
exit_code=1
```

The latest upstream H2Orestart release was also installed into a fresh **user profile** with LibreOffice's `unopkg`; the system extension was not overwritten:

```bash
PROFILE="$ROOT/profiles/h2o-0.7.13"
unopkg -env:UserInstallation="file://$PROFILE" add \
  "$ROOT/downloads/H2Orestart-0.7.13.oxt"
"$ROOT/run_soffice_probe.sh" "$LO24" "$ROOT/minimal-equation.hwpx" \
  "$ROOT/run-lo24-equation-h2o-release" "$PROFILE"
sha256sum "$ROOT/downloads/H2Orestart-0.7.13.oxt"
```

Output remained exit 1; SHA-256 was `726230215dabe450bd617f9acac52376fd76f57c77158bd03b3ef9fe0c7e64fd`.

Parser-only probe:

```bash
H2JAR=/usr/lib/libreoffice/share/extensions/h2orestart/H2Orestart.jar
javac -cp "$H2JAR" -d "$ROOT/tools/h2-parser-classes" \
  "$ROOT/tools/H2OParseProbe.java"
java -cp "$H2JAR:$ROOT/tools/h2-parser-classes" H2OParseProbe \
  "$ROOT/minimal-equation.hwpx"
```

### 4. Equation-image substitution and PDF displacement

```bash
python3 "$ROOT/equations_to_images.py" \
  "$ROOT/minimal-equation.hwpx" "$ROOT/minimal-equation-images.hwpx"
"$ROOT/run_soffice_probe.sh" "$LO24" "$ROOT/minimal-equation-images.hwpx" \
  "$ROOT/run-lo24-equation-images" "$ROOT/profiles/lo24-images"
"$ROOT/run_soffice_probe.sh" "$LO26" "$ROOT/minimal-equation-images.hwpx" \
  "$ROOT/run-lo26-equation-images" "$ROOT/profiles/lo26-images"
```

For the public three-page fixture:

```powershell
python pipeline\scripts\hwpx_render_surrogate.py `
  "$Poc\locked-baseline\linux-xml.hwpx" `
  "$Poc\locked-baseline\linux-xml-surrogate.hwpx" `
  --receipt "$Poc\locked-baseline\linux-xml-surrogate-receipt.json"
python "$Poc\fix_h2_borderfill.py" `
  "$Poc\locked-baseline\linux-xml-surrogate.hwpx" `
  "$Poc\locked-baseline\linux-xml-surrogate-h2.hwpx"
python "$Poc\equations_to_images.py" `
  "$Poc\locked-baseline\linux-xml-surrogate-h2.hwpx" `
  "$Poc\locked-baseline\linux-xml-surrogate-h2-images.hwpx"
```

Convert that final throwaway file with `run_soffice_probe.sh`, then compare each PDF to `locked-baseline/windows-com.pdf`:

```powershell
$env:PYTHONUTF8 = '1'
python "$Poc\compare_pdfs.py" `
  "$Poc\locked-baseline\windows-com.pdf" `
  "$Poc\run-lo26-locked-images\linux-xml-surrogate-h2-images.pdf" `
  --dpi 96 --summary
```

The metric matches words that occur exactly once per page, scales candidate coordinates to the reference page dimensions, and measures Euclidean displacement between word-box centers. It does not measure unmatched objects, equation glyph shape, or raster similarity.

### 5. Exact 676.33 px `rhwp` reproduction

```bash
RHWP=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc/tools/rhwp-0.7.18/rhwp/rhwp
A=/mnt/c/Users/<user>/Downloads/agenthwpx/reports/report-physics-braking-2022-parity/work/stage-5/scratch/tmp/rhwp/out_no_lineseg.hwpx
B=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc/locked-baseline/windows-com.hwpx
"$RHWP" --version
"$RHWP" render-diff "$A" "$B"
```

The command exits 1 with `status: STRUCT_MISMATCH`; the excerpt is recorded in the rendering section above. Locked artifact SHA-256 values:

```text
linux-xml.hwpx  F1E0A067DC0637C8AD40088DA347F241BBFDBAAB9B882CA124990204C760FF50
windows-com.hwpx 2760C5FA0C4A6013D86C473135FEC9E96DCDC62FE100184E110A53BCA59B5041
```

### 6. `rhwp` conversion and rendering probes

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
RHWP="$ROOT/tools/rhwp-0.7.19/rhwp/rhwp"

"$RHWP" export-hwpx "$ROOT/minimal-text.hwp" \
  "$ROOT/rhwp-0719/minimal-text-from-hwp.hwpx" --verify --verify-pages
"$RHWP" export-hwpx "$ROOT/minimal-equation.hwp" \
  "$ROOT/rhwp-0719/minimal-equation-from-hwp.hwpx" --verify --verify-pages

"$RHWP" convert "$ROOT/minimal-text.hwp" \
  "$ROOT/rhwp-0719/minimal-text-reserialized.hwp" --verify --verify-pages
"$RHWP" convert "$ROOT/minimal-equation.hwp" \
  "$ROOT/rhwp-0719/minimal-equation-reserialized.hwp" --verify --verify-pages

"$RHWP" export-svg "$ROOT/locked-baseline/linux-xml-surrogate.hwpx" \
  -o "$ROOT/rhwp-0719/locked-svg"
timeout 240s "$RHWP" export-pdf \
  "$ROOT/locked-baseline/linux-xml-surrogate.hwpx" \
  -o "$ROOT/rhwp-0719/locked.pdf"
```

Reopen the conversion outputs with Hancom and compare:

```powershell
python "$Poc\render_with_hancom.py" `
  "$Poc\rhwp-0719\minimal-text-from-hwp.hwpx" `
  "$Poc\rhwp-0719\minimal-text-from-hwp-com.pdf"
python "$Poc\compare_pdfs.py" "$Poc\minimal-text-com.pdf" `
  "$Poc\rhwp-0719\minimal-text-from-hwp-com.pdf" --dpi 300 --summary
```

Repeat for the equation and reserialized HWP outputs. All four comparisons reported 0.0 px maximum displacement; direct 300-dpi raster comparison reported a zero changed-channel ratio.

### 7. `pyhwp`, `libhwp`, and `unhwp`

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
"$ROOT/run_pyhwp_probe.sh"

/home/pantagram/.local/share/rigorloom-linux-hwp/libhwp-env/bin/python \
  "$ROOT/libhwp_probe.py" "$ROOT/minimal-text.hwp"
/home/pantagram/.local/share/rigorloom-linux-hwp/libhwp-env/bin/python \
  "$ROOT/libhwp_probe.py" "$ROOT/minimal-equation.hwp"

/home/pantagram/.local/share/rigorloom-linux-hwp/unhwp-env/bin/python - <<'PY'
from pathlib import Path
from unhwp import to_markdown

root = Path("/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc")
for name in ("minimal-text.hwp", "minimal-equation.hwp", "minimal-equation.hwpx"):
    print(name)
    print(to_markdown(str(root / name)))
PY
```

### 8. OpenHWP

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
cd "$ROOT/src/openhwp"
git rev-parse HEAD
cargo test --workspace
cd "$ROOT/openhwp-probe"
cargo run --release -- "$ROOT/minimal-text.hwp"
cargo run --release -- "$ROOT/minimal-equation.hwp"
```

Key output: commit `c605402ffae2f241baab06c9010a68faf1415d63`, 558 tests passed, and the probe's text output was incomplete for both files.

### 9. `hwplib`

The following two changes were applied only in the ignored scratch clone to make a current source probe possible: compiler source/target 7 to 8, and removal of the unused `com.sun.jmx.snmp.agent.SnmpUserDataFactory` import.

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
J=/home/pantagram/.local/share/rigorloom-linux-hwp/temurin8/bin
MVN=/home/pantagram/.local/share/rigorloom-linux-hwp/apache-maven-3.9.11/bin/mvn
cd "$ROOT/src/hwplib"
JAVA_HOME=/home/pantagram/.local/share/rigorloom-linux-hwp/temurin8 \
  "$MVN" test package

"$J/javac" -encoding UTF-8 -cp "$ROOT/src/hwplib/target/classes" \
  -d "$ROOT/hwplib-probe-out" "$ROOT/hwplib_probe.java"
"$J/java" -cp "$ROOT/src/hwplib/target/classes:$ROOT/hwplib-probe-out" \
  hwplib_probe "$ROOT/minimal-text.hwp" \
  "$ROOT/hwplib-probe-out/minimal-text-rewritten.hwp"
"$J/java" -cp "$ROOT/src/hwplib/target/classes:$ROOT/hwplib-probe-out" \
  hwplib_probe "$ROOT/minimal-equation.hwp" \
  "$ROOT/hwplib-probe-out/minimal-equation-rewritten.hwp"
```

This WSL Maven command was terminated after it stopped producing output for more than four minutes; use the direct probe commands only after confirming `target/classes` exists. The later Pantadex JDK 8 container build in reproduction step 12 completed all three projects and resolves the build question for that environment. Hancom acceptance and PDF comparison:

```powershell
python "$Poc\render_with_hancom.py" `
  "$Poc\hwplib-probe-out\minimal-text-rewritten.hwp" `
  "$Poc\hwplib-probe-out\minimal-text-rewritten-com.pdf"
python "$Poc\render_with_hancom.py" `
  "$Poc\hwplib-probe-out\minimal-equation-rewritten.hwp" `
  "$Poc\hwplib-probe-out\minimal-equation-rewritten-com.pdf"
python "$Poc\compare_pdfs.py" "$Poc\minimal-text-com.pdf" `
  "$Poc\hwplib-probe-out\minimal-text-rewritten-com.pdf" --dpi 300 --summary
python "$Poc\compare_pdfs.py" "$Poc\minimal-equation-com.pdf" `
  "$Poc\hwplib-probe-out\minimal-equation-rewritten-com.pdf" --dpi 300 --summary
```

### 10. Source activity snapshots

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
git clone https://github.com/ebandal/H2Orestart.git "$ROOT/src/H2Orestart"
git clone https://github.com/mete0r/pyhwp.git "$ROOT/src/pyhwp"
git clone https://github.com/openhwp/openhwp.git "$ROOT/src/openhwp"
git clone https://github.com/neolord0/hwplib.git "$ROOT/src/hwplib"
git clone https://github.com/neolord0/hwpxlib.git "$ROOT/src/hwpxlib"
git clone https://github.com/neolord0/hwp2hwpx.git "$ROOT/src/hwp2hwpx"

for repo in H2Orestart pyhwp openhwp hwplib hwpxlib hwp2hwpx; do
  git -C "$ROOT/src/$repo" rev-parse HEAD
  git -C "$ROOT/src/$repo" log -1 --format='%cI'
done
rg -n 'TextEmbeddedObject|078B7ABA|threeD|breakCellSeparateLine' \
  "$ROOT/src/H2Orestart/source"
```

Recorded commit/date pairs were H2Orestart `a0ead596` / 2026-06-27, pyhwp `83239f0d` / 2023-04-10, OpenHWP `c605402f` / 2025-12-13, `hwplib` `d9e073d` / 2026-07-13, `hwpxlib` `7c159a6` / 2026-07-16, and `hwp2hwpx` `50ae71b` / 2026-06-25.

### 11. Pantadex ARM64 `rhwp` WebAssembly

Stage the four minimal fixtures and `locked-baseline/linux-xml-surrogate.hwpx` under `$ROOT/fixtures`, verify their hashes, and copy `rhwp-arm-probe.mjs` plus `rhwp-complex-probe.mjs` from the ignored proof-of-concept directory:

```bash
ROOT=/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720
mkdir -p "$ROOT"/{fixtures,logs,results,rhwp-node}
sha256sum "$ROOT"/fixtures/*

/usr/bin/time -v npm install --prefix "$ROOT/rhwp-node" \
  --no-save --ignore-scripts --no-audit --no-fund \
  @rhwp/core@0.7.19 @napi-rs/canvas@1.0.2

/usr/bin/time -v node "$ROOT/rhwp-node/rhwp-arm-probe.mjs" \
  "$ROOT/fixtures" "$ROOT/results/rhwp-arm"
/usr/bin/time -v node "$ROOT/rhwp-node/rhwp-complex-probe.mjs" \
  "$ROOT/fixtures/complex-surrogate.hwpx" \
  "$ROOT/results/rhwp-complex-arm"
```

Short output excerpt:

```text
architecture=arm64 node=v20.20.2 rhwp=0.7.19
minimal-text.hwp: pages=1 native reopen=true cross reopen=true
minimal-equation.hwpx: pages=1 native reopen=true cross reopen=true
complex: pageCount=3 renderMs=[86.54,74.48,22.87]
Elapsed 0:02.24; Maximum resident set size 318364 KiB
```

### 12. Pantadex ARM64 Java rewrite and HWP-to-HWPX conversion

All dependency downloads occurred during the build invocation. The actual document probe used `--network=none`.

```bash
ROOT=/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720
mkdir -p "$ROOT/java-src"
for repo in hwplib hwpxlib hwp2hwpx; do
  git clone --depth 1 "https://github.com/neolord0/$repo.git" \
    "$ROOT/java-src/$repo"
done

for repo in hwplib hwpxlib; do
  sed -i 's#<source>7</source>#<source>8</source>#;
          s#<target>7</target>#<target>8</target>#' \
    "$ROOT/java-src/$repo/pom.xml"
done
sed -i 's#<maven.compiler.source>7</maven.compiler.source>#<maven.compiler.source>8</maven.compiler.source>#;
        s#<maven.compiler.target>7</maven.compiler.target>#<maven.compiler.target>8</maven.compiler.target>#' \
  "$ROOT/java-src/hwp2hwpx/pom.xml"
sed -i '/import com\.sun\.jmx\.snmp\.agent\.SnmpUserDataFactory;/d' \
  "$ROOT/java-src/hwplib/src/main/java/kr/dogfoot/hwplib/writer/autosetter/ForDocInfo.java"

docker run --name rigorloom-java-hwp-poc-20260720 --rm \
  --cpus=2 --memory=8g --pids-limit=512 \
  -v "$ROOT:/work" -w /work/java-src maven:3.9-eclipse-temurin-8 \
  bash -lc 'set -eu; for repo in hwplib hwpxlib hwp2hwpx; do
    mvn -f "$repo/pom.xml" -Dmaven.repo.local=/work/m2 \
      -DskipTests -Dgpg.skip=true -Dmaven.javadoc.skip=true install
  done'

docker run --name rigorloom-java-hwp-poc-20260720 --rm --network=none \
  --cpus=2 --memory=8g --pids-limit=512 \
  -v "$ROOT:/work" -w /work/java-src maven:3.9-eclipse-temurin-8 \
  bash -lc 'set -eu
    CP=hwplib/target/hwplib-1.1.10.jar:hwpxlib/target/hwpxlib-1.0.9.jar:hwp2hwpx/target/hwp2hwpx-1.0.0.jar
    mkdir -p /work/results/java/classes /work/results/java/files
    javac -encoding UTF-8 -cp "$CP" -d /work/results/java/classes JavaHwpProbe.java
    java -cp "$CP:/work/results/java/classes" JavaHwpProbe \
      /work/fixtures /work/results/java/files'

unzip -t "$ROOT/results/java/files/minimal-equation-hwp2hwpx.hwpx"
unzip -p "$ROOT/results/java/files/minimal-equation-hwp2hwpx.hwpx" \
  Contents/section0.xml | grep -E 'hp:equation|hp:script'
```

Representative output:

```text
hwplib BUILD SUCCESS 16.557 s
hwpxlib BUILD SUCCESS 12.657 s
hwp2hwpx BUILD SUCCESS 5.872 s
route=HWP-hwplib-HWP ... text_equal=true
route=HWP-hwp2hwpx-HWPX ... output_bytes=6979
<hp:script>x^2 + y^2 = 1
route=HWPX-hwpxlib-HWPX ... text_equal=true
```

Render the four outputs with the existing Windows reference renderer, then run `compare_pdfs.py --dpi 300 --summary` and `compare_pdf_rasters.py --dpi 300`. All four returned `max_displacement_px: 0.0` and `changed_channel_ratio: 0.0`. No Windows installation occurred.

### 13. Pantadex Hangover/FEX COM smoke test

The build files are `scratch/linux-hwp-poc/hangover/{Dockerfile,com_smoke.c,run-smoke.sh}`. The release archive hash came from the GitHub release API and was verified after download.

```bash
ROOT=/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720
URL=https://github.com/AndreRH/hangover/releases/download/hangover-11.9/hangover_11.9_ubuntu2404_noble_arm64.tar
curl -L --fail --retry 3 -o "$ROOT/downloads/hangover_11.9_ubuntu2404_noble_arm64.tar" "$URL"
printf '%s  %s\n' \
  0c66e48800c03d32c3c22029b5053cef3d61376aedcf44eaddf82dce63e410dd \
  "$ROOT/downloads/hangover_11.9_ubuntu2404_noble_arm64.tar" | sha256sum -c -

mkdir -p "$ROOT/hangover-context"
tar -xf "$ROOT/downloads/hangover_11.9_ubuntu2404_noble_arm64.tar" \
  -C "$ROOT/hangover-context" --wildcards '*.deb'
cp scratch/linux-hwp-poc/hangover/{Dockerfile,com_smoke.c,run-smoke.sh} \
  "$ROOT/hangover-context/"
docker build --progress=plain -t rigorloom-hangover-poc:20260720 \
  "$ROOT/hangover-context"

docker run --name rigorloom-hangover-poc-20260720 --rm --network=none \
  --cpus=2 --memory=8g --pids-limit=512 \
  -e WINEPREFIX=/work/results/hangover/wine-prefix \
  -v "$ROOT:/work" rigorloom-hangover-poc:20260720
```

For the cgroup measurement, repeat detached with `-e HOLD_SECONDS=15`, wait until `docker logs` contains `activated_count=3`, then run:

```bash
docker stats --no-stream rigorloom-hangover-poc-20260720
docker exec rigorloom-hangover-poc-20260720 \
  sh -lc 'cat /sys/fs/cgroup/memory.current;
          cat /sys/fs/cgroup/memory.peak;
          cat /sys/fs/cgroup/pids.current'
docker inspect rigorloom-hangover-poc-20260720 \
  --format 'cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}} network={{.HostConfig.NetworkMode}}'
```

The test intentionally stopped before Hancom installation. A real follow-up must receive an authorized installer/license, verify the EULA, activate `HwpFrame.HwpObject`, open only the sanitized fixtures, and compare its PDFs to the same references.

### 14. Pantadex rollback

Before testing, `rigorloom-hangover-poc:20260720`, both Maven image tags, and `ubuntu:24.04` were confirmed absent. Cleanup therefore removed only resources introduced by this proof-of-concept. The path guard must match the exact dated directory:

```bash
ROOT=/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720
PARENT=/home/ubuntu/pantakit/scratch

for name in rigorloom-hangover-poc-20260720 rigorloom-java-hwp-poc-20260720; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    docker container rm -f "$name"
  fi
done

resolved_root=$(realpath -m -- "$ROOT")
resolved_parent=$(realpath -m -- "$PARENT")
case "$resolved_root" in
  "$resolved_parent"/linux-hwp-poc-20260720) ;;
  *) printf 'Refusing unsafe cleanup target: %s\n' "$resolved_root" >&2; exit 2 ;;
esac

# A container removes root-owned Wine-prefix files inside the exact scratch root.
docker run --rm --network=none --entrypoint /bin/sh \
  -v "$PARENT:/scratch" rigorloom-hangover-poc:20260720 \
  -c 'test "$1" = /scratch/linux-hwp-poc-20260720 && rm -rf -- "$1"' \
  cleanup /scratch/linux-hwp-poc-20260720

docker image rm rigorloom-hangover-poc:20260720
docker image rm maven:3.9-eclipse-temurin-8
docker image rm maven:3.9-eclipse-temurin-17
docker image rm ubuntu:24.04
```

The default BuildKit builder retained cache records after image removal. A broad `docker builder prune` was not used because it would delete unrelated Pantadex caches. Instead, `docker buildx du --format json` was used to identify only records created by this Dockerfile during the test window (their descriptions included `COPY hangover-*.deb`, the two Hangover `apt-get` steps, `com_smoke.c`, and `run-smoke.sh`), and each exact cache ID was removed with:

```bash
docker buildx prune --filter "id=$cache_id" --force
docker buildx du --filter "id=$cache_id" --format '{{.ID}}'
```

All identified proof-of-concept cache IDs returned no result afterward. A future rerun should use a dedicated Buildx builder and remove that builder at the end, which makes cache rollback simpler without broad pruning.

Post-cleanup checks:

```bash
test ! -e /home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720
docker image inspect rigorloom-hangover-poc:20260720 >/dev/null 2>&1; test $? -ne 0
docker ps -a --filter name=rigorloom-hangover-poc-20260720 --format '{{.Names}}'
```

## Linux-side install inventory

All installs were user-local, unpacked below a scratch root, or contained in disposable Docker images; no Windows-side software was installed. The existing Ubuntu LibreOffice/H2Orestart packages were inspected but not changed. Pantadex host packages, services, ports, and firewall state were not changed.

| Installed item | Resolved version | User-local location / method |
|---|---|---|
| LibreOffice official full archive | 26.2.4.2, build `0229ac93...` | DEBs extracted without root under `/home/pantagram/.local/share/rigorloom-linux-hwp/lo-26.2.4-root`; archive SHA-256 `810ef197e190d7804a60e0016052c46ff33792303a200fddda9d5216a64b9900` |
| H2Orestart upstream extension | 0.7.13 | Installed only into scratch LibreOffice user profiles; `.oxt` SHA-256 `726230215dabe450bd617f9acac52376fd76f57c77158bd03b3ef9fe0c7e64fd` |
| `rhwp` release archives | 0.7.18 and 0.7.19 | Extracted under `scratch/linux-hwp-poc/tools/`; hashes listed above |
| `pip` bootstrap | current `get-pip.py` result | `python3 get-pip.py --user --break-system-packages` |
| `virtualenv` | 21.6.1 | User Python packages |
| `pyhwp`, `six`, `lxml` | 0.1b15, 1.17.0, 6.0.2 | `/home/pantagram/.local/share/rigorloom-linux-hwp/pyhwp-env` |
| `libhwp` | 0.2.0 | `/home/pantagram/.local/share/rigorloom-linux-hwp/libhwp-env` |
| `unhwp` | 0.5.3 | `/home/pantagram/.local/share/rigorloom-linux-hwp/unhwp-env` |
| Rust toolchain | rustc 1.97.1, cargo 1.97.1 | `rustup` minimal profile under the WSL user home |
| Apache Maven | 3.9.11 | `/home/pantagram/.local/share/rigorloom-linux-hwp/apache-maven-3.9.11`; archive SHA-256 `4b7195b6a4f5c81af4c0212677a32ee8143643401bc6e1e8412e6b06ea82beac` |
| Eclipse Temurin JDK | 8u492 | `/home/pantagram/.local/share/rigorloom-linux-hwp/temurin8`; archive SHA-256 `da257f161d7f8c6ca5b0e5d9e4090f65ac28c5e398072e68b8ae87988b1d1a2e` |
| `@rhwp/core`, `@napi-rs/canvas` | 0.7.19, 1.0.2 | Pantadex `/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720/rhwp-node`; npm prefix only, 34 MB |
| Pure-Java source/Maven cache | `hwplib` 1.1.10, `hwpxlib` 1.0.9, `hwp2hwpx` 1.0.0; Maven 3.9.16/JDK 8u492 image | Pantadex scratch plus `maven:3.9-eclipse-temurin-8`; no host JDK/Maven install |
| Hangover/FEX/Box64 | Hangover 11.9, FEX 2605, Box64 0.4.2 | Verified 287,129,600-byte archive in Pantadex scratch; custom image `rigorloom-hangover-poc:20260720`, 1,094,718,945 bytes |

Installed-package reproduction:

```bash
ROOT=/mnt/c/Users/<user>/dev/rigorloom/scratch/linux-hwp-poc
LOCAL=/home/pantagram/.local/share/rigorloom-linux-hwp

# Unpack the official LibreOffice DEBs without apt/root.
mkdir -p "$ROOT/tools/lo-26.2.4-extract" "$LOCAL/lo-26.2.4-root"
tar -xzf "$ROOT/downloads/LibreOffice_26.2.4_Linux_x86-64_deb.tar.gz" \
  -C "$ROOT/tools/lo-26.2.4-extract"
find "$ROOT/tools/lo-26.2.4-extract/LibreOffice_26.2.4.2_Linux_x86-64_deb/DEBS" \
  -name '*.deb' -exec dpkg-deb -x '{}' "$LOCAL/lo-26.2.4-root" ';'

# Release archives used directly from user-writable locations.
mkdir -p "$ROOT/tools/rhwp-0.7.18" "$ROOT/tools/rhwp-0.7.19"
tar -xzf "$ROOT/downloads/rhwp-v0.7.18-linux-x86_64.tar.gz" \
  -C "$ROOT/tools/rhwp-0.7.18"
tar -xzf "$ROOT/downloads/rhwp-v0.7.19-linux-x86_64.tar.gz" \
  -C "$ROOT/tools/rhwp-0.7.19"
tar -xzf "$LOCAL/apache-maven-3.9.11-bin.tar.gz" -C "$LOCAL"
mkdir -p "$LOCAL/temurin8"
tar -xzf "$LOCAL/temurin8.tar.gz" -C "$LOCAL/temurin8" --strip-components=1

# Python environments.
python3 get-pip.py --user --break-system-packages
python3 -m pip install --user --break-system-packages virtualenv
python3 -m virtualenv "$LOCAL/pyhwp-env"
"$LOCAL/pyhwp-env/bin/pip" install pyhwp==0.1b15 six==1.17.0 lxml==6.0.2
python3 -m virtualenv "$LOCAL/libhwp-env"
"$LOCAL/libhwp-env/bin/pip" install libhwp==0.2.0
python3 -m virtualenv "$LOCAL/unhwp-env"
"$LOCAL/unhwp-env/bin/pip" install unhwp==0.5.3
```

The LibreOffice, JDK, Maven, Rust, H2Orestart, `rhwp`, and Hangover items were archive, package-manager-prefix, or container downloads. Reproduction should verify the publisher's current checksum/signature rather than silently trusting these dated hashes. The Pantadex proof-of-concept used the exact root `/home/ubuntu/pantakit/scratch/linux-hwp-poc-20260720` and exact Docker names/tags; after evidence capture, the 2026-07-20 scratch root and images were removed with the recorded rollback procedure.

## Limitations and open operator questions

### Measurement limits

- The HWP/HWPX write-path positives are based on two one-page synthetic documents. They do not cover the long tail of HWP 5 controls.
- The three-page calibration document is public/sanitized and realistic, but it is still one document.
- The 676.33 px `rhwp` render-tree metric and the LibreOffice PDF word-anchor metric measure different representations.
- Word-anchor displacement ignores unmatched objects and glyph/raster shape. Pixel identity was checked for minimal Hancom-to-Hancom round trips, including the Java conversions, not for LibreOffice/rhwp renderer outputs.
- LO 24 versus LO 26 is a practical stack comparison, not a pure version comparison, because the Ubuntu install lacks LibreOffice Math.
- Fonts, font substitution, WSL graphics/runtime behavior, and exact Hancom build can change layout or timing.
- The Hangover result proves generic x86_64 OLE/COM on Pantadex ARM64 only. It does not prove Hancom installation, activation, rendering, licensing, or long-running stability. One fresh-prefix retry stalled.

### Decisions required from the operator

1. **Commercial evaluation:** May the project contact Hancom and obtain a quote or time-limited Linux/server SDK/viewer trial?
2. **Deployment target:** Which Linux distributions, CPU architectures, container base, offline/network policy, and maximum document/job size must the commercial or open-source path support?
3. **Automation contract:** Is a REST service acceptable, or is an offline local CLI/library mandatory? Public material did not confirm a standalone Hancom CLI.
4. **Licensing:** Are annual/perpetual/site/service licenses acceptable for CI, server rendering, redistribution, and generated output? What concurrency is required?
5. **Document privacy:** May sanitized documents be uploaded to Hancom Docs or any vendor service, or must every render remain local?
6. **Fidelity threshold:** Define acceptance gates separately for page count, render-tree displacement, PDF word displacement, and raster diff. A single undifferentiated `px` threshold is misleading.
7. **v0.15 scope:** Should `.hwp` support be import-only to canonical HWPX, or must v0.15 also emit editable binary HWP after modification?
8. **Upstream engagement:** May maintainers file minimal public issues for H2Orestart's missing Math dependency guidance, optional BorderFill-attribute crash, and complex equation conversion failure?
9. **Corpus approval:** Approve a sanitized HWP/HWPX acceptance corpus before either `rhwp` or `hwplib` becomes a default path.
10. **COM-emulation authorization:** May the operator supply an authorized offline Hancom Windows installer and license for a disposable Hangover test, and does the EULA permit Wine/server automation? Without both, stop.
11. **Oracle topology:** If Windows release rendering must remain, choose between the current Windows workstation, a dedicated x86_64 Windows worker, or Hancom's paid Linux/server service. Pantadex A1 cannot host a supported Windows image and has no nested KVM device.

## Conclusion

There are now demonstrated pure-Linux replacements for every operation except Hancom-grade final rendering. The viable v0.15 design is layered: rigorloom HWPX for canonical edits; ARM-native `@rhwp/core`/`rhwp` for experimental `.hwp` ingress, cross-format editing, and fast SVG diagnostics; the Java `hwplib` + `hwp2hwpx` + `hwpxlib` path as an independent converter/writer quorum; and Hancom only for release verification. LibreOffice/H2Orestart remains an interoperability fallback; equation images solve conversion availability, not fidelity. Pantadex can technically emulate generic Windows COM without excessive RAM or CPU, but actual Hancom compatibility and licensing are unverified and the emulation is operationally less reliable than the native paths. A genuinely Linux-native Hancom-grade renderer remains a commercial evaluation question.
