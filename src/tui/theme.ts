/**
 * TUI theme — palette and tokens borrowed from kilocode's "kilo" theme.
 *
 * Signature look: warm yellow (#f9f76f) accent on a near-black stone base,
 * with muted stone greys for secondary text and borders.
 */

export interface Theme {
  background: string;
  backgroundPanel: string;
  backgroundElement: string;
  border: string;
  borderSubtle: string;
  borderActive: string;
  text: string;
  textMuted: string;
  textWeaker: string;
  primary: string;
  primaryForeground: string;
  secondary: string;
  accent: string;
  error: string;
  warning: string;
  success: string;
  info: string;
  // Semantic tokens — derived from the palette above so call sites reference
  // intent ("tool running") rather than a raw colour. Keeps app.tsx free of
  // hardcoded theme.info/theme.success scattered per widget.
  toolRunning: string;
  toolOk: string;
  toolError: string;
  userAccent: string;
  assistantAccent: string;
  dividerColor: string;
  /** Dimmed dialog backdrop. OpenTUI parses #rrggbbaa hex, NOT rgba(). */
  backdrop: string;
}

/** kilo (dark) — the default Sarma theme. */
export const kiloDark: Theme = {
  background: "#0c0a09",
  backgroundPanel: "#1c1917",
  backgroundElement: "#292524",
  border: "#44403b",
  borderSubtle: "#292524",
  borderActive: "#f9f76f",
  text: "#fafaf9",
  textMuted: "#d6d3d1",
  textWeaker: "#a6a09b",
  primary: "#f9f76f",
  primaryForeground: "#0c0a09",
  secondary: "#a6a09b",
  accent: "#f9f76f",
  error: "#ff6467",
  warning: "#cca700",
  success: "#89d185",
  info: "#3794ff",
  // Semantic aliases (intent → palette colour).
  toolRunning: "#3794ff", // info
  toolOk: "#89d185", // success
  toolError: "#ff6467", // error
  userAccent: "#f9f76f", // primary
  assistantAccent: "#d6d3d1", // textMuted
  dividerColor: "#292524", // borderSubtle
  backdrop: "#000000d9", // black @ ~85% — #rrggbbaa, opentui-parseable
};

export const theme: Theme = kiloDark;

/** Spinner frames matching kilo's braille spinner. */
export const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/** Glyphs used across the transcript and panels (kilo-style). */
export const GLYPH = {
  user: "❯",
  assistant: "◆",
  toolRunning: "▸",
  ok: "✓",
  error: "✗",
  running: "◐",
  pending: "·",
  model: "◆",
  tools: "⚙",
} as const;

/** Fixed sidebar width — wide enough for the longest audit stage names. */
export const SIDEBAR_WIDTH = 28;

/** Truncation budgets per field, so widgets don't carry magic numbers. */
export const TRUNCATE = {
  args: 60,
  summary: 80,
  desc: 50,
  model: 18,
} as const;
