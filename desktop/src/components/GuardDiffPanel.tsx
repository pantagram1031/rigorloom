import { useEffect, useState, type ReactNode } from "react";
import { refreshGuardDiff } from "../actions";
import { useWorkspace } from "../store";
import type { GuardProtectedToken } from "../types";

const KIND_LABELS: Record<string, string> = {
  numbers: "숫자",
  dates: "날짜",
  source_ids: "식별자",
  citations: "인용",
  tags: "태그",
  inline_math: "수식",
  direct_quotes: "인용부",
  urls: "URL",
  markdown_links: "링크",
  qualifiers: "한정어",
  quantifiers: "수량어",
  causal_markers: "인과표지",
  direction: "방향",
  headings: "제목",
};

const STATUS_LABELS: Record<string, string> = {
  kept: "유지 · kept",
  removed: "누락 · removed",
  added: "추가 · added",
};

function labelText(v: unknown): string {
  if (typeof v === "string") {
    return v.length > 48 ? `${v.slice(0, 48)}…` : v;
  }
  if (v && typeof v === "object" && "label" in v) {
    return String((v as { label?: unknown }).label ?? "");
  }
  return "";
}

function kindLabel(kind: string): string {
  const ko = KIND_LABELS[kind];
  return ko ? `${ko} · ${kind}` : kind;
}

