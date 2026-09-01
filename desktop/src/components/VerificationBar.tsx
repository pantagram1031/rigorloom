/**
 * The always-visible truth strip, and the only place proof state may appear.
 *
 * The proof-grade vocabulary is the strongest concept in the codebase and is
 * kept verbatim: three states, read from one canonical file, and an advisory
 * render never displayed without its qualification. This build reaches none of
 * them — `verify/*` is GAP and `candidate/list` is empty until a plan is
 * applied — so the bar says `증명 없음` and names the reason. It does not show
 * a neutral dash that could be read as "fine".
 */
import { useWorkspace } from "../store";
import type { Candidate, InspectResult, Session } from "../types";
import { Tag } from "./Tag";

function Fact({ k, v, title }: { k: string; v: React.ReactNode; title?: string }) {
  return (
    <div className="fact" title={title}>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
    </div>
  );
}

export function VerificationBar({
  session,
  inspect,
  candidates,
}: {
  session: Session | null;
  inspect: InspectResult | null;
  candidates: Candidate[];
}) {
  const status = useWorkspace((s) => s.status);
  const hash = inspect?.documentHash ?? session?.source.sha256 ?? null;
  const anomalies = inspect
    ? inspect.regions.regions.filter((r) => r.colorAnomaly || r.scriptAnomaly).length
    : 0;

  return (
    <footer className="verifybar" data-testid="verification-bar">
      <Fact
        k="원본"
        v={hash ? <span title={hash}>{hash.slice(0, 12)}</span> : "—"}
        title={hash ?? undefined}
      />
      <div className="sep" />
      <Fact
        k="후보본"
        v={
          candidates.length === 0 ? (
            <Tag tone="none">없음</Tag>
          ) : (
            <Tag tone="ok">{candidates.length}개</Tag>
          )
        }
      />
      <div className="sep" />
      {/* Never a bare colour: the label is the signal, the tone is support. */}
      <Fact
        k="렌더 증명"
        v={<Tag tone="none">증명 없음</Tag>}
        title="이 빌드는 렌더러를 조사하지도, 실행하지도 않습니다."
      />
      <Fact
        k="검증"
        v={<Tag tone="none">실행 안 함</Tag>}
        title="verify/* 는 이 런타임에 아직 없습니다."
      />
      <div className="sep" />
      <Fact
        k="채움 자리"
        v={inspect ? String(inspect.summary.fillTargetCount) : "—"}
      />
      <Fact
        k="주의"
        v={
          !inspect ? (
            "—"
          ) : anomalies === 0 ? (
            <Tag tone="ok">0</Tag>
          ) : (
            <Tag tone="warn">{anomalies}</Tag>
          )
        }
        title="색 또는 글자속성 이상이 붙은 채움 자리 수"
      />
      <div className="sep" />
      <Fact
        k="런타임"
        v={
          !status?.running ? (
            <Tag tone="bad">끊김</Tag>
          ) : !status.initialized ? (
            <Tag tone="warn">준비 중</Tag>
          ) : (
            <span>
              pid {status.pid} · {status.mode === "packaged" ? "패키지" : "개발"}
            </span>
          )
        }
      />
      <Fact
        k="자식 정리"
        v={
          status?.jobConfined === true ? (
            <Tag tone="ok">보장됨</Tag>
          ) : status?.jobConfined === false ? (
            <Tag tone="bad">실패</Tag>
          ) : (
            <Tag tone="none">확인 안 됨</Tag>
          )
        }
        title={
          status?.jobError ??
          "작업 개체로 사이드카를 묶어 두었습니다. 셸이 강제 종료되어도 함께 정리됩니다."
        }
      />
    </footer>
  );
}
