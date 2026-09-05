/**
 * 설정 — which provider, and what it needs.
 *
 * THE ONE RULE THIS PANE EXISTS TO KEEP: a secret is typed here once and is
 * never read back, never shown, never written to a settings file and never
 * carried in an event. The field has no reveal control, because a field that
 * can display a key is a field that can be screenshotted; the value goes
 * straight to the OS credential store and what the UI keeps afterwards is
 * present/absent and a byte count.
 *
 * What IS written to the config file is a reference — the name of the
 * environment variable the Agent Host will resolve, composed on the Rust side
 * and not accepted from here. The pane shows the config it produced, verbatim,
 * so the claim is inspectable rather than promised.
 *
 * 연결 확인 runs `--capabilities`, which is a local describe: no document, no
 * network, no key required. Its three-state table is rendered UNCHANGED —
 * `unknown` renders as 모름 and never as a no, because `supports()` treating an
 * unverified maybe as permission to try is precisely the bug the third state
 * was invented to prevent.
 */
import { useEffect, useState } from "react";

import {
  forgetCredential,
  probeProvider,
  refreshCredential,
  saveProviderSettings,
  storeCredential,
} from "../actions";
import * as rt from "../runtime";
import { activeStoreKey, setState, useWorkspace } from "../store";
import type { ProviderId, ProviderSettings } from "../types";
import { Tag } from "./Tag";

const PROVIDERS: Array<{ id: ProviderId; label: string; blurb: string }> = [
  {
    id: "mock",
    label: "내장 목",
    blurb: "네트워크도 시계도 없는 결정론 제공자. 같은 문서면 같은 요청을 냅니다.",
  },
  {
    id: "router",
    label: "커스텀 라우터",
    blurb: "OpenAI 호환 엔드포인트. 주소와 모델 이름을 직접 넣습니다.",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    blurb: "공식 Messages API. 실제 호출은 열쇠를 넣고 지시를 보낼 때만 일어납니다.",
  },
];

const MOCK_SCENARIOS = [
  { id: "propose-one", label: "한 칸 제안" },
  { id: "propose-invalid", label: "쓰기 전 확인에서 막히는 제안" },
  { id: "propose-then-wait", label: "제안하고 승인 대기" },
  { id: "escalate", label: "적용까지 시도 (문 앞에서 막히는 것을 봅니다)" },
];

/** The capability names the profile always carries, in the order they read. */
const CAPABILITY_LABELS: Array<[string, string]> = [
  ["text", "글 생성"],
  ["structuredToolUse", "도구 호출"],
  ["streaming", "토막 전송"],
  ["structuredOutput", "구조화 출력"],
  ["modelDiscovery", "모델 목록"],
  ["resumableThread", "대화 이어받기"],
  ["vision", "그림 입력"],
];

const STATE_LABEL: Record<string, { text: string; tone: "ok" | "bad" | "none" }> = {
  yes: { text: "예", tone: "ok" },
  no: { text: "아니오", tone: "bad" },
  unknown: { text: "모름", tone: "none" },
};

/**
 * The adapter's own credential vocabulary, rendered without translation of
 * meaning: `ah_anthropic.credential_state` answers exactly these four, and
 * `unsupported` is the one that matters — it is what the OS-store source
 * returns today, and the reason this app hands the key over as an environment
 * reference on the child process instead.
 */
const CREDENTIAL_STATE: Record<string, { text: string; tone: "ok" | "bad" | "warn" | "none" }> = {
  configured: { text: "설정됨", tone: "ok" },
  missing: { text: "없음", tone: "none" },
  not_required: { text: "필요 없음", tone: "none" },
  unsupported: { text: "이 방식은 아직 안 됩니다", tone: "warn" },
};

function credentialVerdict(profile: { notes: Record<string, unknown> }): string {
  const row = profile.notes?.credential as { state?: string } | undefined;
  return row?.state ?? "missing";
}

