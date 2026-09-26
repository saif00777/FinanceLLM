import { createContext, useContext } from "react";
import type { ResolvedTheme, ThemePreference } from "@/lib/theme";

export interface ThemeState {
  /** What the person chose: light, dark, or follow the system. */
  preference: ThemePreference;
  /** What is actually showing right now. */
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeState | null>(null);

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (!state) throw new Error("useTheme must be used inside <ThemeProvider>");
  return state;
}
