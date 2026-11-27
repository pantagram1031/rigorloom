import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
} from "react";

import { wp3t } from "../i18n/v2/wp3";
import {
  formatCellAddress,
  formatParaAddress,
  formatSeatLocation,
  legacyCellKey,
  type CanvasChangeRef,
} from "../model/page";
import {
  activeInspect,
  activeSession,
  activeDisplayText,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { deriveCellFieldLabel } from "../workspace/fieldLabels";
import { useCanvasChanges } from "../canvas/changes";
import {
  findTextPattern,
  replaceAllFindMatches,
  replaceFindMatch,
  type FindMatchItem,
} from "../canvas/actions";
import {
  getPublishedKnownPages,
  scrollCanvasToTarget,
  setCanvasSlice,
  useCanvasSlice,
  usePublishedPageSource,
} from "../canvas/controller";
import "./panes.css";

export function FindPane() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeDisplayText);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);
  const pageSource = usePublishedPageSource();

  const findInputRef = useRef<HTMLInputElement | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const composingRef = useRef(false);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const changes = useCanvasChanges(session?.sessionId ?? null, textMap);

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
    const pattern = findTextPattern(query);
    const out: FindMatchItem[] = [];
    const coveredStrings = new Set<string>();

    const knownPages =
      pageSource?.kind === "engine" ? getPublishedKnownPages() : null;

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
        const match = text.matchAll(pattern).next().value;
        if (match?.index === undefined) continue;
        const label = deriveCellFieldLabel(
          inspect,
          textMap,
          tbl.index,
          cell.addr.row,
          cell.addr.col,
          language,
        );
        const cellAddr = formatCellAddress(tbl.index, cell.addr.row, cell.addr.col);
        const cellPage = knownPages?.get(key) ?? knownPages?.get(cellAddr) ?? null;
        out.push({
          id: key,
          targetType: "cell",
          cellKey: key,
          table: tbl.index,
          row: cell.addr.row,
          col: cell.addr.col,
          label,
          locationLabel: formatSeatLocation(
            cellPage,
            tbl.index,
            cell.addr.row,
            cell.addr.col,
            language,
          ),
          text,
          matchStart: match.index,
          matchEnd: match.index + match[0].length,
        });
      }
    }

    for (const para of inspect.graph.paragraphs) {
      const pKey = `p:${para.at_para}`;
      const text = textMap[pKey]?.text ?? para.text ?? "";
      if (!text.trim() || coveredStrings.has(text.trim())) continue;
      const match = text.matchAll(pattern).next().value;
      if (match?.index === undefined) continue;
      const paraAddr = formatParaAddress(para.at_para);
      const paraPage = knownPages?.get(pKey) ?? knownPages?.get(paraAddr) ?? null;
      out.push({
        id: pKey,
        targetType: "para",
        atPara: para.at_para,
        run: 0,
        label: text.slice(0, 24),
        locationLabel:
          paraPage !== null ? wp3t("outline_page_header", language, [paraPage]) : "",
        text,
        matchStart: match.index,
        matchEnd: match.index + match[0].length,
      });
    }

    return out;
  }, [inspect, slice.findQuery, cellEffectiveChanges, textMap, language, pageSource]);

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

  const stepMatch = useCallback((delta: -1 | 1) => {
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
  }, [matches, safeIndex]);

  useEffect(() => {
    const request = slice.findRequest;
    if (request === null) return;
    if (typeof request === "number") {
      stepMatch(request);
    } else {
      const input = request === "replace" && slice.findQuery.trim()
        ? replaceInputRef.current : findInputRef.current;
      input?.focus();
      input?.select();
    }
    setCanvasSlice({ findRequest: null }, session?.sessionId);
  }, [slice.findRequest, slice.findQuery, stepMatch, session?.sessionId]);

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
    if (e.key === "Enter") {
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
