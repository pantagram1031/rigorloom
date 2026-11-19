import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import {
  closeOperatorModal,
  forgetCredential,
  loadProviderSettings,
  probeProvider,
  refreshAgentHost,
  refreshCredential,
  saveProviderSettings,
  sendInstruction,
  stopInstruction,
  storeCredential,
} from "../actions";
import { errorCodeMessage, t, type VocabularyKey } from "../i18n/vocabulary";
import * as rt from "../runtime";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  activeStoreKey,
  composerBlocker,
  composerDraftOf,
  getState,
  setComposerDraft,
  useComposerDraftText,
  useWorkspace,
  writeComposerDraft,
} from "../store";
import type {
  Activity,
  HostRunPayload,
  ProviderId,
  ProviderProfile,
  ProviderSettings,
  RuntimeEvent,
  Turn,
  UiLanguage,
} from "../types";
import { submitComposerDraft } from "../workspace/composerDraft";
import { DetailDisclosure } from "./DetailDisclosure";

type OperatorTab = "agent" | "events" | "credentials";

const PROVIDERS: ReadonlyArray<{
  id: ProviderId;
  labelKey: VocabularyKey;
  blurbKey: VocabularyKey;
}> = [
  {
    id: "mock",
    labelKey: "operator_provider_mock_label",
    blurbKey: "operator_provider_mock_blurb",
  },
  {
    id: "router",
    labelKey: "operator_provider_router_label",
    blurbKey: "operator_provider_router_blurb",
  },
  {
    id: "anthropic",
    labelKey: "operator_provider_anthropic_label",
    blurbKey: "operator_provider_anthropic_blurb",
  },
];

const MOCK_SCENARIOS: ReadonlyArray<{ id: string; labelKey: VocabularyKey }> = [
  { id: "propose-one", labelKey: "operator_scenario_propose_one" },
  { id: "propose-invalid", labelKey: "operator_scenario_propose_invalid" },
  { id: "propose-then-wait", labelKey: "operator_scenario_propose_wait" },
  { id: "escalate", labelKey: "operator_scenario_escalate" },
];

const CAPABILITY_ROWS: ReadonlyArray<[string, VocabularyKey]> = [
  ["text", "operator_cap_text"],
  ["structuredToolUse", "operator_cap_tools"],
  ["streaming", "operator_cap_streaming"],
  ["structuredOutput", "operator_cap_structured"],
  ["modelDiscovery", "operator_cap_models"],
  ["resumableThread", "operator_cap_thread"],
  ["vision", "operator_cap_vision"],
];

const OWNERSHIP_KEYS: Record<string, VocabularyKey> = {
  none: "operator_own_none",
  env_reference: "operator_own_env",
  os_store_reference: "operator_own_os",
  provider_managed: "operator_own_managed",
};

const CRED_VERDICT_KEYS: Record<string, VocabularyKey> = {
  configured: "operator_cred_configured",
  missing: "operator_cred_missing",
  not_required: "operator_cred_not_required",
  unsupported: "operator_cred_unsupported",
};

function capStateText(state: string, language: UiLanguage): string {
  if (state === "yes") return t("operator_state_yes", language);
  if (state === "no") return t("operator_state_no", language);
  return t("operator_state_unknown", language);
}

function credentialVerdict(profile: ProviderProfile): string {
  const row = profile.notes?.credential as { state?: string } | undefined;
  return row?.state ?? "missing";
}

function describeEvent(event: RuntimeEvent, language: UiLanguage): string {
  const d = (event.detail ?? event) as Record<string, unknown>;
  switch (event.kind) {
    case "session.opened":
      return t("operator_event_opened", language, [String(d.sourceName ?? "")]);
    case "plan.proposed":
      return t("operator_event_proposed", language, [
        String(d.ops ?? "?"),
        String(d.proposer ?? ""),
      ]);
    case "plan.validated":
      return d.ok === true
        ? t("operator_event_validated_ok", language)
        : t("operator_event_validated_fail", language);
    case "approval.requested":
      return t("operator_event_approval_req", language, [String(d.requestedBy ?? "")]);
    case "approval.resolved":
      return d.state === "approved"
        ? t("operator_event_approved", language, [String(d.approver ?? "")])
        : t("operator_event_rejected", language, [String(d.approver ?? "")]);
    case "plan.applied":
      return t("operator_event_applied", language);
    case "candidate.published":
      return t("operator_event_candidate", language, [
        d.acceptance === true
          ? t("operator_event_check_pass", language)
          : t("operator_event_check_fail", language),
      ]);
    case "pdf.prepared":
      return t("operator_event_pdf", language);
    default:
      return event.kind;
  }
}

