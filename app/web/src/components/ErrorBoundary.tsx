import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; label: string; compact?: boolean };
type State = { error: Error | null };

// A rendering error stays inside the part that failed (one answer, one page) instead of
// blanking the whole application, and shows what failed so it can be reported.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className={`m-auto w-full max-w-2xl rounded-input border border-bad/30 bg-bad/5 ${this.props.compact ? "p-4" : "mt-10 p-6"}`}>
        <div className="flex items-start gap-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-bad-ink" />
          <div className="min-w-0 space-y-1">
            <div className="text-sm font-semibold text-ink">This {this.props.label} could not be displayed.</div>
            <p className="text-sm text-ink-2">
              The data is safe; only its display failed. Error: <code className="break-all font-mono text-xs">{error.message}</code>
            </p>
            <button className="btn-ghost -ml-2.5 mt-1 h-8 px-2.5 text-sm" onClick={() => this.setState({ error: null })}>
              <RotateCcw size={14} /> Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
