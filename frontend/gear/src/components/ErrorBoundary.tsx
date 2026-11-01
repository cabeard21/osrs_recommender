import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="panel" role="alert">
        <h2>Something went wrong showing this view</h2>
        <p>
          Your settings are saved in this tab. Reload the page, then run the
          optimization again.
        </p>
        <button onClick={() => location.reload()}>Reload page</button>
      </div>
    );
  }
}
