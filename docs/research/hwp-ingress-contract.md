# Binary HWP ingress contract (T85)

Checked 2026-08-10. This note defines an evidence boundary, not a claim that a
portable parser can reproduce Hancom layout.

## Why the boundary exists

`.hwp` is a Compound Binary File carrying an HWP `FileHeader`; it is not an
HWPX ZIP and must never be sent to the XML editor. A filename extension, an
installed application, a capability probe, or a skipped comparison does not
prove that a document was safely converted.

The read-only candidate stage validates only a bounded CFB v3 allocation:
exact header invariants, closed FAT/DIFAT/mini-FAT chains and allocation,
exactly one root storage, direct-root `DocInfo`, direct-root `BodyText` with at
least one `Section*`, and the direct-root `FileHeader`. The FileHeader must be
exactly 256 bytes with the exact 32-byte `HWP Document File` signature field,
a supported HWP 5.0/5.1 version, and no password, distribution, script, DRM,
certificate, privacy, or reserved property. It emits no body text, stream
names, author metadata, raw IDs, command output, or absolute paths. Candidate
status is container capability, not semantic or render evidence.

## Canonical publication

T85 has one canonical adapter: Windows Hancom COM. It does not auto-select a
converter and does not promote LibreOffice, `pyhwp`, `hwplib`, or `rhwp`
output. Before each COM child, the runtime performs the exact
`tasklist | findstr /i hwp` precheck and refuses unless no Hwp.exe is running;
it never kills a process. One crash-safe, process-wide Windows named mutex is
held from destination prechecks through receipt-first/output-last publication,
so two ingress calls cannot both enter Hancom or race one another's canonical
receipt.

The source bytes are captured once. The same privacy-safe COM extractor runs
on the captured HWP and the converted, reopened HWPX. Full-text SHA-256,
character count, tables, pictures, equations, shapes, pages, total controls,
and field count must match. The hash itself is an internal comparison value
and is not copied into the public comparison object; the receipt carries only
closed match booleans and aggregate counts. The staged HWPX must have the
physical mimetype/ZIP bounds, OCF rootfile envelope, OPF manifest/spine, and
exact section coverage expected by this slice. The live source hash is checked
again before exclusive publication. The receipt is created first and binds the
staged output hash; the output hard link is the final commit marker.

The receipt's source hash identifies the exact immutable bytes captured for
that conversion. It is not a claim that the caller's original path will keep
those bytes forever, and neither the public receipt nor the converted HWPX
retains a copy of the source HWP. Long-term source custody is therefore an
operator/workspace retention responsibility; consumers can reverify the
published HWPX and receipt, but cannot reconstruct or re-prove a deleted source
HWP from the receipt alone.

The receipt schema is `rigorloom/hwp-ingress/v1`. Its proof grade is always
`none`: a successful HWP-to-HWPX conversion is conversion execution with a
bounded semantic comparison, not native PDF rendering, layout parity, or a
submission proof. Render evidence still requires the separate current
artifact/PDF/quality/visual contracts.

Before a consumer claims HWP-ingress provenance, it must bind the receipt to
the exact HWPX again:

```sh
python pipeline/scripts/hwp_ingress.py verify output/form_copy.hwpx \
  --manifest output/proof/ingress/receipt.json
```

`verify` rejects duplicate/unknown receipt fields, nonterminal state, the
wrong adapter or evidence class, and output size/hash/count drift. The report
scaffolder accepts `--ingress-receipt` for this claimed-origin path, verifies
both the supplied HWPX and its copied `output/form_copy.hwpx`, then retains the
receipt under `output/proof/ingress/`. A native-origin HWPX that makes no binary
HWP-ingress claim remains a separate ordinary HWPX input path.

## Exit and privacy contract

- exit 0: candidate inspection or canonical conversion actually passed;
- exit 2: usage/configuration error;
- exit 3: malformed/protected/unsupported input, unavailable Hancom, an
  already-running Hwp.exe, missing execution leg, hash drift, comparison
  mismatch, invalid output, or publication refusal.

Synthetic CI fixtures construct their own CFB bytes. No corpus HWP/HWPX/PDF
is shipped in the core bundle. A native Windows bench may use an operator-side
scratch copy of a license-reviewed public or project-authored form, but its
bytes remain local and only the closed receipt may be retained.

## Primary sources

- [Hancom HWP 5.0 binary format revision 1.3](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf)
- [Microsoft CFB header](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/05060311-bfce-4b12-874d-71fd4ce63aea)
- [Microsoft CFB chain validity](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/9d33df18-7aee-4065-9121-4eabe41c29d4)
- [Microsoft CFB validation and security considerations](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/3c5249cc-1dc2-46f0-8faf-06c6a36f0085)
- [Hancom Automation and licence boundary](https://developer.hancom.com/hwpautomation)
- [Hancom product support surface](https://www.hancom.com/support/csCenter/prdStatus)

Hancom's Automation page distinguishes non-commercial use from commercial
products/solutions requiring vendor approval or a separate licence. The code
does not install or redistribute Hancom software or vendor binaries.
