import { useRef } from "react";
import { MonitorIcon, MoonIcon, SunIcon, type LucideIcon } from "lucide-react";
import type { ThemePreference } from "@/lib/theme";
import { useTheme } from "@/lib/themeContext";

const OPTIONS: { value: ThemePreference; label: string; icon: LucideIcon }[] = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "system", label: "System", icon: MonitorIcon },
];

/** Light / Dark / System as one radio group. Arrow keys move between the options, as in a native radio group. */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: React.KeyboardEvent) {
    const order = OPTIONS.map((o) => o.value);
    const at = order.indexOf(preference);
    let next: ThemePreference | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = order[(at + 1) % order.length];
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = order[(at - 1 + order.length) % order.length];
    if (next) {
      event.preventDefault();
      setPreference(next);
      refs.current[next]?.focus();
    }
  }

  return (
    <div role="radiogroup" aria-label="Theme" onKeyDown={onKeyDown} className="bg-muted inline-flex items-center gap-0.5 rounded-lg p-0.5">
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const on = preference === value;
        return (
          <button
            key={value}
            ref={(node) => {
              refs.current[value] = node;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            aria-label={label}
            title={label}
            tabIndex={on ? 0 : -1}
            onClick={() => setPreference(value)}
            className={`focus-visible:ring-ring inline-flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none ${on ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        );
      })}
    </div>
  );
}