const OWNERSHIP: Record<string, string> = {
  none: "열쇠가 필요 없습니다",
  env_reference: "환경 변수 이름으로 참조합니다",
  os_store_reference: "운영체제 저장소 키로 참조합니다",
  provider_managed: "제공자 쪽이 인증을 갖고 있습니다",
};

export function Settings() {
  const open = useWorkspace((s) => s.settingsOpen);
  const saved = useWorkspace((s) => s.provider);
  const profile = useWorkspace((s) => s.providerProfile);
  const probePhase = useWorkspace((s) => s.probePhase);
  const probeError = useWorkspace((s) => s.probeError);
  const credential = useWorkspace((s) => s.credential);
  const host = useWorkspace((s) => s.agentHost);

  const [draft, setDraft] = useState<ProviderSettings>(saved);
  const [secret, setSecret] = useState("");
  const [config, setConfig] = useState<{ path: string; body: unknown } | null>(null);

  // Re-seed from the store whenever the pane opens: it is a dialog over shared
  // state, not a second copy of it.
  useEffect(() => {
    if (open) {
      setDraft(saved);
      setSecret("");
      void refreshCredential();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open || draft.provider === "mock") {
      setConfig(null);
      return;
    }
    void rt
      .agentHostReadConfig(draft.provider)
      .then((row) => setConfig(row.exists ? { path: row.path, body: row.config } : null))
      .catch(() => setConfig(null));
  }, [open, draft.provider, credential?.state]);

  if (!open) return null;

  const key = activeStoreKey(draft);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  async function apply(next: ProviderSettings) {
    setDraft(next);
    await saveProviderSettings(next);
  }

  return (
    <div className="sheet settings" data-testid="settings">
      <div className="sheet-head">
        <h2>설정 — 에이전트 제공자</h2>
        <span className="spacer" />
        <button className="ghost" data-testid="settings-close" onClick={() => setState({ settingsOpen: false })}>
          닫기 (Esc)
        </button>
      </div>

      <div className="sheet-body">
        <section className="section">
          <h3>에이전트 호스트</h3>
          {host?.available ? (
            <p className="prose tiny">
              <Tag tone="ok">찾음</Tag> <span className="mono">{host.mode}</span> ·{" "}
              <span className="mono" style={{ overflowWrap: "anywhere" }}>
                {host.script}
              </span>
            </p>
          ) : (
            <p className="prose tiny">
              <Tag tone="bad">없음</Tag> {host?.reason ?? "확인하지 못했습니다."}
            </p>
          )}
          <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
            제공자와 이야기하는 것은 이 별도 프로세스뿐입니다. 문서를 뜯어보는 쪽은 네트워크를
            모릅니다.
          </p>
        </section>

        <section className="section">
          <h3>제공자</h3>
          <div className="radios" role="radiogroup" aria-label="제공자">
            {PROVIDERS.map((row) => (
              <button
                key={row.id}
                className="radio"
                role="radio"
                aria-checked={draft.provider === row.id}
                data-testid={`provider-${row.id}`}
                onClick={() => void apply({ ...draft, provider: row.id })}
              >
                <span className="primary">{row.label}</span>
                <span className="secondary">{row.blurb}</span>
              </button>
            ))}
          </div>
        </section>

        {draft.provider === "mock" ? (
          <section className="section" data-testid="settings-mock">
            <h3>어떤 대본을 돌릴지</h3>
            <div className="rows">
              {MOCK_SCENARIOS.map((row) => (
                <button
                  key={row.id}
                  className="row"
                  aria-selected={draft.scenario === row.id}
                  onClick={() => void apply({ ...draft, scenario: row.id })}
                >
                  <span className="primary">{row.label}</span>
                  <span className="secondary mono">{row.id}</span>
                </button>
              ))}
            </div>
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              열쇠도 네트워크도 쓰지 않습니다. 같은 문서에 같은 대본이면 같은 요청이 나옵니다.
            </p>
          </section>
        ) : null}

        {draft.provider === "router" ? (
          <section className="section" data-testid="settings-router">
            <h3>라우터</h3>
            <label className="field">
              <span>주소</span>
              <input
                data-testid="router-baseurl"
                value={draft.router.baseUrl}
                placeholder="https://gateway.example.invalid/v1"
                onChange={(e) =>
                  setDraft({ ...draft, router: { ...draft.router, baseUrl: e.target.value } })
                }
              />
            </label>
            <label className="field">
              <span>모델</span>
              <input
                data-testid="router-model"
                value={draft.router.model}
                onChange={(e) =>
                  setDraft({ ...draft, router: { ...draft.router, model: e.target.value } })
                }
              />
            </label>
            <label className="field">
              <span>자격 증명 이름</span>
              <input
                data-testid="router-storekey"
                value={draft.router.storeKey}
                onChange={(e) =>
                  setDraft({ ...draft, router: { ...draft.router, storeKey: e.target.value } })
                }
              />
            </label>
          </section>
        ) : null}

        {draft.provider === "anthropic" ? (
          <section className="section" data-testid="settings-anthropic">
            <h3>Anthropic</h3>
            <label className="field">
              <span>모델</span>
              <input
                data-testid="anthropic-model"
                value={draft.anthropic.model}
                placeholder={
                  (profile?.model as string | undefined) ?? "비워 두면 어댑터의 기본값"
                }
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    anthropic: { ...draft.anthropic, model: e.target.value },
                  })
                }
              />
            </label>
            <label className="field">
              <span>자격 증명 이름</span>
              <input
                data-testid="anthropic-storekey"
                value={draft.anthropic.storeKey}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    anthropic: { ...draft.anthropic, storeKey: e.target.value },
                  })
                }
              />
            </label>
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              모델 이름을 비워 두면 어댑터가 고른 기본값을 씁니다. 여기에 기본값을 베껴 두면
              어댑터가 옮겨 갔을 때 이쪽만 낡습니다.
            </p>
          </section>
        ) : null}

        {dirty ? (
          <div className="section">
            <button className="action primary" data-testid="settings-save" onClick={() => void apply(draft)}>
              설정 저장
            </button>
          </div>
        ) : null}

        {draft.provider !== "mock" ? (
          <section className="section" data-testid="settings-credential">
            <h3>자격 증명</h3>
            <p className="prose tiny">
              값은 이 기계의 Windows 자격 증명 관리자에만 들어갑니다. 설정 파일에는 이름만
              적히고, 화면으로 다시 나오지 않습니다.
            </p>
            <p className="prose tiny">
              현재 상태:{" "}
              {credential?.state === "present" ? (
                <>
                  <Tag tone="ok">저장됨</Tag>{" "}
                  <span className="mono">
                    {credential.key} · {credential.bytes}바이트
                  </span>
                </>
              ) : (
                <>
                  <Tag tone="none">없음</Tag>{" "}
                  <span className="mono">{key ?? "이름 없음"}</span>
                </>
              )}
            </p>
            <label className="field">
              <span>값 붙여넣기</span>
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                data-testid="credential-input"
                value={secret}
                placeholder="여기에 붙여넣으면 곧바로 저장소로 갑니다"
                onChange={(e) => setSecret(e.target.value)}
              />
            </label>
            <div className="row-actions">
              <button
                className="action"
                data-testid="credential-save"
                disabled={secret.trim() === "" || !key}
                onClick={() => {
                  const value = secret;
                  setSecret("");
                  void storeCredential(value);
                }}
              >
                저장소에 넣기
              </button>
              {credential?.state === "present" ? (
                <button
                  className="action"
                  data-testid="credential-forget"
                  onClick={() => void forgetCredential()}
                >
                  지우기
                </button>
              ) : null}
            </div>
          </section>
        ) : null}

        <section className="section">
          <h3>연결 확인</h3>
          <div className="row-actions">
            <button
              className="action primary"
              data-testid="probe-capabilities"
              disabled={probePhase === "starting" || !host?.available}
              onClick={() => void probeProvider()}
            >
              {probePhase === "starting" ? "물어보는 중…" : "연결 확인"}
            </button>
            <span className="tiny">
              어댑터에게 “무엇을 할 수 있나”만 묻습니다. 문서도 네트워크도 건드리지 않습니다.
            </span>
          </div>

          {probeError ? (
            <div className="refusal" data-testid="probe-error">
              <p className="prose">{probeError.message}</p>
              <p className="mono tiny">{probeError.code}</p>
            </div>
          ) : null}

          {profile ? (
            <div data-testid="capability-table">
              <p className="prose tiny">
                <span className="mono">{profile.providerId}</span>
                {profile.model ? <span className="mono"> · {profile.model}</span> : null} ·{" "}
                {OWNERSHIP[profile.authOwnership] ?? profile.authOwnership}
              </p>
              {/* What the ADAPTER says about the reference, separately from
                  what the OS store says about the key. They can disagree —
                  a key saved under one name while the config points at
                  another — and one line each is how a person sees that. */}
              <p className="prose tiny" data-testid="credential-verdict">
                자격 증명 참조:{" "}
                <Tag tone={CREDENTIAL_STATE[credentialVerdict(profile)]?.tone ?? "none"}>
                  {CREDENTIAL_STATE[credentialVerdict(profile)]?.text ??
                    credentialVerdict(profile)}
                </Tag>{" "}
                <span className="mono">
                  {String(
                    (profile.notes?.credentialRef as { key?: string } | undefined)?.key ?? "—",
                  )}
                </span>
              </p>
              <table className="caps">
                <tbody>
                  {CAPABILITY_LABELS.map(([name, label]) => {
                    const row = profile.capabilities[name];
                    const state = STATE_LABEL[row?.state ?? "unknown"] ?? STATE_LABEL.unknown;
                    return (
                      <tr key={name} data-testid={`cap-${name}`}>
                        <th>{label}</th>
                        <td>
                          <Tag tone={state.tone}>{state.text}</Tag>
                        </td>
                        <td className="tiny">{row?.reason ?? ""}</td>
                        <td className="tiny mono">{row?.declaredBy ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
                모름은 아니오가 아닙니다. 어댑터가 확인하지 않았다는 뜻이고, 확인되지 않은
                기능은 시도하지 않습니다.
              </p>
              {/* The one thing a capability table cannot say for itself. */}
              <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
                토막 전송이 “예”여도 이 슬라이스에서는 글이 한 번에 옵니다. 호스트의 턴
                루프가 아직 어댑터의 stream() 을 부르지 않습니다 — 진행 상황만 실시간으로
                흐릅니다.
              </p>
            </div>
          ) : null}
        </section>

        {config ? (
          <section className="section" data-testid="settings-config">
            <h3>이 제공자가 읽을 설정 파일</h3>
            <p className="prose mono tiny" style={{ overflowWrap: "anywhere" }}>
              {config.path}
            </p>
            <pre className="tiny">{JSON.stringify(config.body, null, 2)}</pre>
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              여기에 값이 들어 있지 않다는 것을 직접 보십시오. 이름뿐입니다.
            </p>
          </section>
        ) : null}

        <section className="section" data-testid="product-legal">
          <h3>제품 정보와 호환성</h3>
          <p className="prose tiny">
            본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
          </p>
          <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
            Rigorloom은 한컴 또는 한컴오피스와 제휴하거나 그 승인을 받은 제품이 아닙니다.
            한컴오피스와 그 바이너리·SDK·글꼴·템플릿은 포함하지 않습니다. Automation 기능은
            사용자가 적법하게 설치한 한컴오피스와 해당 이용 조건이 허용하는 범위에서만 사용할 수
            있습니다.
          </p>
        </section>
      </div>
    </div>
  );
}
