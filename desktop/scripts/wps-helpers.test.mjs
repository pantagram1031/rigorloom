import assert from "node:assert/strict";
import test from "node:test";

const josa = await import("../src/i18n/josa.ts");
const wpsI18n = await import("../src/i18n/v2/wps.ts");
const titles = await import("../src/workspace/titles.ts");
const dates = await import("../src/workspace/dates.ts");
const exportName = await import("../src/history/exportName.ts");

// ─── i18n/josa.ts ────────────────────────────────────────────────────────────

test("josa handles Hangul batchim, non-batchim, and rieul batchim correctly", () => {
  // Batchim (non-rieul): 문단, 수정본, 변경
  assert.equal(josa.hasBatchim("수정본"), true);
  assert.equal(josa.hasRieulBatchim("수정본"), false);
  assert.equal(josa.withJosa("수정본", "은/는"), "수정본은");
  assert.equal(josa.withJosa("수정본", "이/가"), "수정본이");
  assert.equal(josa.withJosa("수정본", "을/를"), "수정본을");
  assert.equal(josa.withJosa("수정본", "과/와"), "수정본과");
  assert.equal(josa.withJosa("수정본", "으로/로"), "수정본으로");

  // No batchim: 문서, 안내
  assert.equal(josa.hasBatchim("문서"), false);
  assert.equal(josa.withJosa("문서", "은/는"), "문서는");
  assert.equal(josa.withJosa("문서", "이/가"), "문서가");
  assert.equal(josa.withJosa("문서", "을/를"), "문서를");
  assert.equal(josa.withJosa("문서", "과/와"), "문서와");
  assert.equal(josa.withJosa("문서", "으로/로"), "문서로");

  // Rieul batchim: 파일, 글, 표절 -> 으로/로 selects 로!
  assert.equal(josa.hasBatchim("파일"), true);
  assert.equal(josa.hasRieulBatchim("파일"), true);
  assert.equal(josa.withJosa("파일", "은/는"), "파일은");
  assert.equal(josa.withJosa("파일", "을/를"), "파일을");
  assert.equal(josa.withJosa("파일", "으로/로"), "파일로");
  assert.equal(josa.withJosa("파일", "으로서/로서"), "파일로서");
  assert.equal(josa.withJosa("파일", "으로부터/로부터"), "파일로부터");
});

test("josa handles numerals, Latin tokens, acronyms, trailing punctuation, and empty input", () => {
  // Numerals: 1(일=ㄹ), 2(이=vowel), 3(삼=batchim), 10(십=batchim), 7(칠=ㄹ), 8(팔=ㄹ)
  assert.equal(josa.withJosa("수정본 1", "으로/로"), "수정본 1로");
  assert.equal(josa.withJosa("수정본 1", "을/를"), "수정본 1을");
  assert.equal(josa.withJosa("수정본 2", "을/를"), "수정본 2를");
  assert.equal(josa.withJosa("수정본 2", "으로/로"), "수정본 2로");
  assert.equal(josa.withJosa("수정본 3", "으로/로"), "수정본 3으로");
  assert.equal(josa.withJosa("수정본 10", "은/는"), "수정본 10은");
  assert.equal(josa.withJosa("7", "으로/로"), "7로");
  assert.equal(josa.withJosa("8", "으로/로"), "8로");

  // Acronyms & product names
  assert.equal(josa.withJosa("PDF", "으로/로"), "PDF로");
  assert.equal(josa.withJosa("HWPX", "으로/로"), "HWPX로");
  assert.equal(josa.withJosa("XML", "으로/로"), "XML로");
  assert.equal(josa.withJosa("JSON", "으로/로"), "JSON으로");
  assert.equal(josa.withJosa("Rigorloom", "은/는"), "Rigorloom은");
  assert.equal(josa.withJosa("Rigorloom", "으로/로"), "Rigorloom으로");

  // Trailing quotes/brackets stripped before inspection
  assert.equal(josa.pickJosa("‘수정본 1’", "은/는"), "은");
  assert.equal(josa.pickJosa("기안문(별지 제1호서식)", "을/를"), "을");
  assert.equal(josa.pickJosa("‘문서’", "이/가"), "가");

  // NFD Korean normalized to NFC
  const nfd = "수정본".normalize("NFD");
  assert.equal(josa.pickJosa(nfd, "을/를"), "을");

  // Empty input never throws
  assert.equal(josa.withJosa("", "은/는"), "");
  assert.equal(josa.pickJosa("", "은/는"), "는");
});