function renderAnnotatedText(
  text: string,
  tokens: GuardProtectedToken[],
): ReactNode {
  if (!text) return <span className="diff-empty-line">(비어 있음)</span>;
  if (!tokens || tokens.length === 0) return text;
  const sorted = [...tokens]
    .filter((t) => Number.isFinite(t.start) && Number.isFinite(t.end) && t.end > t.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (let i = 0; i < sorted.length; i += 1) {
    const tok = sorted[i];
    const start = Math.max(cursor, Math.min(text.length, tok.start));
    const end = Math.max(start, Math.min(text.length, tok.end));
    if (start > cursor) {
      parts.push(text.slice(cursor, start));
    }
    if (end > start) {
      parts.push(
        <mark
          key={`${i}-${start}-${end}`}
          className={`guard-token guard-token--${tok.status}`}
          data-token-kind={tok.kind}
          data-token-status={tok.status}
          title={`${kindLabel(tok.kind)} (${STATUS_LABELS[tok.status]})`}
        >
          {text.slice(start, end)}
          <span className="guard-token-tag">{KIND_LABELS[tok.kind] ?? tok.kind}</span>
        </mark>,
      );
      cursor = end;
    }
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return parts;
}

export function GuardDiffPanel() {
  const activeSessionId = useWorkspace((s) => s.activeSessionId);
  const planId = useWorkspace((s) => s.draft.plan?.planId ?? null);
  const head = useWorkspace((s) => s.head);
  const guardDiff = useWorkspace((s) => s.guardDiff);
  const phase = useWorkspace((s) => s.guardDiffPhase);
  const error = useWorkspace((s) => s.guardDiffError);

  const [mode, setMode] = useState<"session" | "direct">("session");
  const [beforeInput, setBeforeInput] = useState("");
  const [afterInput, setAfterInput] = useState("");
  const [showAllParagraphs, setShowAllParagraphs] = useState(false);

  useEffect(() => {
    if (mode === "session" && activeSessionId && phase === "idle") {
      void refreshGuardDiff();
    }
  }, [mode, activeSessionId, planId, head, phase]);

  const rows = showAllParagraphs
    ? (guardDiff?.allParagraphs ?? guardDiff?.changed ?? [])
    : (guardDiff?.changed ?? []);

  return (
    <section className="guard-panel" data-testid="guard-diff-panel">
      <div className="guard-head">
        <div>
          <h3>보호 비교 · Guard diff</h3>
          <p className="hint">
            숫자·날짜·한정어 등 보호 토큰의 변경 전후 유지 여부를 확인합니다.
          </p>
        </div>
        <div className="guard-controls">
          <div className="segmented" role="tablist" aria-label="비교 방식">
            <button
              type="button"
              className={mode === "session" ? "is-active" : ""}
              onClick={() => {
                setMode("session");
                if (activeSessionId) void refreshGuardDiff();
              }}
            >
              문서 비교 · Session
            </button>
            <button
              type="button"
              className={mode === "direct" ? "is-active" : ""}
              onClick={() => setMode("direct")}
            >
              직접 입력 · Direct
            </button>
          </div>
          <button
            type="button"
            className="ghost"
            data-testid="guard-diff-run"
            disabled={phase === "starting" || (mode === "session" && !activeSessionId)}
            onClick={() =>
              void refreshGuardDiff(
                mode === "direct"
                  ? { beforeText: beforeInput, afterText: afterInput }
                  : undefined,
              )
            }
          >
            {phase === "starting" ? "비교 중…" : "비교 실행 · Run"}
          </button>
        </div>
      </div>

      {mode === "direct" && (
        <div className="guard-direct-inputs">
          <label>
            <span className="section-label">변경 전 · Before</span>
            <textarea
              rows={3}
              data-testid="guard-diff-before-input"
              value={beforeInput}
              onChange={(e) => setBeforeInput(e.target.value)}
              placeholder="2026년 3월 15일까지 최소 20% 증액 검토"
            />
          </label>
          <label>
            <span className="section-label">변경 후 · After</span>
            <textarea
              rows={3}
              data-testid="guard-diff-after-input"
              value={afterInput}
              onChange={(e) => setAfterInput(e.target.value)}
              placeholder="2026년 3월 20일까지 증액 검토"
            />
          </label>
        </div>
      )}

      {error && (
        <div className="error-box" data-testid="guard-diff-error">
          <strong>{error.code}</strong>
          <span>{error.message}</span>
        </div>
      )}

      {!guardDiff && !error && phase !== "starting" && (
        <div className="hint guard-empty">
          {mode === "session" && !activeSessionId
            ? "문서를 열거나 ‘직접 입력 · Direct’ 모드로 전환해 텍스트를 비교할 수 있습니다."
            : "비교 결과가 아직 없습니다. ‘비교 실행 · Run’을 눌러 확인하세요."}
        </div>
      )}

      {guardDiff && (
        <div className="guard-results">
          <div className="guard-summary">
            <span
              className={`guard-verdict ${guardDiff.pass ? "guard-verdict--pass" : "guard-verdict--fail"}`}
              data-testid="guard-diff-verdict"
            >
              {guardDiff.pass ? "보호 유지 · PASS" : "보호 변화 감지 · CHECK"}
            </span>
            <span className="guard-meta mono">
              {labelText(guardDiff.before)} → {labelText(guardDiff.after)}
            </span>
            <span className="guard-meta">
              변경 문단 {guardDiff.changed.length} / 전체 {guardDiff.paragraphs}
            </span>
            {guardDiff.allParagraphs.length > guardDiff.changed.length && (
              <button
                type="button"
                className="ghost"
                onClick={() => setShowAllParagraphs((v) => !v)}
              >
                {showAllParagraphs ? "변경된 문단만" : `전체 문단(${guardDiff.allParagraphs.length})`}
              </button>
            )}
          </div>

          {!guardDiff.pass && guardDiff.reason && (
            <div className="guard-reason">{guardDiff.reason}</div>
          )}

          <div className="guard-legend">
            <span className="guard-token guard-token--kept">유지 · kept</span>
            <span className="guard-token guard-token--removed">누락 · removed</span>
            <span className="guard-token guard-token--added">추가 · added</span>
          </div>

          {rows.length === 0 ? (
            <div className="hint">변경된 문단이 없습니다 · No changed paragraphs.</div>
          ) : (
            <ul className="guard-rows">
              {rows.map((row) => {
                const uniqueTokens = new Map<string, GuardProtectedToken>();
                for (const tok of [...row.beforeProtected, ...row.afterProtected]) {
                  uniqueTokens.set(`${tok.status}:${tok.kind}:${tok.text}`, tok);
                }
                return (
                  <li
                    key={row.paragraph}
                    className={`guard-row ${row.pass ? "" : "guard-row--fail"}`}
                    data-testid={`guard-paragraph-${row.paragraph}`}
                  >
                    <div className="guard-row-head">
                      <span className="mono">문단 #{row.paragraph}</span>
                      <span className={row.pass ? "pill-ok" : "pill-warn"}>
                        {row.pass ? "유지 · pass" : "주의 · drift"}
                      </span>
                      <div className="guard-kind-badges">
                        {row.kinds.map((k) => (
                          <span key={k} className="badge-kind">
                            {kindLabel(k)}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="guard-diff-columns">
                      <div className="guard-col">
                        <span className="diff-tag">전 · Before</span>
                        <div className="guard-text">
                          {renderAnnotatedText(row.before, row.beforeProtected)}
                        </div>
                      </div>
                      <div className="guard-col">
                        <span className="diff-tag">후 · After</span>
                        <div className="guard-text">
                          {renderAnnotatedText(row.after, row.afterProtected)}
                        </div>
                      </div>
                    </div>

                    {uniqueTokens.size > 0 && (
                      <div className="guard-token-summary">
                        {[...uniqueTokens.values()].map((tok, idx) => (
                          <span
                            key={`${idx}-${tok.text}`}
                            className={`guard-chip guard-chip--${tok.status}`}
                          >
                            [{KIND_LABELS[tok.kind] ?? tok.kind}] {tok.text} ({STATUS_LABELS[tok.status]})
                          </span>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
