import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n/vocabulary";
import { getState } from "../store";
import { DetailDisclosure } from "./DetailDisclosure";

interface State {
  error: Error | null;
  stack: string | null;
}

/**
 * Last-resort boundary around the whole shell.
 *
 * A single unexpected shape in one component should not turn the window into a
 * blank square. The runtime keeps running underneath, so the user gets a
 * plain message and the details under a collapsed disclosure.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, stack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ stack: info.componentStack ?? error.stack ?? null });
    // eslint-disable-next-line no-console
    console.error("render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const language = getState().language;
    return (
      <div className="boot">
        <div className="fatal" data-testid="render-error">
          <h2>{t("error_boundary_title", language)}</h2>
          <p className="prose">{t("error_boundary_body", language)}</p>
          <div style={{ marginTop: "var(--space-2)" }}>
            <button
              type="button"
              className="action primary"
              onClick={() => window.location.reload()}
            >
              {t("error_boundary_retry", language)}
            </button>
          </div>
          <div style={{ marginTop: "var(--space-2)" }}>
            <DetailDisclosure>
              <pre style={{ whiteSpace: "pre-wrap", userSelect: "text", margin: 0 }}>
                {this.state.error.message}
                {this.state.stack ? `\n${this.state.stack}` : ""}
              </pre>
            </DetailDisclosure>
          </div>
        </div>
      </div>
    );
  }
}
