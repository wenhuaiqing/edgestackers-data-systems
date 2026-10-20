// A render error in one module must not white-screen the whole app.
//
// This is a demo concern first and a design position second. During a live
// walkthrough a blank page is unrecoverable; a module that says "this one
// failed, the rest still work" is survivable, and it is the same philosophy
// the platform applies to its data — say what is broken rather than show
// nothing and let the viewer assume everything is fine.

import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Keep the detail in the console for whoever is debugging; the surface
    // stays calm.
    console.error("Module render failed:", error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const t = this.props.theme || {};
    return (
      <div
        role="alert"
        style={{
          background: t.surface || "#fff",
          border: `1px solid ${t.border || "rgba(0,0,0,0.12)"}`,
          borderLeft: `3px solid ${t.status?.critical || "#B3323F"}`,
          borderRadius: 12,
          padding: "20px 24px",
          maxWidth: 720,
        }}
      >
        <h2 style={{
          margin: 0, fontSize: 15, fontWeight: 700,
          color: t.text || "#10242A",
        }}>
          This module failed to render
        </h2>
        <p style={{
          margin: "8px 0 0", fontSize: 13, lineHeight: 1.6,
          color: t.textMuted || "rgba(0,0,0,0.6)",
        }}>
          Every other module still works, and the assistant in the corner is
          unaffected. The detail is in the browser console.
        </p>
        <pre style={{
          margin: "14px 0 0", padding: "10px 12px",
          background: t.surfaceRaised || "rgba(0,0,0,0.04)",
          border: `1px solid ${t.border || "rgba(0,0,0,0.12)"}`,
          borderRadius: 8, fontSize: 11.5, overflow: "auto",
          color: t.textMuted || "rgba(0,0,0,0.6)", maxHeight: 160,
        }}>
          {String(error?.message || error)}
        </pre>
        <button
          onClick={() => this.setState({ error: null })}
          style={{
            marginTop: 14,
            background: t.accent || "#7A5F1E", color: t.accentText || "#fff",
            border: "none", borderRadius: 999, padding: "7px 16px",
            fontSize: 12.5, fontWeight: 700, cursor: "pointer",
          }}
        >
          Try again
        </button>
      </div>
    );
  }
}
