/**
 * The webview half of crash visibility.
 *
 * `src-tauri/src/main.rs` installs a panic hook so a Rust panic writes
 * crash.log instead of vanishing (spike obligation 5, M17). This is the same
 * obligation on the other side of the IPC boundary: an uncaught render error
 * unmounts the whole React root, and the window then shows nothing at all with
 * no indication that anything went wrong.
 *
 * That failure is not hypothetical here. The first smoke run against the built
 * app reported every store assertion passing and every DOM assertion failing,
 * because a selector returning a fresh `[]` tripped React's infinite-loop
 * detection and took the root down silently. With this boundary the same bug
 * would have named itself on screen.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
  stack: string | null;
}

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
    return (
      <div className="boot">
        <div className="fatal" data-testid="render-error">
          <h2>화면을 그리지 못했습니다</h2>
          <p className="prose" style={{ color: "var(--fg)" }}>
            문서와 런타임은 그대로입니다. 창을 다시 열면 이어서 작업할 수 있습니다.
          </p>
          <p className="prose mono" style={{ marginTop: "var(--s3)" }}>
            {this.state.error.message}
          </p>
          {this.state.stack ? (
            <details style={{ marginTop: "var(--s3)" }}>
              <summary style={{ fontSize: "var(--text-xs)", color: "var(--fg-faint)" }}>
                자세히
              </summary>
              <pre
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-xs)",
                  whiteSpace: "pre-wrap",
                  userSelect: "text",
                }}
              >
                {this.state.stack}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    );
  }
}