test("josa detectors catch unresolved particles and particles attached to placeholders", () => {
  assert.equal(josa.containsUnresolvedJosa("{0}이(가) 승인했습니다"), true);
  assert.equal(josa.containsUnresolvedJosa("파일(으)로 저장"), true);
  assert.equal(josa.containsUnresolvedJosa("승인한 사람 {0}"), false);

  assert.equal(josa.hasPlaceholderJosa("수정본 {0}을 만들었습니다"), true);
  assert.equal(josa.hasPlaceholderJosa("{0}이(가) 승인했습니다"), true);
  assert.equal(josa.hasPlaceholderJosa("종료 코드 {0}로 끝났습니다."), true);
  assert.equal(josa.hasPlaceholderJosa("날짜가 {1}에서 {2}로 바뀝니다."), true);

  // Counters / units after placeholders are allowed
  assert.equal(josa.hasPlaceholderJosa("변경 {0}건 승인"), false);
  assert.equal(josa.hasPlaceholderJosa("{0} / {1}쪽"), false);
  assert.equal(josa.hasPlaceholderJosa("{0}월 {1}일 {2} {3}:{4}"), false);
  assert.equal(josa.hasPlaceholderJosa("빈칸 {1}개 중 {0}개 입력"), false);
});

// ─── workspace/titles.ts ─────────────────────────────────────────────────────

test("titles resolves bundled sample forms identically across recents, tabs, and window title", () => {
  const corpus = [
    {
      name: "forms/converted/gianmun-byeolji-1ho.hwpx",
      path: "/repo/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx",
      size: 12000,
    },
    {
      name: "probes/render-check-01.hwpx",
      path: "/repo/tests/corpus/probes/render-check-01.hwpx",
      size: 4000,
    },
    {
      name: "table-break-probe.hwpx",
      path: "/repo/tests/corpus/forms/converted/table-break-probe.hwpx",
      size: 4000,
    },
    {
      name: "forms/gianmun-byeolji-1ho.hwp",
      path: "/repo/tests/corpus/forms/gianmun-byeolji-1ho.hwp",
      size: 10000,
    },
  ];

  // Fixtures hidden and redundant .hwp twin removed
  const visible = titles.visibleSampleForms(corpus, true);
  assert.equal(visible.length, 1);
  assert.equal(visible[0].name, "forms/converted/gianmun-byeolji-1ho.hwpx");
  assert.equal(titles.isHiddenCorpusFixture("render-check-01.hwpx"), true);
  assert.equal(titles.isHiddenCorpusFixture("table-break-probe.hwpx"), true);
  assert.equal(titles.isHiddenCorpusFixture("gianmun-byeolji-1ho.hwpx"), false);

  // Same canonical title from corpus list AND from raw recent path before corpus loads
  const fromCorpus = titles.resolveDocumentTitle({
    path: "/repo/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx",
    corpusFiles: corpus,
    language: "ko",
  });
  const fromRecentPath = titles.resolveDocumentTitle({
    path: "/repo/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx",
    language: "ko",
  });
  assert.equal(fromCorpus.displayName, fromRecentPath.displayName);
  assert.equal(fromCorpus.isSampleForm, true);
  assert.equal(fromCorpus.extension, "");
  assert.equal(fromCorpus.extensionLabel, "HWPX");
  assert.equal(
    titles.formatWindowTitle(fromCorpus, "ko"),
    `${fromCorpus.displayName} — Rigorloom`,
  );
  assert.equal(titles.formatWindowTitle(null, "ko"), "Rigorloom");
});

