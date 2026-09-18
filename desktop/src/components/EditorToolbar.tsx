/**
 * The editor strip above the document. Hangul-editor-shaped, and our own.
 *
 * EVERY FIELD IS READ-ONLY, and every field is real. See the previous
 * comments in this file's history for the 글꼴 / charPr / size honesty rules.
 */
import type { ReactNode } from "react";

import {
  applyUiZoom,
  bindFormAndOpen,
  exportApplied,
  openViaDialog,
  runCheck,
  stepUiZoom,
  toggleLeftRail,
} from "../actions";
import {
  activeText,
  canRenderPages,
  canRequestApproval,
  cellKey,
  getState,
  selectInspectorTab,
  setCenterMode,
  setChromeMenu,
  setZoom,
  useWorkspace,
  type ChromeMenu,
  type Selection,
} from "../store";
import type { InspectResult, RegionText, TypefaceByLang } from "../types";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "../ui/DropdownMenu";
import { Kbd } from "../ui/Kbd";
import { ToggleGroup, ToggleGroupItem } from "../ui/ToggleGroup";
import { Tooltip } from "../ui/Tooltip";
import { Icon } from "./Icon";
import { Tag } from "./Tag";

function ToolMenu({
  id,
  label,
  testId,
  summary,
  ariaLabel,
  iconOnly,
  children,
}: {
  id?: Exclude<ChromeMenu, null>;
  label: string;
  testId: string;
  summary?: ReactNode;
  ariaLabel?: string;
  iconOnly?: boolean;
  children: ReactNode;
}) {
  const open = useWorkspace((s) => (id ? s.chromeMenu === id : false));
  const trigger = (
    <DropdownMenuTrigger
      className={iconOnly ? "ui-btn-ghost ui-icon-btn" : undefined}
      data-testid={testId}
      aria-label={ariaLabel ?? label}
    >
      {iconOnly ? (
        <span aria-hidden="true">···</span>
      ) : (
        <>
          <span className="tool-label">{label}</span>
          {summary ? <span className="tool-value">{summary}</span> : null}
          <Icon name="chevron-down" />
        </>
      )}
    </DropdownMenuTrigger>
  );
  return (
    <DropdownMenu
      open={id ? open : undefined}
      onOpenChange={
        id
          ? (next) => {
              if (next) setChromeMenu(id);
              else if (getState().chromeMenu === id) setChromeMenu(null);
            }
          : undefined
      }
    >
      {iconOnly ? <Tooltip content={ariaLabel ?? label}>{trigger}</Tooltip> : trigger}
      <DropdownMenuContent className="toolmenu-body">
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function faceIndex(inspect: InspectResult | null): Map<string, TypefaceByLang> {
  const index = new Map<string, TypefaceByLang>();
  if (!inspect) return index;
  const add = (id: string | undefined | null, face: TypefaceByLang | null | undefined) => {
    if (!id || !face) return;
    if (!index.has(id)) index.set(id, face);
  };
  add(inspect.summary.baselineCharPr?.id, inspect.summary.baselineCharPr?.face);
  add(inspect.summary.blackCharPr?.id, inspect.summary.blackCharPr?.face);
  for (const region of inspect.regions.regions) {
    add(region.charPr, region.charPrFace);
    add(region.charPrSuggested, region.charPrSuggestedFace);
  }
  return index;
}

function faceIndexWithRuns(
  inspect: InspectResult | null,
  texts: RegionText[],
): Map<string, TypefaceByLang> {
  const index = faceIndex(inspect);
  for (const region of texts) {
    for (const run of region.runs ?? []) {
      if (run.charpr && run.charpr_face && !index.has(run.charpr)) {
        index.set(run.charpr, run.charpr_face);
      }
    }
  }
  return index;
}

function primaryFace(face: TypefaceByLang | undefined): string | null {
  return face?.hangul ?? null;
}

function allFaces(face: TypefaceByLang | undefined): string {
  if (!face) return "";
  const LANG: Record<string, string> = {
    hangul: "한글",
    latin: "영문",
    hanja: "한자",
    japanese: "일어",
    other: "기타",
    symbol: "기호",
    user: "사용자",
  };
  return Object.entries(face)
    .filter(([, name]) => !!name)
    .map(([lang, name]) => `${LANG[lang] ?? lang} ${name}`)
    .join(" · ");
}

function seatCharPr(
  selection: Selection,
  inspect: InspectResult | null,
  texts: RegionText[],
  caretRun: number | null,
): { id: string | null; suggested: string | null; where: string } {
  if (!inspect || !selection) return { id: null, suggested: null, where: "" };
  if (selection.kind === "cell") {
    const table = inspect.graph.tables.find((t) => t.index === selection.table);
    const cell = table?.cells.find(
      (c) => c.addr.row === selection.row && c.addr.col === selection.col,
    );
    return {
      id: cell?.charPr ?? null,
      suggested: cell?.charPrSuggested ?? null,
      where: cellKey(selection.table, selection.row, selection.col),
    };
  }
  if (selection.kind === "paragraph") {
    const region = texts.find((row) => row.at_para === selection.atPara);
    const run = caretRun !== null ? region?.runs?.find((r) => r.index === caretRun) : region?.runs?.[0];
    return { id: run?.charpr ?? null, suggested: null, where: `p:${selection.atPara}` };
  }
  return { id: null, suggested: null, where: `t:${selection.table}` };
}

export function EditorToolbar({ inspect }: { inspect: InspectResult | null }) {
  const mode = useWorkspace((s) => s.centerMode);
  const canRender = useWorkspace(canRenderPages);
  const zoom = useWorkspace((s) => s.zoom);
  const uiZoom = useWorkspace((s) => s.uiZoom);
  const selection = useWorkspace((s) => s.selection);
  const texts = useWorkspace(activeText);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const caret = inlineEdit?.kind === "run" ? inlineEdit : null;
  const charPr = seatCharPr(selection, inspect, texts, caret?.run ?? null);
  const queued = useWorkspace((s) => s.draft.ops.length);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applied = useWorkspace((s) => s.applied);
  const checkPhase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);
  const exportPhase = useWorkspace((s) => s.exportPhase);
  const canApprove = useWorkspace(canRequestApproval);
  const railCollapsed = useWorkspace((s) => s.leftRailCollapsed);

  const baseline = inspect?.summary.baselineCharPr ?? null;
  const hard = findings.filter((f) => f.severity === "hard").length;
  const anomalous = charPr.suggested !== null && charPr.id !== charPr.suggested;

  const faces = faceIndexWithRuns(inspect, texts);
  const typefaces = inspect?.summary.typefaces ?? null;
  const face = charPr.id ? faces.get(charPr.id) : undefined;
  const suggestedFace = charPr.suggested ? faces.get(charPr.suggested) : undefined;
  const name = primaryFace(face);
  const suggestedName = primaryFace(suggestedFace);
  const faceUnknown =
    !typefaces || typefaces.state !== "read"
      ? (typefaces?.reason ?? "이 빌드는 글꼴 이름을 읽지 못했습니다")
      : null;

  const typefaceTip = name
    ? `이 문서가 선언한 글꼴입니다 — ${allFaces(face)}`
    : faceUnknown
      ? `글꼴 이름을 읽을 수 없었습니다 — ${faceUnknown}`
      : charPr.id
        ? "이 문서는 이 글자 모양에 쓸 글꼴 이름을 선언하지 않았습니다."
        : "선택한 곳이 없습니다.";
  const sizeTip = caret?.sizePt
    ? "커서가 선 줄을 렌더러가 그린 크기입니다. 문서가 선언한 값이 아니라 지면에서 잰 값입니다."
    : "이 문서가 본문 글자 모양에 선언한 크기입니다.";
  const mismatchTip =
    suggestedName && name
      ? `이 자리는 ${name}(charPr ${charPr.id}) 을 물려받는데, 서식 검사가 권하는 본문 모양은 ${suggestedName}(charPr ${charPr.suggested}) 입니다`
      : `이 문서의 본문 모양은 charPr ${charPr.suggested} 입니다`;

  // Read-only readout of the face, charPr and size at the selection or caret.
  // It lives in the toolbar itself, never inside a menu: opening a menu moves
  // focus, and moving focus commits the seat editor, which ends the very caret
  // this readout describes. Word and 한글 keep the font box in the band for the
  // same reason.
  const formatBody = (
    <div className="tool-format" data-testid="tool-format" aria-label="서식">
      <div className="tool-group" data-testid="tool-typeface">
        <span className="tool-label">글꼴</span>
        <Tooltip content={typefaceTip}>
          <span className="tool-value" data-testid="typeface-name" data-face={name ?? ""}>
            {name ?? "—"}
          </span>
        </Tooltip>
        {!name && charPr.id ? (
          <span className="tool-note tiny" data-testid="typeface-absent">
            {faceUnknown ? "읽지 못함" : "문서가 이름을 안 밝힘"}
          </span>
        ) : null}
      </div>

      <div className="tool-group" data-testid="tool-charpr">
        <span className="tool-label">글자 모양</span>
        <Tooltip content={charPr.where || "선택한 곳이 없습니다"}>
          <span className="tool-value mono">{charPr.id ?? "—"}</span>
        </Tooltip>
        {anomalous ? (
          <Tag tone="warn" title={mismatchTip}>
            {suggestedName && name && suggestedName !== name
              ? `본문은 ${suggestedName}`
              : "본문과 다름"}
          </Tag>
        ) : null}
      </div>

      <div className="tool-group" data-testid="tool-size">
        <span className="tool-label">크기</span>
        <Tooltip content={sizeTip}>
          <span
            className="tool-value mono"
            data-testid="size-value"
            data-source={caret?.sizePt ? "render" : "baseline"}
          >
            {caret?.sizePt ? `${caret.sizePt}pt` : baseline ? `${baseline.height_pt}pt` : "—"}
          </span>
        </Tooltip>
        <span className="tool-note tiny">{caret?.sizePt ? "지면에서 잰 값" : "본문 기준"}</span>
      </div>
    </div>
  );

  const exportTip = applied
    ? "후보본과 영수증을 함께 저장합니다 (Ctrl+S)"
    : "아직 내보낼 후보본이 없습니다. 편집을 승인해 적용하면 생깁니다.";
  const pageTip = canRender
    ? "실제 페이지 그림"
    : "이 런타임에는 문서를 그림으로 그리는 방법이 아직 없습니다";
  const checkTip =
    hard > 0
      ? `오프라인 검사 · 막힘 ${hard}`
      : findings.length > 0
        ? `오프라인 검사 · ${findings.length}건`
        : "오프라인 검사를 돌립니다";
  const approveTip =
    approvalPhase === "pending"
      ? "오른쪽에서 승인하고 적용합니다"
      : canApprove
        ? "검토 탭에서 승인하고 적용합니다"
        : "입력 칸에 값을 넣으면 승인을 요청할 수 있습니다";
  const railTip = railCollapsed ? "구조 레일 펼치기 (Ctrl+B)" : "구조 레일 접기 (Ctrl+B)";

  return (
    <div className="toolbar" data-testid="editor-toolbar" role="toolbar" aria-label="편집 도구">
      <div className="tool-cluster tool-left" data-testid="tool-actions">
        <Tooltip content={railTip}>
          <Button
            variant="ghost"
            className="btn-icon tool-rail"
            data-testid="toggle-left-rail"
            aria-pressed={railCollapsed}
            aria-label={railCollapsed ? "구조 펼치기" : "구조 접기"}
            onClick={() => toggleLeftRail()}
          >
            <Icon name={railCollapsed ? "chevron-right" : "chevron-left"} />
          </Button>
        </Tooltip>
        <Tooltip content="문서를 엽니다 (Ctrl+O)">
          <Button variant="ghost" className="btn-icon" data-testid="act-open" onClick={() => void openViaDialog()}>
            <Icon name="open" />
            <span className="tool-action-label">열기</span>
          </Button>
        </Tooltip>
        <ToolMenu id="overflow" label="더 보기" testId="tool-overflow" ariaLabel="더 보기" iconOnly>
          <Tooltip content={exportTip}>
            <DropdownMenuItem
              data-testid="act-export"
              disabled={!applied || exportPhase === "starting"}
              onClick={() => {
                setChromeMenu(null);
                void exportApplied();
              }}
            >
              <Icon name="save" />
              {exportPhase === "starting" ? "내보내는 중…" : "저장/내보내기"}
              <DropdownMenuShortcut>
                <Kbd>Ctrl+S</Kbd>
              </DropdownMenuShortcut>
            </DropdownMenuItem>
          </Tooltip>
          <Tooltip content="되돌리기와 후보본 계보를 봅니다">
            <DropdownMenuItem
              data-testid="act-undo"
              onClick={() => {
                setChromeMenu(null);
                selectInspectorTab("history");
              }}
            >
              <Icon name="undo" />
              되돌리기
            </DropdownMenuItem>
          </Tooltip>
          <Tooltip content="빈 양식이나 form_profile.json을 연결해 엽니다">
            <DropdownMenuItem
              data-testid="act-bind-form"
              onClick={() => {
                setChromeMenu(null);
                void bindFormAndOpen();
              }}
            >
              <Icon name="link" />
              양식 연결
            </DropdownMenuItem>
          </Tooltip>
        </ToolMenu>
      </div>

      <div className="tool-cluster tool-center">
        <ToggleGroup
          className="modeswitch"
          value={mode}
          onValueChange={(v) => setCenterMode(v as "text" | "page")}
          aria-label="가운데 화면 모드"
        >
          <Tooltip content="문서의 글과 표를 읽기 순서로">
            <ToggleGroupItem value="text" data-testid="mode-text">
              본문
            </ToggleGroupItem>
          </Tooltip>
          <Tooltip content={pageTip}>
            <ToggleGroupItem value="page" data-testid="mode-page" disabled={!canRender}>
              페이지
            </ToggleGroupItem>
          </Tooltip>
        </ToggleGroup>
        <ToolMenu
          id="zoom"
          label="배율"
          testId="tool-zoom"
          summary={`${Math.round(zoom * 100)}%`}
          ariaLabel="배율"
        >
          <div className="tool-group zoomer">
            <span className="tool-label">문서</span>
            <Button variant="ghost" size="sm" aria-label="문서 축소" disabled={zoom <= 0.5} onClick={() => setZoom(zoom - 0.1)}>
              −
            </Button>
            <Tooltip content="100% 로 되돌립니다">
              <Button variant="ghost" size="sm" className="tool-value mono" data-testid="zoom-value" onClick={() => setZoom(1)}>
                {Math.round(zoom * 100)}%
              </Button>
            </Tooltip>
            <Button variant="ghost" size="sm" aria-label="문서 확대" disabled={zoom >= 4} onClick={() => setZoom(zoom + 0.1)}>
              +
            </Button>
          </div>
          <div className="tool-group zoomer" data-testid="tool-uizoom">
            <span className="tool-label">화면</span>
            <Tooltip content="Ctrl+−">
              <Button
                variant="ghost"
                size="sm"
                aria-label="화면 축소"
                disabled={uiZoom <= 0.5}
                onClick={() => stepUiZoom(-1)}
              >
                −
                <DropdownMenuShortcut>
                  <Kbd>Ctrl+−</Kbd>
                </DropdownMenuShortcut>
              </Button>
            </Tooltip>
            <Tooltip content="Ctrl+0 으로 되돌립니다">
              <Button
                variant="ghost"
                size="sm"
                className="tool-value mono"
                data-testid="uizoom-value"
                disabled={uiZoom === 1}
                onClick={() => void applyUiZoom(1)}
              >
                {Math.round(uiZoom * 100)}%
              </Button>
            </Tooltip>
            <Tooltip content="Ctrl+=">
              <Button
                variant="ghost"
                size="sm"
                aria-label="화면 확대"
                disabled={uiZoom >= 2}
                onClick={() => stepUiZoom(1)}
              >
                +
                <DropdownMenuShortcut>
                  <Kbd>Ctrl+=</Kbd>
                </DropdownMenuShortcut>
              </Button>
            </Tooltip>
          </div>
        </ToolMenu>
      </div>

      <div className="tool-cluster tool-right">
        {formatBody}
        <Tooltip content={checkTip}>
          <Button
            variant="secondary"
            className="btn-icon"
            data-testid="toolbar-check"
            disabled={!inspect || checkPhase === "starting"}
            onClick={() => void runCheck()}
          >
            <Icon name="search" />
            <span className="tool-action-label">{checkPhase === "starting" ? "검사 중" : "검사"}</span>
          </Button>
        </Tooltip>
        <Tooltip content={approveTip}>
          <Button
            variant="secondary"
            className={approvalPhase === "pending" ? "btn-icon point" : "btn-icon"}
            data-testid="act-approve"
            disabled={approvalPhase !== "pending" && !canApprove}
            onClick={() => {
              selectInspectorTab("review");
              window.requestAnimationFrame(() => {
                document
                  .querySelector('[data-testid="approve-and-apply"]')
                  ?.scrollIntoView({ block: "center" });
              });
            }}
          >
            <Icon name="check" />
            <span className="tool-action-label">
              {approvalPhase === "pending" ? "승인 대기" : "승인"}
            </span>
            <Badge
              variant="secondary"
              className="tool-badge"
              data-testid="tool-state"
              hidden={queued === 0}
            >
              {queued}
            </Badge>
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
