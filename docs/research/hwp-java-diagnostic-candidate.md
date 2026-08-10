# T87: quarantined Java HWP diagnostic candidate

T87 is a separate diagnostic lane for one approved `hwp2hwpx` Java tool
snapshot. It is not a T85 ingress adapter, a native Hancom route, an
independent semantic comparison, or render evidence. A successful run exists
only below:

`work/stage-0/scratch/hwp-java-diagnostic/<opaque-run-id>/`

The closed receipt schema is
`rigorloom/hwp-java-diagnostic-candidate/v1`; its comparison is always
`unknown/independent_source_oracle_not_run`, render is `not_run`, proof is
`none`, and submission grade is `false`. `new_report` rejects both this receipt
and the schema-owned raw candidate layout before workspace creation.

## Approved source and artifact boundary

The release-owned lock records these upstream source commits:

- [`hwp2hwpx` `50ae71bbaf98ec7a00192f72492d6a130a755ac1`](https://github.com/neolord0/hwp2hwpx/tree/50ae71bbaf98ec7a00192f72492d6a130a755ac1)
- [`hwplib` `d9e073d6899d947f8f583492e00a5e1062381d7e`](https://github.com/neolord0/hwplib/tree/d9e073d6899d947f8f583492e00a5e1062381d7e)
- [`hwpxlib` `473d9d6aa82d8896f4f464b52d801e5691dc7cf3`](https://github.com/neolord0/hwpxlib/tree/473d9d6aa82d8896f4f464b52d801e5691dc7cf3)

All three projects use Apache-2.0. `hwp2hwpx` has no upstream CLI or official
Maven Central release. T87 therefore uses a source-visible fixed bridge and
accepts only an operator-supplied fat JAR matching the shipped lock:

`io.github.spah1879:hwp2hwpx:2026.6.25-jdk11`

The coordinate is a [third-party Maven Central republication](https://central.sonatype.com/artifact/io.github.spah1879/hwp2hwpx/2026.6.25-jdk11),
not an official `kr.dogfoot:hwp2hwpx` release. Operators obtain it separately
and must review its POM/license/source mapping; Rigorloom does not download or
redistribute it.

The approved JAR SHA-256 is
`06ba7071b9ee2f2256fa62398b5d32dc07496cb47cf764b4cf0b7c6119bd11cd`.
The audited source JAR mapped all 66 project source files exactly to the pinned
upstream `hwp2hwpx` commit; its embedded 727 `hwplib` and 940 `hwpxlib` class
files matched the official Maven artifacts. This is a provenance mapping, not
a native-fidelity or malicious-code sandbox claim. No JAR, JRE, `.class`,
sample HWP/HWPX, or downloaded archive is shipped in the bundle.

The Java launcher path and caller pin are rehashed before and after execution,
but the launcher dynamically loads its surrounding runtime. The receipt says
`runtime_binding: launcher_rehashed_runtime_unbound`; it never claims a closed
JRE snapshot. There is no PATH/JAVA_HOME discovery, Maven resolution, network
download, caller main class, wildcard classpath, or arbitrary JVM argument.
`CLASSPATH`, `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS`, and `JDK_JAVA_OPTIONS` are
removed from the child environment.

## Execution and normalization

The source first passes T85's bounded CFB/FileHeader and protected-property
gate. The source, approved JAR, and fixed bridge are staged as immutable
snapshots. The exact Java operation is equivalent to:

```text
java -XX:-UsePerfData -Djava.awt.headless=true -Dfile.encoding=UTF-8 \
  -Duser.language=en -Duser.country=US -Duser.timezone=UTC \
  -Djava.io.tmpdir=<isolated> -cp <approved-fat-jar> \
  Hwp2HwpxBridge.java convert <snapshot.hwp> <tool-output.hwpx>
```

The shared T86/T87 stdlib core supplies Windows suspended Job containment,
POSIX process groups, bounded output and timeout, no-follow rehashes, root
guards, owner-token rollback, and receipt-first/candidate-last publication.

`hwpxlib` currently writes a deflated, data-descriptor `mimetype`. T87 retains
member payloads, canonicalizes only the ZIP envelope, and prunes only a declared
but absent OCF auxiliary rootfile from the closed Preview/RDF set. The receipt
records `package_normalization: zip_envelope_canonicalized` and the exact
`missing_aux_rootfiles_pruned` count. The result must then pass the unchanged
T85 physical ZIP, OCF, OPF, section-coverage, size, CRC, and control-count
validator. This repair is not semantic parity.

## Commands

Pre-create the exact diagnostic leaf and supply explicit local paths:

```text
python pipeline/scripts/hwp_java_diagnostic_candidate.py run INPUT.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --java <explicit-java-launcher> --java-sha256 <64-lowercase-hex> \
  --tool-jar <approved-fat-jar>

python pipeline/scripts/hwp_java_diagnostic_candidate.py verify \
  --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef
```

Exit 0 means only a current quarantined candidate and receipt. Usage/config is
2; refusal, drift, timeout, invalid output, receipt mismatch, or a publication
race is 3. Receipts contain no source text, argv, stdout/stderr, Java vendor
prose, IDs, document metadata, absolute paths, or downloaded artifact paths.

## Bounded execution evidence

An operator-local Windows JDK 24.0.1 run against the public
`jeongbo-gonggae-cheongguseo.hwp` fixture exited 0, then `verify` exited 0.
The source was 130,048 bytes, the quarantined candidate was 15,069 bytes, and
the bounded output counts were tables 2, pictures 1, equations 0. One missing
Preview auxiliary rootfile was pruned. The candidate and downloaded audit
artifacts were deleted after the check. This is one execution/structure probe,
not Windows/macOS/Linux support, source-text parity, page parity, Hancom native
behavior, rendering, or submission proof.