test("titles splits user file stem + dimmed extension and disambiguates duplicate names", () => {
  const docA = titles.resolveDocumentTitle({
    path: "/home/user/문서/2026/발송/기안문.hwpx",
    language: "ko",
  });
  const docB = titles.resolveDocumentTitle({
    path: "/home/user/문서/2026/수신/기안문.hwpx",
    language: "ko",
  });
  const docC = titles.resolveDocumentTitle({
    path: "/home/user/문서/협조요청_개요.md",
    language: "ko",
  });

  assert.equal(docA.stem, "기안문");
  assert.equal(docA.extension, ".hwpx");
  assert.equal(docA.displayName, "기안문.hwpx");
  assert.equal(docA.extensionLabel, "HWPX");
  assert.equal(docA.isSampleForm, false);

  const disambiguated = titles.disambiguateDocumentTitles([
    { title: docA, path: "/home/user/문서/2026/발송/기안문.hwpx" },
    { title: docB, path: "/home/user/문서/2026/수신/기안문.hwpx" },
    { title: docC, path: "/home/user/문서/협조요청_개요.md" },
  ]);
  assert.equal(disambiguated[0].title.disambiguator, "발송");
  assert.equal(disambiguated[1].title.disambiguator, "수신");
  assert.equal(disambiguated[2].title.disambiguator, "");

  // When immediate parent folders also match, climb one segment higher
  const deepDup = titles.disambiguateDocumentTitles([
    { title: docA, path: "/home/user/문서/2025/발송/기안문.hwpx" },
    { title: docB, path: "/home/user/문서/2026/발송/기안문.hwpx" },
  ]);
  assert.equal(deepDup[0].title.disambiguator, "2025/발송");
  assert.equal(deepDup[1].title.disambiguator, "2026/발송");

  // Untitled fallback
  const untitledKo = titles.resolveDocumentTitle({ name: "", language: "ko" });
  const untitledEn = titles.resolveDocumentTitle({ name: "  ", language: "en" });
  assert.equal(untitledKo.displayName, wpsI18n.tWps("wps_untitled_document", "ko"));
  assert.equal(untitledEn.displayName, "Untitled document");

  // Supported workspace extensions
  assert.equal(titles.isSupportedWorkspaceExtension("a.hwpx"), true);
  assert.equal(titles.isSupportedWorkspaceExtension("a.HWP"), true);
  assert.equal(titles.isSupportedWorkspaceExtension("a.docx"), true);
  assert.equal(titles.isSupportedWorkspaceExtension("a.md"), true);
  assert.equal(titles.isSupportedWorkspaceExtension("a.exe"), false);
  assert.equal(titles.isSupportedWorkspaceExtension("a.txt"), false);

  // Breadcrumb never exposes /home/user when root is supplied
  assert.equal(
    titles.formatFolderBreadcrumb(
      "/home/user/문서/기록관리과/2026 협조/기안문.hwpx",
      "/home/user/문서",
    ),
    "문서 › 기록관리과 › 2026 협조",
  );
});

// ─── workspace/dates.ts ──────────────────────────────────────────────────────

