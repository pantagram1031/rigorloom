import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { wp3t } from "../i18n/v2/wp3";
import { legacyCellKey, type CanvasChangeRef } from "../model/page";
import {
  activeInspect,
  activeSession,
  activeText,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { deriveCellFieldLabel } from "../workspace/fieldLabels";
import {
  buildIndexedChanges,
  useReviewGuardSummary,
} from "../workspace/guardHelper";
import {
  bindFindFocusHook,
  indexedChangesToCanvasRefs,
} from "../canvas/_shim";
import {
  replaceAllFindMatches,
  replaceFindMatch,
  type FindMatchItem,
} from "../canvas/actions";
import {
  scrollCanvasToTarget,
  setCanvasSlice,
  useCanvasSlice,
} from "../canvas/controller";
import "./panes.css";

export interface FindPaneProps {
  /** Optional external changes list (for standalone harness / WP4 queue). */
  changesOverride?: readonly CanvasChangeRef[];
  /** Start with replace input expanded. */
  defaultShowReplace?: boolean;
}

export function FindPane({
  changesOverride,
  defaultShowReplace = true,
}: FindPaneProps = {}) {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const draft = useWorkspace((s) => s.draft);
  const language = useWorkspace((s) => s.language);
  const guardSummary = useReviewGuardSummary();
  const slice = useCanvasSlice(session?.sessionId);

  const [showReplace, setShowReplace] = useState(defaultShowReplace);
  const findInputRef = useRef<HTMLInputElement | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const composingRef = useRef(false);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const indexedChanges = useMemo(
    () => (inspect ? buildIndexedChanges(draft, inspect, textMap, language) : []),
    [draft, inspect, textMap, language],
  );

  const isStale = Boolean(
    draft.validation?.stale ||
      (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256),
  );

  const changes = useMemo<CanvasChangeRef[]>(() => {
    if (changesOverride) {
      return changesOverride.map((ch) => ({
        ...ch,
        decision: slice.decisions[ch.id] ?? ch.decision,
      }));
    }
    return indexedChangesToCanvasRefs(
      indexedChanges,
      guardSummary.rowAudits,
      slice.decisions,
      {
        isStale,
        reverses: draft.reverses,
        planProvenance: (draft.plan as { provenance?: string | null } | null)?.provenance,
      },
    );
  }, [
    changesOverride,
    indexedChanges,
    guardSummary.rowAudits,
    slice.decisions,
    isStale,
    draft.reverses,
    draft.plan,
  ]);

  useEffect(() => {
    return bindFindFocusHook((mode) => {
      if (mode === "replace") setShowReplace(true);
      requestAnimationFrame(() => {
        if (mode === "replace" && slice.findQuery.trim().length > 0) {
          replaceInputRef.current?.focus();
          replaceInputRef.current?.select();
        } else {
          findInputRef.current?.focus();
          findInputRef.current?.select();
        }
      });
    });
  }, [slice.findQuery]);

  const cellEffectiveChanges = useMemo(() => {
    const map = new Map<string, CanvasChangeRef>();
    for (const ch of changes) {
      if (!ch.cellKey || ch.decision === "rejected") continue;
      if (ch.opKind === "fill_cell" || ch.opKind === "replace_at_cell") {
        map.set(ch.cellKey, ch);
      }
    }
    return map;
  }, [changes]);

  const matches = useMemo<FindMatchItem[]>(() => {
    const query = slice.findQuery.trim();
    if (!inspect || !query) return [];
    const needle = query.toLowerCase();
    const out: FindMatchItem[] = [];
    const coveredStrings = new Set<string>();

    for (const tbl of inspect.graph.tables) {
      const sorted = [...tbl.cells]
        .filter((c) => c.classification !== "spacer")
        .sort((a, b) => a.addr.row - b.addr.row || a.addr.col - b.addr.col);
      for (const cell of sorted) {
        const key = legacyCellKey(tbl.index, cell.addr.row, cell.addr.col);
        const effectiveChange = cellEffectiveChanges.get(key);
        const text =
          effectiveChange?.after ??
          textMap[key]?.text ??
          cell.textPreview ??
          "";
        if (text.trim()) coveredStrings.add(text.trim());
        const matchStart = text.toLowerCase().indexOf(needle);
        if (matchStart < 0) continue;
        const label = deriveCellFieldLabel(
          inspect,
          textMap,
          tbl.index,
          cell.addr.row,
          cell.addr.col,
          language,
        );
        out.push({
          id: key,
          targetType: "cell",
          cellKey: key,
          table: tbl.index,
          row: cell.addr.row,
          col: cell.addr.col,
          label,
          locationLabel: wp3t("seat_location_short", language, [
            1,
            tbl.index + 1,
            cell.addr.row + 1,
            cell.addr.col + 1,
          ]),
          text,
          matchStart,
          matchEnd: matchStart + query.length,
        });
      }
    }

    for (const para of inspect.graph.paragraphs) {
      const pKey = `p:${para.at_para}`;
      const text = textMap[pKey]?.text ?? para.text ?? "";
      if (!text.trim() || coveredStrings.has(text.trim())) continue;
      const matchStart = text.toLowerCase().indexOf(needle);
      if (matchStart < 0) continue;
      out.push({
        id: pKey,
        targetType: "para",
        atPara: para.at_para,
        run: 0,
        label: text.slice(0, 24),
        locationLabel: wp3t("outline_page_header", language, [1]),
        text,
        matchStart,
        matchEnd: matchStart + query.length,
      });
    }

    return out;
  }, [inspect, slice.findQuery, cellEffectiveChanges, textMap, language]);

  const safeIndex =
    matches.length === 0
      ? 0
      : Math.max(0, Math.min(slice.activeFindIndex, matches.length - 1));
  const activeMatch = matches[safeIndex] ?? null;

  useEffect(() => {
    const nextKey =
      activeMatch?.cellKey ??
      (activeMatch?.atPara !== undefined ? `p:${activeMatch.atPara}` : null);
    setCanvasSlice((prev) => {
      if (prev.activeFindCellKey === nextKey && prev.activeFindIndex === safeIndex) {
        return prev;
      }
      return {
        ...prev,
        activeFindIndex: safeIndex,
        activeFindCellKey: nextKey,
      };
    });
  }, [activeMatch, safeIndex]);

  const stepMatch = (delta: -1 | 1) => {
    if (matches.length === 0) return;
    const next = (safeIndex + delta + matches.length) % matches.length;
    const target = matches[next];
    const nextKey =
      target.cellKey ?? (target.atPara !== undefined ? `p:${target.atPara}` : null);
    setCanvasSlice({
      activeFindIndex: next,
      activeFindCellKey: nextKey,
    });
    scrollCanvasToTarget({
      cellKey: target.cellKey ?? null,
      atPara: target.atPara ?? null,
    });
  };

  const selectMatchAt = (index: number) => {
    const target = matches[index];
    if (!target) return;
    const nextKey =
      target.cellKey ?? (target.atPara !== undefined ? `p:${target.atPara}` : null);
    setCanvasSlice({
      activeFindIndex: index,
      activeFindCellKey: nextKey,
      selectedSeatKey: target.cellKey ?? null,
    });
    scrollCanvasToTarget({
      cellKey: target.cellKey ?? null,
      atPara: target.atPara ?? null,
    });
  };

  const handleFindKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || composingRef.current) {
      return;
    }
    if (e.key === "Enter" || e.code === "F3") {
      e.preventDefault();
      stepMatch(e.shiftKey ? -1 : 1);
    }
  };

  const handleReplaceKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || composingRef.current) {
      return;
    }
    if (e.key === "Enter" && activeMatch) {
      e.preventDefault();
      void replaceFindMatch(activeMatch, slice.findQuery, slice.replaceQuery);
    }
  };

  const replaceableCount = matches.filter((m) => m.cellKey !== undefined).length;
  const trimmedQuery = slice.findQuery.trim();

  return (
    <section
      className="rl-pane rl-pane--find"
      data-testid="pane-find"
      data-docked="true"
      aria-label={wp3t("pane_find_title", language)}
    >
      <div className="rl-find-form">
        <div className="rl-find-input-row">
          <input
            ref={findInputRef}
            type="text"
            className="rl-find-input"
            data-testid="find-query-input"
            value={slice.findQuery}
            placeholder={wp3t("find_input_placeholder", language)}
            aria-label={wp3t("find_input_placeholder", language)}
            onCompositionStart={() => {
              composingRef.current = true;
            }}
            onCompositionEnd={() => {
              composingRef.current = false;
            }}
            onChange={(e) =>
              setCanvasSlice({ findQuery: e.target.value, activeFindIndex: 0 })
            }
            onKeyDown={handleFindKeyDown}
          />
        </div>

        <div className="rl-find-nav-row">
          <span className="rl-find-count rl-num" data-testid="find-match-count">
            {trimmedQuery.length === 0
              ? wp3t("find_match_pos", language, [0, 0])
              : matches.length > 0
                ? wp3t("find_match_pos", language, [safeIndex + 1, matches.length])
                : wp3t("find_match_pos", language, [0, 0])}
          </span>
          <div className="rl-find-nav-btns">
            <button
              type="button"
              className="rl-pane-btn"
              data-testid="find-prev-btn"
              disabled={matches.length === 0}
              onClick={() => stepMatch(-1)}
            >
              {wp3t("find_prev", language)}
            </button>
            <button
              type="button"
              className="rl-pane-btn"
              data-testid="find-next-btn"
              disabled={matches.length === 0}
              onClick={() => stepMatch(1)}
            >
              {wp3t("find_next", language)}
            </button>
          </div>
        </div>

        {showReplace ? (
          <div className="rl-find-replace-box">
            <input
              ref={replaceInputRef}
              type="text"
              className="rl-find-input"
              data-testid="find-replace-input"
              value={slice.replaceQuery}
              placeholder={wp3t("replace_input_placeholder", language)}
              aria-label={wp3t("replace_input_placeholder", language)}
              onCompositionStart={() => {
                composingRef.current = true;
              }}
              onCompositionEnd={() => {
                composingRef.current = false;
              }}
              onChange={(e) => setCanvasSlice({ replaceQuery: e.target.value })}
              onKeyDown={handleReplaceKeyDown}
            />
            <div className="rl-find-replace-btns">
              <button
                type="button"
                className="rl-pane-btn"
                data-testid="replace-one-btn"
                disabled={!activeMatch || !trimmedQuery}
                onClick={() => {
                  if (!activeMatch) return;
                  void replaceFindMatch(
                    activeMatch,
                    slice.findQuery,
                    slice.replaceQuery,
                  );
                }}
              >
                {wp3t("replace_one", language)}
              </button>
              <button
                type="button"
                className="rl-pane-btn"
                data-testid="replace-all-btn"
                disabled={replaceableCount === 0 || !trimmedQuery}
                onClick={() => {
                  void replaceAllFindMatches(
                    matches,
                    slice.findQuery,
                    slice.replaceQuery,
                  );
                }}
              >
                {wp3t("replace_all", language)}
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {trimmedQuery.length > 0 && matches.length === 0 ? (
        <div className="rl-pane-empty" data-testid="find-empty">
          {wp3t("find_no_matches", language, [trimmedQuery])}
        </div>
      ) : matches.length > 0 ? (
        <ul className="rl-find-results rl-pane-scroll" role="list">
          {matches.map((m, idx) => {
            const isActive = idx === safeIndex;
            return (
              <li key={m.id} className="rl-find-row">
                <button
                  type="button"
                  className={`rl-find-hit-btn${
                    isActive ? " rl-find-hit-btn--active" : ""
                  }`}
                  data-testid={`find-match-${idx}`}
                  data-active={isActive ? "true" : undefined}
                  onClick={() => selectMatchAt(idx)}
                >
                  <span className="rl-find-hit-label">{m.label}</span>
                  <span className="rl-find-hit-snippet">
                    {m.text.replace(/\s+/g, " ").trim()}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
