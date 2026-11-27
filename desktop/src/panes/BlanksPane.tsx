import { Fragment, useMemo, useState } from "react";

import { wp3t } from "../i18n/v2/wp3";
import {
  detectDocumentSeats,
  groupSeatsByLocation,
  resolveSeatPages,
  type PageSeat,
  type SeatLocationGroup,
} from "../model/page";
import {
  activeInspect,
  activeSession,
  activeDisplayText,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { getShell, setShell } from "../shell/shellState";
import { useCanvasChanges } from "../canvas/changes";
import { beginCellEditV2 } from "../canvas/actions";
import {
  getPublishedKnownPages,
  scrollCanvasToTarget,
  setCanvasSlice,
  useCanvasSlice,
  usePublishedPageSource,
} from "../canvas/controller";
import "./panes.css";

export function BlanksPane() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeDisplayText);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);
  const pageSource = usePublishedPageSource();

  // `J1 §3` & `BlanksPane`: receiving-agency blanks start collapsed by default.
  const [agencyOpen, setAgencyOpen] = useState(false);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const changes = useCanvasChanges(session?.sessionId ?? null, textMap);

  const seats = useMemo(() => {
    if (!inspect) return [];
    const detected = detectDocumentSeats(inspect, textMap, changes, language);
    return resolveSeatPages(
      detected,
      pageSource,
      language,
      pageSource?.kind === "engine" ? getPublishedKnownPages() : undefined,
    );
  }, [inspect, textMap, changes, language, pageSource]);

  const primarySeats = useMemo(
    () => seats.filter((s) => s.group === "primary"),
    [seats],
  );
  const agencySeats = useMemo(
    () => seats.filter((s) => s.group === "agency"),
    [seats],
  );
  const primaryGroups = useMemo(
    () => groupSeatsByLocation(primarySeats, language),
    [primarySeats, language],
  );
  const agencyGroups = useMemo(
    () => groupSeatsByLocation(agencySeats, language),
    [agencySeats, language],
  );

  const counterPool = primarySeats.length > 0 ? primarySeats : seats;
  const filledCount = counterPool.filter((s) => s.filled).length;
  const totalCount = counterPool.length;

  const handleHover = (seat: PageSeat | null) => {
    if (!seat) {
      setCanvasSlice({ hoveredSeatKey: null, hoveredSeatLabel: null });
      return;
    }
    setCanvasSlice({
      hoveredSeatKey: seat.key,
      hoveredSeatLabel: `${seat.displayLabel} · ${seat.locationLabel}`,
    });
  };

  const handleActivate = (seat: PageSeat) => {
    if (getShell().breakpoint === "narrow") setShell({ narrowDrawerOpen: false });
    setCanvasSlice({
      selectedSeatKey: seat.key,
      hoveredSeatKey: seat.key,
      hoveredSeatLabel: `${seat.displayLabel} · ${seat.locationLabel}`,
    });
    scrollCanvasToTarget({ cellKey: seat.key });
    if (inspect) {
      beginCellEditV2(seat.table, seat.row, seat.col, {
        inspect,
        texts: [...texts],
      });
    }
  };

  const renderSeatRow = (seat: PageSeat) => {
    const isActive =
      slice.selectedSeatKey === seat.key || slice.hoveredSeatKey === seat.key;
    const preview = seat.filled
      ? seat.currentText.replace(/\s+/g, " ").trim()
      : "";

    return (
      <li key={seat.id} className="rl-blank-row">
        <button
          type="button"
          className={`rl-blank-btn${isActive ? " rl-blank-btn--active" : ""}`}
          data-testid={`blank-seat-${seat.address}`}
          data-seat-key={seat.key}
          data-seat-filled={seat.filled ? "true" : "false"}
          data-active={isActive ? "true" : undefined}
          onMouseEnter={() => handleHover(seat)}
          onMouseLeave={() => handleHover(null)}
          onFocus={() => handleHover(seat)}
          onBlur={() => handleHover(null)}
          onClick={() => handleActivate(seat)}
        >
          <span className="rl-blank-line1">
            <span
              className={`rl-blank-dot${
                seat.filled ? " rl-blank-dot--filled" : " rl-blank-dot--empty"
              }`}
              aria-hidden="true"
            />
            <span className="rl-blank-label">{seat.displayLabel}</span>
            {preview ? (
              <span className="rl-blank-preview" title={seat.currentText}>
                {preview}
              </span>
            ) : null}
          </span>
          <span className="rl-blank-loc rl-num">{seat.cellLocationLabel}</span>
        </button>
      </li>
    );
  };

  const renderSeatGroups = (groups: readonly SeatLocationGroup<PageSeat>[]) =>
    groups.map((group) => (
      <Fragment key={group.key}>
        <li
          className="rl-blanks-group-hdr rl-num"
          data-testid="blanks-group-heading"
          data-group-key={group.key}
          role="presentation"
        >
          {group.heading}
        </li>
        {group.seats.map(renderSeatRow)}
      </Fragment>
    ));

  return (
    <section
      className="rl-pane rl-pane--blanks"
      data-testid="pane-blanks"
      data-docked="true"
      aria-label={wp3t("pane_blanks_title", language)}
    >
      <div className="rl-pane-header rl-num" data-testid="blanks-counter">
        {wp3t("blanks_counter", language, [filledCount, totalCount])}
      </div>

      {seats.length === 0 ? (
        <div className="rl-pane-empty" data-testid="blanks-empty">
          {wp3t("blanks_empty", language)}
        </div>
      ) : (
        <div className="rl-pane-scroll">
          {primarySeats.length > 0 ? (
            <ul className="rl-blanks-list" role="list">
              {renderSeatGroups(primaryGroups)}
            </ul>
          ) : null}

          {agencySeats.length > 0 ? (
            <div className="rl-blanks-agency-group">
              <button
                type="button"
                className="rl-blanks-group-toggle"
                data-testid="blanks-agency-toggle"
                aria-expanded={agencyOpen}
                onClick={() => setAgencyOpen((v) => !v)}
              >
                <span className="rl-blanks-caret" aria-hidden="true">
                  {agencyOpen ? "▾" : "▸"}
                </span>
                <span className="rl-blanks-group-title">
                  {wp3t("blanks_agency_group", language)}
                </span>
                <span className="rl-blanks-group-count rl-num">
                  {agencySeats.length}
                </span>
              </button>
              {agencyOpen ? (
                <ul
                  className="rl-blanks-list rl-blanks-list--agency"
                  data-testid="blanks-agency-list"
                  role="list"
                >
                  {renderSeatGroups(agencyGroups)}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