test("dates enforces one canonical date format across the entire app", () => {
  // 2026-11-17T04:13:00Z = 2026-11-17 13:13 KST (Asia/Seoul)
  const sampleIso = "2026-11-17T04:13:00Z";
  assert.equal(
    dates.formatAppDateTime(sampleIso, "ko", { timeZone: "Asia/Seoul" }),
    "11월 17일 오후 1:13",
  );
  assert.equal(
    dates.formatAppDateTime(sampleIso, "en", { timeZone: "Asia/Seoul" }),
    "Nov 17, 1:13 PM",
  );

  // 2026-11-19T05:31:00Z = 2026-11-19 14:31 KST
  const approvalIso = "2026-11-19T05:31:00Z";
  assert.equal(
    dates.formatAppDateTime(approvalIso, "ko", { timeZone: "Asia/Seoul" }),
    "11월 19일 오후 2:31",
  );
  assert.equal(
    dates.formatAppTime(approvalIso, "ko", { timeZone: "Asia/Seoul" }),
    "오후 2:31",
  );
  assert.equal(
    dates.formatAppTime(approvalIso, "en", { timeZone: "Asia/Seoul" }),
    "2:31 PM",
  );

  // Midnight (00:05) -> 오전 12:05 and Noon (12:05) -> 오후 12:05, single-digit month/day
  assert.equal(
    dates.formatAppDateTime("2026-01-05T00:05:00Z", "ko", { timeZone: "UTC" }),
    "1월 5일 오전 12:05",
  );
  assert.equal(
    dates.formatAppDateTime("2026-01-05T12:05:00Z", "ko", { timeZone: "UTC" }),
    "1월 5일 오후 12:05",
  );
  assert.equal(
    dates.formatAppDateTime("2026-01-05T00:05:00Z", "en", { timeZone: "UTC" }),
    "Jan 5, 12:05 AM",
  );

  // Never returns relative strings, ISO strings, or "Invalid Date"
  assert.equal(dates.formatAppDateTime("not-a-date", "ko"), "");
  assert.equal(dates.formatAppDateTime(null, "ko"), "");
  assert.equal(dates.formatAppDateTime(NaN, "ko"), "");
  assert.equal(
    dates.formatHistoryDateTime(undefined, "ko"),
    wpsI18n.tWps("wps_date_unknown", "ko"),
  );
  assert.equal(
    dates.formatAppDateTime(sampleIso, "ko", {
      timeZone: "Asia/Seoul",
      fixedTime: "11월 19일 오후 2:31",
    }),
    "11월 19일 오후 2:31",
  );
});

// ─── history/exportName.ts ───────────────────────────────────────────────────

test("exportName generates …_수정본N.ext and strips prior revision suffixes", () => {
  assert.equal(
    exportName.formatExportFilename({
      baseName: "기안문(별지 제1호서식)",
      revisionNumber: 2,
      format: "hwpx",
      language: "ko",
    }),
    "기안문(별지 제1호서식)_수정본2.hwpx",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: "기안문(별지 제1호서식).hwpx",
      revisionNumber: 1,
      format: "PDF",
      language: "ko",
    }),
    "기안문(별지 제1호서식)_수정본1.pdf",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: "기안문_수정본1.hwpx",
      revisionNumber: 2,
      format: "hwpx",
      language: "ko",
    }),
    "기안문_수정본2.hwpx",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: "gianmun-byeolji-1ho-candidate.hwpx",
      revisionNumber: 3,
      format: "hwpx",
      language: "ko",
    }),
    "gianmun-byeolji-1ho_수정본3.hwpx",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: "Draft.hwpx",
      revisionNumber: 2,
      format: "hwpx",
      language: "en",
    }),
    "Draft_rev2.hwpx",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: "기안문.hwpx",
      revisionNumber: null,
      format: "hwpx",
      language: "ko",
    }),
    "기안문_원본.hwpx",
  );
  // Windows reserved device name and illegal characters sanitized safely
  assert.equal(
    exportName.formatExportFilename({
      baseName: "CON.hwpx",
      revisionNumber: 1,
      format: "hwpx",
      language: "ko",
    }),
    "CON__수정본1.hwpx",
  );
  assert.equal(
    exportName.formatExportFilename({
      baseName: 'bad:name*with?"chars',
      revisionNumber: 1,
      format: "hwpx",
      language: "ko",
    }),
    "bad name with chars_수정본1.hwpx",
  );
});

