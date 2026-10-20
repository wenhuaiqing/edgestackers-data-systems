import { useEffect, useState } from "react";
import { Menu, Moon, Sun, X } from "lucide-react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Mark from "./components/Mark.jsx";
import { writeToken } from "./config.js";
import { useTheme } from "./context/ThemeContext.jsx";
import { useApi } from "./lib/api.js";
import { getRoutes } from "./navigation.js";

const ROUTES = getRoutes();
const NARROW = 920;

function useNarrow() {
  const q = `(max-width: ${NARROW}px)`;
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

function NavList({ onPick }) {
  const { t } = useTheme();
  const groups = [];
  for (const r of ROUTES) {
    if (!groups.length || groups[groups.length - 1].name !== r.group) groups.push({ name: r.group, items: [] });
    groups[groups.length - 1].items.push(r);
  }
  return (
    <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {groups.map((g) => (
        <div key={g.name} style={{ marginBottom: 8 }}>
          <div style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase",
            color: t.sidebarGroup, padding: "6px 10px 4px",
          }}>{g.name}</div>
          {g.items.map((r) => {
            const Icon = r.icon;
            return (
              <NavLink key={r.to} to={r.to} onClick={onPick} style={({ isActive }) => ({
                display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8,
                fontSize: 13.5, fontWeight: 500,
                color: isActive ? t.sidebarActiveText : t.sidebarText,
                background: isActive ? t.sidebarActive : "transparent",
              })}>
                {Icon && <Icon size={15} strokeWidth={1.9} />}
                <span>{r.label}</span>
              </NavLink>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  const { t } = useTheme();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Mark colour={t.sidebarMark} size={28} />
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
        <span style={{ fontSize: 15, fontWeight: 800, letterSpacing: "0.14em", color: "#FFFFFF" }}>TAPELINE</span>
        <span style={{ fontSize: 10.5, color: t.sidebarMuted, fontWeight: 600, marginTop: 3 }}>
          raw events to decisions you can trust
        </span>
      </div>
    </div>
  );
}

function ThemeButton({ dark }) {
  const { t, isDark, toggle } = useTheme();
  const colour = dark ? t.sidebarMuted : t.headerMuted;
  return (
    <button onClick={toggle} aria-label={isDark ? "Use the light theme" : "Use the dark theme"} style={{
      display: "flex", alignItems: "center", gap: 6, background: "none", cursor: "pointer",
      border: `1px solid ${dark ? t.sidebarBorder : t.headerBorder}`, color: colour,
      borderRadius: 999, padding: "6px 11px", fontSize: 12, fontFamily: "inherit",
    }}>
      {isDark ? <Sun size={13} /> : <Moon size={13} />}
      {isDark ? "Light" : "Dark"}
    </button>
  );
}

function Header({ narrow, onMenu, menuOpen }) {
  const { t } = useTheme();
  const location = useLocation();
  const { data: meta } = useApi("/api/meta");
  const current = ROUTES.find((r) => location.pathname.startsWith(r.to)) || ROUTES[0];
  const operator = Boolean(writeToken());
  return (
    <header style={{
      minHeight: 56, borderBottom: `1px solid ${t.headerBorder}`, background: narrow ? t.sidebarBg : t.headerBg,
      display: "flex", alignItems: "center", padding: narrow ? "10px 14px" : "0 24px", gap: 14, flexWrap: "wrap",
    }}>
      {narrow ? (
        <>
          <button onClick={onMenu} aria-label={menuOpen ? "Close the menu" : "Open the menu"} style={{
            background: "none", border: "none", color: "#FFFFFF", cursor: "pointer", padding: 4, display: "flex",
          }}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <Brand />
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {current?.icon && <current.icon size={17} color={t.headerAccent} strokeWidth={2} />}
          <span style={{ fontSize: 16, fontWeight: 650, color: t.headerText }}>{current?.label}</span>
        </div>
      )}
      <div style={{ flex: 1 }} />
      {!narrow && meta && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11.5, color: t.headerMuted, flexWrap: "wrap" }}>
          <Pill tone="neutral">Synthetic data</Pill>
          <span>Sessions 12/10 to 16/10/2026, {meta.timezone}</span>
          <Pill tone={operator ? "good" : "neutral"}>{operator ? "Operator: writes enabled" : "Read-only link"}</Pill>
          <Pill tone={meta.llm_configured ? "ai" : "neutral"}>{meta.llm_configured ? `Agent: ${meta.llm_model}` : "Agent: runbook only"}</Pill>
        </div>
      )}
    </header>
  );
}

function Pill({ tone, children }) {
  const { t } = useTheme();
  return (
    <span style={{
      background: t.statusBg[tone], color: t.status[tone], borderRadius: 999, padding: "3px 9px",
      fontWeight: 650, whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

export default function App() {
  const { t } = useTheme();
  const narrow = useNarrow();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  const routes = (
    <Routes>
      <Route path="/" element={<Navigate to="/desk" replace />} />
      {ROUTES.map((r) => (
        <Route key={r.to} path={r.to} element={<ErrorBoundary key={r.to} theme={t}><r.component /></ErrorBoundary>} />
      ))}
      <Route path="*" element={<Navigate to="/desk" replace />} />
    </Routes>
  );

  if (narrow) {
    return (
      <div style={{ minHeight: "100%", background: t.bg, color: t.text }}>
        <Header narrow onMenu={() => setMenuOpen((v) => !v)} menuOpen={menuOpen} />
        {menuOpen && (
          <div style={{ background: t.sidebarBg, padding: "8px 10px 14px", borderBottom: `1px solid ${t.sidebarBorder}` }}>
            <NavList onPick={() => setMenuOpen(false)} />
            <div style={{ padding: "4px 10px" }}><ThemeButton dark /></div>
          </div>
        )}
        <main style={{ padding: "16px 16px 40px", minWidth: 0, overflowX: "hidden" }}>{routes}</main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: t.bg, color: t.text }}>
      <aside style={{
        width: 248, background: t.sidebarBg, borderRight: `1px solid ${t.sidebarBorder}`,
        display: "flex", flexDirection: "column", padding: "18px 12px", overflowY: "auto", flexShrink: 0,
      }}>
        <div style={{ padding: "0 8px 18px" }}><Brand /></div>
        <NavList />
        <div style={{ flex: 1 }} />
        <div style={{ padding: "8px 8px 0" }}><ThemeButton dark /></div>
      </aside>
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Header />
        <div style={{ flex: 1, overflow: "auto" }}>
          <div style={{ padding: "22px 28px 48px", maxWidth: 1480 }}>{routes}</div>
        </div>
      </main>
    </div>
  );
}