function describeActivity(item: Activity): string {
  if (item.kind === "lifecycle" || item.kind === "log") return item.text ?? "";
  const frame = item.frame as { kind?: string; method?: string } | null;
  return frame?.method ?? frame?.kind ?? item.kind;
}

function turnStatusLabel(turn: Turn, language: UiLanguage): string {
  if (turn.phase === "starting") return t("operator_turn_working", language);
  if (turn.payload?.providerFault) return t("operator_turn_fault", language);
  if (turn.phase === "failed") return t("operator_turn_failed", language);
  if (turn.payload?.plan) return t("operator_turn_plan_ready", language);
  return t("operator_turn_no_plan", language);
}

function renderPlanNote(turn: Turn, payload: HostRunPayload, language: UiLanguage): string | null {
  if (!payload.plan) return null;
  if (turn.planId) {
    return t("operator_turn_plan_adopted", language);
  }
  return t("operator_turn_plan_not_queued", language);
}

/**
 * Shared composer bar for the operator modal. Reads and mutates the active
 * document's draft in the workspace store so unsent text survives closing or
 * switching views, and stays with the document it was typed for.
 */
function OperatorAgentComposer({ language }: { language: UiLanguage }) {
  const text = useComposerDraftText();
  const activeTurn = useWorkspace((s) => s.activeTurn);
  const blocker = useWorkspace(composerBlocker);
  const composingRef = useRef(false);

  const canSend = text.trim().length > 0 && blocker === null && activeTurn === null;

  async function submitDraft() {
    const doc = getState().activeSessionId;
    await submitComposerDraft({
      read: () => composerDraftOf(doc),
      write: (draft) => writeComposerDraft(draft, doc),
      send: sendInstruction,
    });
  }

  function handleFormSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    void submitDraft();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || composingRef.current) {
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (canSend) void submitDraft();
    }
  }

  const blockedMessage =
    blocker && blocker !== "busy"
      ? blocker === "no_document"
        ? t("operator_no_open_doc", language)
        : errorCodeMessage(blocker, language)
      : null;

  return (
    <form className="composer" data-testid="composer" onSubmit={handleFormSubmit}>
      <textarea
        data-testid="composer-input"
        rows={3}
        value={text}
        disabled={activeTurn !== null}
        placeholder={t("operator_prompt_placeholder", language)}
        aria-label={t("operator_prompt_placeholder", language)}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={(e) => {
          composingRef.current = false;
          setComposerDraft(e.currentTarget.value);
        }}
        onChange={(e) => setComposerDraft(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      <div className="composer-actions">
        <button
          type="submit"
          className="action primary"
          data-testid="agent-run-btn"
          disabled={!canSend}
        >
          {activeTurn !== null
            ? t("operator_turn_working", language)
            : t("operator_prompt_submit", language)}
        </button>

        {activeTurn !== null ? (
          <button
            type="button"
            className="action"
            data-testid="agent-stop-btn"
            onClick={() => void stopInstruction()}
          >
            {t("operator_prompt_stop", language)}
          </button>
        ) : null}

        <button
          type="button"
          className="action"
          data-testid="agent-status-btn"
          onClick={() => void refreshAgentHost()}
        >
          {t("operator_host_status_btn", language)}
        </button>
      </div>

      {blockedMessage ? (
        <p className="note" data-testid="composer-note">
          {t("operator_composer_blocked", language, [blockedMessage])}
        </p>
      ) : null}
    </form>
  );
}

function OperatorAgentTab({ language }: { language: UiLanguage }) {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const candidates = useWorkspace(activeCandidates);
  const host = useWorkspace((s) => s.agentHost);
  const turns = useWorkspace((s) => s.turns);

  return (
    <div className="operator-agent-panel" data-testid="operator-agent-panel">
      <section className="section">
        <div className="row-actions">
          <strong>{t("operator_host_heading", language)}</strong>
          <span className="mono" data-testid="agent-host-status">
            {host?.available
              ? `${t("operator_host_available", language)}${host.mode ? ` (${host.mode})` : ""}`
              : `${t("operator_host_unavailable", language)}: ${host?.reason ?? t("operator_host_unknown_reason", language)}`}
          </span>
        </div>
        <p className="tiny">{t("operator_host_boundary_note", language)}</p>
        <p className="tiny" data-testid="operator-session-summary">
          {session
            ? t("operator_session_summary", language, [
                session.source.name,
                candidates.length,
              ])
            : t("operator_no_open_doc", language)}
          {inspect ? ` (${inspect.summary.fillTargetCount})` : ""}
        </p>
      </section>

      <OperatorAgentComposer language={language} />

      <section className="section" data-testid="operator-turns-list">
        {turns.length === 0 ? (
          <p className="empty">{t("operator_turns_empty", language)}</p>
        ) : (
          turns.map((turn) => {
            const payload = turn.payload;
            const planNote = payload ? renderPlanNote(turn, payload, language) : null;
            return (
              <article className="turn" key={turn.id} data-testid={`turn-${turn.id}`}>
                <div className="head">
                  <span className="asked">{turn.instruction}</span>
                  <span className="tiny mono">{turn.provider}</span>
                  <span className="tiny">{turnStatusLabel(turn, language)}</span>
                  {payload ? (
                    <span className="tiny">
                      {t("operator_turn_count", language, [payload.turns])}
                    </span>
                  ) : null}
                </div>

                {payload?.closingText ? (
                  <p className="said" data-testid="turn-said">
                    {payload.closingText}
                  </p>
                ) : null}

                {payload?.providerFault ? (
                  <div className="refusal" data-testid="turn-fault">
                    <p>{`${payload.providerFault.code}: ${payload.providerFault.message}`}</p>
                    <p className="tiny">{t("operator_turn_fault_note", language)}</p>
                  </div>
                ) : null}

                {turn.error ? (
                  <div className="refusal" data-testid="turn-error">
                    <p>{`${turn.error.code}: ${turn.error.message}`}</p>
                  </div>
                ) : null}

                {planNote ? <p className="gate">{planNote}</p> : null}

                {payload?.neverCompiled && payload.neverCompiled.length > 0 ? (
                  <p className="tiny">
                    {t("operator_turn_never_compiled", language, [
                      payload.neverCompiled.join(", "),
                    ])}
                  </p>
                ) : null}

                {turn.events.length > 0 ? (
                  <DetailDisclosure
                    label={t("operator_turn_events_summary", language, [turn.events.length])}
                  >
                    <pre>{JSON.stringify(turn.events, null, 2)}</pre>
                  </DetailDisclosure>
                ) : null}
              </article>
            );
          })
        )}
      </section>
    </div>
  );
}

function OperatorEventsTab({ language }: { language: UiLanguage }) {
  const session = useWorkspace(activeSession);
  const events = useWorkspace((s) => s.events);
  const eventPhase = useWorkspace((s) => s.eventPhase);
  const eventError = useWorkspace((s) => s.eventError);
  const subscription = useWorkspace((s) => s.eventSubscription);
  const activity = useWorkspace((s) => s.activity);

  if (!session) {
    return <p className="modal-empty">{t("operator_no_session", language)}</p>;
  }

  return (
    <div className="timeline" data-testid="timeline">
      <div className="row-actions">
        <strong>{t("operator_events_heading", language)}</strong>
        <span className="tiny" data-testid="events-total">
          {t("operator_events_count", language, [events.length])}
        </span>
        <span className="tiny">
          {subscription
            ? t("operator_events_live", language)
            : eventPhase === "failed"
              ? t("operator_events_disconnected", language)
              : t("operator_events_idle", language)}
        </span>
      </div>

      {eventError ? (
        <div className="refusal">
          <p>{t("operator_events_sub_error", language)}</p>
          <p className="tiny">{`${eventError.code}: ${eventError.message}`}</p>
        </div>
      ) : null}

      {events.length === 0 ? (
        <p className="empty">{t("operator_events_empty", language)}</p>
      ) : (
        events.map((ev) => (
          <article className="card" key={ev.seq} data-testid={`event-${ev.seq}`}>
            <div className="head">
              <span className="mono">{`#${ev.seq}`}</span>
              <span className="mono">{ev.kind}</span>
              <span className="when mono">{ev.at}</span>
            </div>
            <p className="said">{describeEvent(ev, language)}</p>
            <DetailDisclosure label={t("detail_raw_log", language)}>
              <pre>{JSON.stringify(ev, null, 2)}</pre>
            </DetailDisclosure>
          </article>
        ))
      )}

      <DetailDisclosure
        testId="protocol-chatter"
        label={t("operator_protocol_chatter", language, [activity.length])}
      >
        <p className="tiny">{t("operator_protocol_note", language)}</p>
        <pre>
          {activity
            .slice(-60)
            .map((a) => `[${a.seq}] ${a.kind}: ${describeActivity(a)}`)
            .join("\n")}
        </pre>
      </DetailDisclosure>
    </div>
  );
}

function OperatorCredentialsTab({
  open,
  language,
}: {
  open: boolean;
  language: UiLanguage;
}) {
  const saved = useWorkspace((s) => s.provider);
  const profile = useWorkspace((s) => s.providerProfile);
  const probePhase = useWorkspace((s) => s.probePhase);
  const probeError = useWorkspace((s) => s.probeError);
  const credential = useWorkspace((s) => s.credential);

  const [draft, setDraft] = useState<ProviderSettings>(saved);
  const [secret, setSecret] = useState("");
  const [config, setConfig] = useState<{ path: string; body: unknown } | null>(null);

  useEffect(() => {
    if (!open) return;
    void loadProviderSettings();
    setSecret("");
  }, [open]);

  useEffect(() => {
    setDraft(saved);
  }, [saved]);

  useEffect(() => {
    if (!open || draft.provider === "mock") {
      setConfig(null);
      return;
    }
    void rt
      .agentHostReadConfig(draft.provider)
      .then((row) => setConfig(row.exists ? { path: row.path, body: row.config } : null))
      .catch(() => setConfig(null));
  }, [open, draft.provider, credential?.state, saved]);

  const key = activeStoreKey(draft);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  async function applySettings(next: ProviderSettings) {
    setDraft(next);
    await saveProviderSettings(next);
  }

  async function handleStoreCredential() {
    const trimmed = secret.trim();
    if (!trimmed) return;
    await saveProviderSettings(draft);
    const ok = await storeCredential(trimmed);
    if (ok) setSecret("");
  }

  const verdictKey = profile ? credentialVerdict(profile) : "missing";
  const verdictVocab = CRED_VERDICT_KEYS[verdictKey] ?? "operator_cred_missing";
  const ownershipVocab = profile
    ? OWNERSHIP_KEYS[profile.authOwnership]
    : undefined;

  return (
    <div className="settings settings-embedded" data-testid="settings">
      <section className="section">
        <h3>{t("operator_provider_heading", language)}</h3>
        <div
          className="radios"
          role="radiogroup"
          aria-label={t("operator_provider_heading", language)}
        >
          {PROVIDERS.map((row) => (
            <button
              key={row.id}
              type="button"
              className="radio"
              role="radio"
              aria-checked={draft.provider === row.id}
              data-testid={`provider-${row.id}`}
              onClick={() => void applySettings({ ...draft, provider: row.id })}
            >
              <span className="primary">{t(row.labelKey, language)}</span>
              <span className="secondary">{t(row.blurbKey, language)}</span>
            </button>
          ))}
        </div>
      </section>

      {draft.provider === "mock" ? (
        <section className="section" data-testid="settings-mock">
          <h3>{t("operator_scenario_heading", language)}</h3>
          <label className="field">
            <span>{t("operator_scenario_heading", language)}</span>
            <select
              data-testid="mock-scenario"
              value={draft.scenario}
              onChange={(e) =>
                void applySettings({ ...draft, scenario: e.target.value })
              }
            >
              {MOCK_SCENARIOS.map((row) => (
                <option key={row.id} value={row.id}>
                  {t(row.labelKey, language)}
                </option>
              ))}
            </select>
          </label>
          <p className="tiny">{t("operator_scenario_note", language)}</p>
        </section>
      ) : null}

      {draft.provider === "router" ? (
        <section className="section" data-testid="settings-router">
          <h3>{t("operator_router_heading", language)}</h3>
          <label className="field">
            <span>{t("operator_field_base_url", language)}</span>
            <input
              type="text"
              data-testid="router-config"
              value={draft.router.baseUrl}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  router: { ...draft.router, baseUrl: e.target.value },
                })
              }
            />
          </label>
          <label className="field">
            <span>{t("operator_field_model", language)}</span>
            <input
              type="text"
              data-testid="router-role"
              value={draft.router.model}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  router: { ...draft.router, model: e.target.value },
                })
              }
            />
          </label>
          <label className="field">
            <span>{t("operator_field_store_key", language)}</span>
            <input
              type="text"
              data-testid="router-fallback"
              value={draft.router.storeKey}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  router: { ...draft.router, storeKey: e.target.value },
                })
              }
            />
          </label>
        </section>
      ) : null}

      {draft.provider === "anthropic" ? (
        <section className="section" data-testid="settings-anthropic">
          <h3>{t("operator_anthropic_heading", language)}</h3>
          <label className="field">
            <span>{t("operator_field_model", language)}</span>
            <input
              type="text"
              data-testid="anthropic-model"
              placeholder={
                (profile?.model as string | undefined) ??
                t("operator_anthropic_model_placeholder", language)
              }
              value={draft.anthropic.model}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  anthropic: { ...draft.anthropic, model: e.target.value },
                })
              }
            />
          </label>
          <label className="field">
            <span>{t("operator_field_store_key", language)}</span>
            <input
              type="text"
              data-testid="anthropic-store-key"
              value={draft.anthropic.storeKey}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  anthropic: { ...draft.anthropic, storeKey: e.target.value },
                })
              }
            />
          </label>
          <p className="tiny">{t("operator_model_empty_note", language)}</p>
        </section>
      ) : null}

      <div className="row-actions">
        <button
          type="button"
          className="action primary"
          data-testid="settings-save"
          onClick={() => void applySettings(draft)}
        >
          {t("operator_save_settings", language)}
        </button>
        {dirty ? (
          <span className="tiny">{t("operator_settings_dirty", language)}</span>
        ) : null}
      </div>

      <section className="section" data-testid="settings-credential">
        <h3>{t("operator_credential_heading", language)}</h3>
        <p className="tiny">{t("operator_credential_note", language)}</p>
        <p className="tiny" data-testid="credential-status">
          {`${t("operator_credential_status_label", language)}: `}
          {credential?.state === "present"
            ? t("operator_credential_stored", language, [
                credential.key,
                credential.bytes ?? 0,
              ])
            : t("operator_credential_absent", language, [
                key ?? t("operator_credential_unnamed", language),
              ])}
        </p>

        <label className="field">
          <span>{t("operator_credential_paste_label", language)}</span>
          <input
            type="password"
            autoComplete="off"
            data-testid="credential-input"
            placeholder={t("operator_credential_placeholder", language)}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
        </label>

        <div className="row-actions">
          <button
            type="button"
            className="action"
            data-testid="credential-store"
            disabled={!key || secret.trim().length === 0}
            onClick={() => void handleStoreCredential()}
          >
            {t("operator_credential_store_btn", language)}
          </button>
          <button
            type="button"
            className="action"
            data-testid="credential-forget"
            disabled={!key || credential?.state !== "present"}
            onClick={() => void forgetCredential()}
          >
            {t("operator_credential_forget_btn", language)}
          </button>
        </div>
      </section>

      <section className="section">
        <h3>{t("operator_probe_heading", language)}</h3>
        <div className="row-actions">
          <button
            type="button"
            className="action"
            data-testid="probe-provider"
            disabled={probePhase === "starting"}
            onClick={() => void probeProvider()}
          >
            {probePhase === "starting"
              ? t("operator_probe_busy", language)
              : t("operator_probe_btn", language)}
          </button>
          <span className="tiny">{t("operator_probe_note", language)}</span>
        </div>

        {probeError ? (
          <div className="refusal" data-testid="probe-error">
            <p>{`${probeError.code}: ${probeError.message}`}</p>
          </div>
        ) : null}

        {profile ? (
          <div data-testid="capability-table">
            <p className="tiny">
              {profile.model
                ? `${t("operator_cap_model_prefix", language, [profile.model])} · `
                : ""}
              {ownershipVocab ? t(ownershipVocab, language) : profile.authOwnership}
            </p>
            <p className="tiny" data-testid="credential-verdict">
              {`${t("operator_cap_verdict_label", language)}: ${t(verdictVocab, language)}`}
            </p>
            <table className="caps">
              <thead>
                <tr>
                  <th>{t("operator_cap_th_capability", language)}</th>
                  <th>{t("operator_cap_th_supported", language)}</th>
                  <th>{t("operator_cap_th_reason", language)}</th>
                  <th>{t("operator_cap_th_source", language)}</th>
                </tr>
              </thead>
              <tbody>
                {CAPABILITY_ROWS.map(([name, labelKey]) => {
                  const row = profile.capabilities[name];
                  return (
                    <tr key={name} data-testid={`cap-${name}`}>
                      <th>{t(labelKey, language)}</th>
                      <td>{capStateText(row?.state ?? "unknown", language)}</td>
                      <td className="tiny">{row?.reason ?? "-"}</td>
                      <td className="tiny mono">{row?.declaredBy ?? "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="section" data-testid="settings-config">
        <h3>{t("operator_config_heading", language)}</h3>
        <p className="tiny">{t("operator_config_note", language)}</p>
        {config ? (
          <>
            <p className="tiny mono">{config.path}</p>
            <pre>{JSON.stringify(config.body, null, 2)}</pre>
          </>
        ) : (
          <p className="empty">{t("operator_config_empty", language)}</p>
        )}
      </section>
    </div>
  );
}

export function OperatorAgentModal() {
  const open = useWorkspace((s) => s.operatorModalOpen);
  const language = useWorkspace((s) => s.language);
  const [tab, setTab] = useState<OperatorTab>("agent");

  useEffect(() => {
    if (!open) return;
    void refreshCredential();
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="dialog-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("operator_modal_title", language)}
      data-testid="operator-agent-modal"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeOperatorModal();
      }}
    >
      <div className="dialog-card dialog--operator">
        <header className="dialog-head">
          <div>
            <h2 className="dialog-title">{t("operator_modal_title", language)}</h2>
            <div className="operator-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "agent"}
                data-testid="operator-tab-agent"
                className={`operator-tab${tab === "agent" ? " is-active" : ""}`}
                onClick={() => setTab("agent")}
              >
                {t("operator_tab_agent", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "events"}
                data-testid="operator-tab-events"
                className={`operator-tab${tab === "events" ? " is-active" : ""}`}
                onClick={() => setTab("events")}
              >
                {t("operator_tab_events", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "credentials"}
                data-testid="operator-tab-credentials"
                className={`operator-tab${tab === "credentials" ? " is-active" : ""}`}
                onClick={() => setTab("credentials")}
              >
                {t("operator_tab_credentials", language)}
              </button>
            </div>
          </div>
          <button
            type="button"
            className="dialog-close"
            data-testid="operator-modal-close"
            aria-label={t("operator_close", language)}
            onClick={() => closeOperatorModal()}
          >
            {t("operator_close", language)}
          </button>
        </header>

        <div className="dialog-body operator-modal-body">
          {tab === "agent" ? (
            <OperatorAgentTab language={language} />
          ) : tab === "events" ? (
            <OperatorEventsTab language={language} />
          ) : (
            <OperatorCredentialsTab open={open} language={language} />
          )}
        </div>
      </div>
    </div>
  );
}
