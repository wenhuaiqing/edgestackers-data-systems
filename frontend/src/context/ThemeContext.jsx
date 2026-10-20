import { createContext, useContext, useEffect, useState } from "react";

// The platform's own palette - deliberately not Edge Stackers' brand. It
// carries their name because it was built for them; it is not their product
// and should never look like it.
//
//   graphite #11161D   the chrome: sidebar, hero tiles
//   amber    #E3A23B   the mark and the active nav state - chrome only,
//                      it is 2.2:1 on white and never carries text there
//   teal     #0E6B63   interactive and "governed" (6.4:1 on white)
//   violet   #5847C9   anything the triage agent produced, so "the model
//                      said this" is never confused with "the data says this"
//
// Status colours always travel with a label (Badge); chart series are fixed
// in order and never cycled.

export const light = {
  name: "light",
  bg: "#F4F5F7",
  surface: "#FFFFFF",
  surfaceRaised: "#FAFBFC",
  border: "rgba(18,22,28,0.12)",
  borderBright: "rgba(18,22,28,0.26)",
  accent: "#0E6B63",
  accentText: "#FFFFFF",
  accentGlow: "rgba(14,107,99,0.10)",
  accent2: "#5847C9",
  accent2Glow: "rgba(88,71,201,0.10)",
  text: "#12161C",
  textMuted: "rgba(18,22,28,0.64)",
  textDim: "rgba(18,22,28,0.34)",

  sidebarBg: "#11161D",
  sidebarText: "rgba(255,255,255,0.72)",
  sidebarActive: "rgba(227,162,59,0.15)",
  sidebarActiveText: "#E3A23B",
  sidebarBorder: "rgba(255,255,255,0.10)",
  sidebarMark: "#E3A23B",
  sidebarMuted: "rgba(255,255,255,0.52)",
  sidebarGroup: "rgba(255,255,255,0.38)",

  headerBg: "#FFFFFF",
  headerText: "#12161C",
  headerMuted: "rgba(18,22,28,0.60)",
  headerBorder: "rgba(18,22,28,0.10)",
  headerAccent: "#0E6B63",

  ctaBg: "#12161C",
  ctaText: "#FFFFFF",
  ctaHoverBg: "#0E6B63",
  ctaHoverText: "#FFFFFF",

  cardRule: "#E3A23B",
  tableHead: "#F1F3F5",
  statHeroBg: "#11161D",
  statHeroText: "#FFFFFF",
  statHeroMuted: "rgba(255,255,255,0.70)",
  rowHover: "rgba(18,22,28,0.035)",
  rowDivider: "rgba(18,22,28,0.07)",
  grid: "rgba(18,22,28,0.08)",
  code: "rgba(18,22,28,0.05)",
  series: ["#2F6FB5", "#C27E1E", "#6B5CA5", "#2E9A96"],
  status: { good: "#1F7A5A", warning: "#8A6410", serious: "#B4562A", critical: "#A8324B", neutral: "#5B5E6B", ai: "#5847C9" },
  statusBg: {
    good: "rgba(31,122,90,0.10)", warning: "rgba(227,162,59,0.20)", serious: "rgba(180,86,42,0.12)",
    critical: "rgba(168,50,75,0.10)", neutral: "rgba(18,22,28,0.06)", ai: "rgba(88,71,201,0.10)",
  },
};

export const dark = {
  name: "dark",
  bg: "#0D1117",
  surface: "#161B22",
  surfaceRaised: "#1C2330",
  border: "rgba(230,237,243,0.11)",
  borderBright: "rgba(230,237,243,0.24)",
  accent: "#3FB6A8",
  accentText: "#0D1117",
  accentGlow: "rgba(63,182,168,0.14)",
  accent2: "#A99BFF",
  accent2Glow: "rgba(169,155,255,0.14)",
  text: "#E6EDF3",
  textMuted: "rgba(230,237,243,0.62)",
  textDim: "rgba(230,237,243,0.32)",

  sidebarBg: "#090C10",
  sidebarText: "rgba(230,237,243,0.68)",
  sidebarActive: "rgba(227,162,59,0.14)",
  sidebarActiveText: "#E3A23B",
  sidebarBorder: "rgba(230,237,243,0.08)",
  sidebarMark: "#E3A23B",
  sidebarMuted: "rgba(230,237,243,0.50)",
  sidebarGroup: "rgba(230,237,243,0.34)",

  headerBg: "#0D1117",
  headerText: "#E6EDF3",
  headerMuted: "rgba(230,237,243,0.60)",
  headerBorder: "rgba(230,237,243,0.09)",
  headerAccent: "#3FB6A8",

  ctaBg: "#E6EDF3",
  ctaText: "#0D1117",
  ctaHoverBg: "#3FB6A8",
  ctaHoverText: "#0D1117",

  cardRule: "#C98A2B",
  tableHead: "#1C2330",
  statHeroBg: "#E3A23B",
  statHeroText: "#0D1117",
  statHeroMuted: "rgba(13,17,23,0.72)",
  rowHover: "rgba(230,237,243,0.04)",
  rowDivider: "rgba(230,237,243,0.07)",
  grid: "rgba(230,237,243,0.09)",
  code: "rgba(230,237,243,0.06)",
  series: ["#6FA8E6", "#E0A84E", "#A596DE", "#4FC2BD"],
  status: { good: "#5CCB9F", warning: "#E0BE6E", serious: "#F08A5D", critical: "#E8788F", neutral: "#A7A9B4", ai: "#A99BFF" },
  statusBg: {
    good: "rgba(92,203,159,0.14)", warning: "rgba(224,190,110,0.16)", serious: "rgba(240,138,93,0.14)",
    critical: "rgba(232,120,143,0.14)", neutral: "rgba(255,255,255,0.08)", ai: "rgba(169,155,255,0.14)",
  },
};

const Ctx = createContext(null);
const KEY = "edgestackers_theme";

function initial() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved === "dark";
  } catch { /* storage blocked */ }
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }) {
  const [isDark, setIsDark] = useState(initial);
  useEffect(() => {
    try { localStorage.setItem(KEY, isDark ? "dark" : "light"); } catch { /* storage blocked */ }
    document.body.style.background = (isDark ? dark : light).bg;
  }, [isDark]);
  return (
    <Ctx.Provider value={{ t: isDark ? dark : light, isDark, toggle: () => setIsDark((v) => !v) }}>
      {children}
    </Ctx.Provider>
  );
}

export function useTheme() {
  return useContext(Ctx);
}
