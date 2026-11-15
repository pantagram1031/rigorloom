import { useState } from "react";
import { closeOperatorModal, openViaDialog, selectSession } from "../actions";
import { t } from "../i18n/vocabulary";
import { activeSession, useWorkspace } from "../store";
import { AgentView } from "../views/AgentView";
import { Settings } from "./Settings";
import { Timeline } from "./Timeline";

export function OperatorAgentModal() {
  const open = useWorkspace((s) => s.operatorModalOpen);
  const language = useWorkspace((s) => s.language);
  const session = useWorkspace(activeSession);
  const [tab, setTab] = useState<"agent" | "events" | "credentials">("agent");

  if (!open) return null;

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeOperatorModal();
      }}
    >
      <div
        className="dialog dialog--operator"
        role="dialog"
        aria-modal="true"
        aria-labelledby="operator-modal-title"
        data-testid="operator-agent-modal"
      >
        <div className="dialog-head">
          <div>
            <h2 id="operator-modal-title">{t("operator_modal_title", language)}</h2>
            <div className="operator-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "agent"}
                className={`operator-tab${tab === "agent" ? " is-active" : ""}`}
                data-testid="operator-tab-agent"
                onClick={() => setTab("agent")}
              >
                {t("operator_tab_agent", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "events"}
                className={`operator-tab${tab === "events" ? " is-active" : ""}`}
                data-testid="operator-tab-events"
                onClick={() => setTab("events")}
              >
                {t("operator_tab_events", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "credentials"}
                className={`operator-tab${tab === "credentials" ? " is-active" : ""}`}
                data-testid="operator-tab-credentials"
                onClick={() => setTab("credentials")}
              >
                {t("operator_tab_credentials", language)}
              </button>
            </div>
          </div>

          <button
            type="button"
            className="ghost"
            data-testid="operator-modal-close"
            onClick={() => closeOperatorModal()}
          >
            {t("operator_close", language)}
          </button>
        </div>

        <div className="dialog-body operator-modal-body">
          {tab === "agent" ? (
            <AgentView
              onOpen={() => {
                closeOperatorModal();
                void openViaDialog();
              }}
              onSelectSession={(id) => {
                closeOperatorModal();
                void selectSession(id);
              }}
            />
          ) : tab === "credentials" ? (
            <Settings embedded />
          ) : session ? (
            <Timeline />
          ) : (
            <p className="hint">{t("operator_no_session", language)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
