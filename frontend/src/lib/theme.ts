/**
 * Pure theme rules. No React and no browser APIs, so the same file runs in the app and under `node --test`.
 * `index.html` repeats the tiny read-and-apply step inline so the right theme is set before first paint.
 */

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "financial-assistant.theme";

/** Browser chrome colour (mobile address bar) for each resolved theme; matches --background in index.css. */
export const THEME_COLORS: Record<ResolvedTheme, string> = { light: "#ffffff", dark: "#0a0a0a" };

const PREFERENCES: readonly string[] = ["light", "dark", "system"];

/** Reads a saved value; anything missing or unrecognised means follow the operating system. */
export function parseTheme(raw: string | null | undefined): ThemePreference {
  return raw && PREFERENCES.includes(raw) ? (raw as ThemePreference) : "system";
}

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

export function nextInCycle(preference: ThemePreference): ThemePreference {
  return preference === "light" ? "dark" : preference === "dark" ? "system" : "light";
}
