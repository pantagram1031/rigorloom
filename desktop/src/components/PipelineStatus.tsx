/**
 * Status strip + 파이프라인 details. P2 verify is a sibling slide-in.
 */
import { refreshPipelineStatus } from "../actions";
import {
  PIPELINE_NOT_FOUND,
  gateStateLabel,
  gateTone,
  stagesDone,
  stripSummary,
} from "../pipelineStatus";
import { getState, setLeftRailCollapsed, useWorkspace } from "../store";
import { EmptyIconDoc, EmptyState } from "./EmptyState";
import { FillCard } from "./FillResults";
import { PosterCard } from "./PosterResults";
import { Icon } from "./Icon";
import { Tag } from "./Tag";

function togglePipelineDisclosure() {
  const wasCollapsed = getState().leftRailCollapsed;
  if (wasCollapsed) setLeftRailCollapsed(false);
  const apply = () => {
    const el = document.querySelector<HTMLDetailsElement>('[data-testid="pipeline-disclosure"]');
    if (el) el.open = !el.open;
  };
  if (wasCollapsed) requestAnimationFrame(() => requestAnimationFrame(apply));
  else apply();
}

export function PipelineStrip() {
  const status = useWorkspace((s) => s.pipelineStatus);
  const phase = useWorkspace((s) => s.pipelinePhase);
  const error = useWorkspace((s) => s.pipelineError);
  if (phase === "idle" && !status) return null;
  if (phase === "failed" && error) {
    return (
      <div className="pipeline-strip" data-testid="pipeline-strip" data-state="error">
        <button
          type="button"
          className="pipeline-strip-main"
          title="파이프라인"
          onClick={() => togglePipelineDisclosure()}
        >
          <span className="pipeline-strip-text">파이프라인 헤더를 읽지 못했습니다</span>
          <Icon name="chevron-down" />
        </button>
        <button
          type="button"
          className="pipeline-refresh btn-icon"
          data-testid="pipeline-refresh"
          title="다시 읽기"
          aria-label="다시 읽기"
          onClick={() => void refreshPipelineStatus()}
        >
          <Icon name="search" />
        </button>
      </div>
    );
  }
  if (!status?.found) return null;
  const { done, total } = stagesDone(status);
  const next = status.nextGate?.gate?.name ?? status.nextGate?.stageId ?? "없음";
  return (
    <div className="pipeline-strip" data-testid="pipeline-strip" data-state="found">
      <button
        type="button"
        className="pipeline-strip-main"
        title={stripSummary(status)}
        aria-label="파이프라인"
        onClick={() => togglePipelineDisclosure()}
      >
        <span className="pipeline-strip-text" data-testid="pipeline-strip-text">
          <span className="mono">{status.slug}</span>
          <span className="sep" />
          <span data-testid="pipeline-strip-progress">
            {done}/{total}
          </span>
          <span className="sep" />
          <span data-testid="pipeline-strip-next">{next}</span>
        </span>
        <Icon name="chevron-down" />
      </button>
      <button
        type="button"
        className="pipeline-refresh btn-icon"
        data-testid="pipeline-refresh"
        title="다시 읽기"
        aria-label="다시 읽기"
        onClick={() => void refreshPipelineStatus()}
      >
        <Icon name="search" />
      </button>
    </div>
  );
}

export function PipelinePanel() {
  const status = useWorkspace((s) => s.pipelineStatus) ?? PIPELINE_NOT_FOUND;
  const phase = useWorkspace((s) => s.pipelinePhase);
  const error = useWorkspace((s) => s.pipelineError);

  if (phase === "starting") {
    return <p className="empty">파이프라인 상태를 읽는 중입니다.</p>;
  }
  if (phase === "failed" && error) {
    return (
      <div className="section" data-testid="pipeline-panel">
        <p className="prose" data-testid="pipeline-error">
          {error.message}
        </p>
        <button type="button" className="action" data-testid="pipeline-refresh" onClick={() => void refreshPipelineStatus()}>
          다시 읽기
        </button>
      </div>
    );
  }
  if (!status.found) {
    return (
      <EmptyState
        icon={<EmptyIconDoc />}
        title="보고서 작업 폴더가 아닙니다"
        body="이 문서 위쪽으로 PIPELINE.md가 없습니다. 보고서 워크스페이스를 열면 단계와 게이트가 여기에 펼쳐집니다."
        testId="pipeline-empty"
      />
    );
  }

  return (
    <div className="pipeline-panel" data-testid="pipeline-panel">
      <div className="pipeline-panel-head">
        <span className="mono">{status.slug}</span>
        <button
          type="button"
          className="ghost btn-icon"
          data-testid="pipeline-refresh"
          onClick={() => void refreshPipelineStatus()}
        >
          <Icon name="search" />
          다시 읽기
        </button>
      </div>
      <ul className="pipeline-stages" data-testid="pipeline-stages">
        {status.stages.map((row) => (
          <li key={row.id} className="pipeline-stage" data-stage={row.id}>
            <span className="pipeline-stage-id mono">{row.id}</span>
            <span className="pipeline-stage-label">{row.label ?? row.id}</span>
            <span className="pipeline-stage-status">{row.status}</span>
            <span className="pipeline-stage-gate mono">
              {row.gate?.name ?? "—"}
            </span>
            <Tag tone={gateTone(row.gate)}>{gateStateLabel(row.gate)}</Tag>
            {row.gate?.at ? (
              <span className="pipeline-stage-at mono" title={row.gate.at}>
                {row.gate.at}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      <FillCard />
      <PosterCard />
    </div>
  );
}