test("exportName refuses targets equal to source, case-insensitively on Windows and across path forms", () => {
  // Windows case-insensitive, slash style, relative .., extended \\?\ prefix, trailing dot
  const winCases = [
    ["C:\\Docs\\Draft.hwpx", "C:\\Docs\\Draft.hwpx"],
    ["c:\\docs\\draft.HWPX", "C:\\Docs\\Draft.hwpx"],
    ["c:/docs/sub/../draft.hwpx", "C:\\Docs\\Draft.hwpx"],
    ["\\\\?\\C:\\Docs\\Draft.hwpx", "C:\\Docs\\Draft.hwpx"],
    ["C:\\Docs\\Draft.hwpx.", "C:\\Docs\\Draft.hwpx"],
    ["\\\\server\\share\\DOCS\\Report.HWPX", "//SERVER/share/docs/report.hwpx"],
    ["\\\\?\\UNC\\server\\share\\report.hwpx", "\\\\SERVER\\share\\Report.HWPX"],
  ];
  for (const [target, source] of winCases) {
    const res = exportName.validateExportTarget({
      targetPath: target,
      sourcePath: source,
      language: "ko",
    });
    assert.equal(res.ok, false, `expected refusal for ${target} vs ${source}`);
    assert.equal(
      res.code,
      target.endsWith(".") ? "invalid_name" : "target_equals_source",
      `code mismatch for ${target}`,
    );
    assert.equal(
      exportName.isSamePathAsSource(target, source),
      true,
      `expected isSamePathAsSource=true for ${target} vs ${source}`,
    );
  }

  // POSIX case-sensitive vs identical + NFC/NFD Korean equality
  const nfd = "/home/user/문서/기안문.hwpx".normalize("NFD");
  const nfc = "/home/user/문서/기안문.hwpx".normalize("NFC");
  assert.equal(exportName.isSamePathAsSource(nfd, nfc, { platform: "posix" }), true);
  assert.equal(
    exportName.validateExportTarget({
      targetPath: "/home/user/문서/sub/../기안문.hwpx",
      sourcePath: nfc,
      platform: "posix",
    }).ok,
    false,
  );
  assert.equal(
    exportName.validateExportTarget({
      targetPath: "/home/user/문서/Draft.hwpx",
      sourcePath: "/home/user/문서/draft.hwpx",
      platform: "posix",
    }).ok,
    true,
  );
  assert.equal(
    exportName.validateExportTarget({
      targetPath: "/home/user/문서/Draft.hwpx",
      sourcePath: "/home/user/문서/draft.hwpx",
      platform: "win32",
    }).ok,
    false,
  );

  // Sidecar receipt collision refused
  assert.equal(
    exportName.validateExportTarget({
      targetPath: "/home/user/문서/기안문.hwpx.receipt.json",
      sourcePath: "/home/user/문서/기안문.hwpx",
      platform: "posix",
    }).ok,
    false,
  );

  // NUL bytes, empty names, reserved device names refused
  assert.equal(exportName.validateExportTarget({ targetPath: "" }).ok, false);
  assert.equal(
    exportName.validateExportTarget({ targetPath: "/tmp/a\x00.hwpx" }).ok,
    false,
  );
  assert.equal(
    exportName.validateExportTarget({ targetPath: "C:\\Docs\\NUL.hwpx" }).ok,
    false,
  );

  // Distinct export target succeeds cleanly
  const okRes = exportName.validateExportTarget({
    targetPath: "C:\\Docs\\기안문_수정본1.hwpx",
    sourcePath: "C:\\Docs\\기안문.hwpx",
    language: "ko",
  });
  assert.equal(okRes.ok, true);
  if (okRes.ok) {
    assert.equal(okRes.filename, "기안문_수정본1.hwpx");
  }

  assert.equal(
    exportName.joinExportPath("C:\\Docs\\", "기안문_수정본1.hwpx"),
    "C:\\Docs\\기안문_수정본1.hwpx",
  );
  assert.equal(
    exportName.joinExportPath("/home/user/문서/", "기안문_수정본1.hwpx"),
    "/home/user/문서/기안문_수정본1.hwpx",
  );
});
