import { CheckCircle2Icon } from "lucide-react";
import type { ProgressStep } from "@/lib/graphNodes";

/** What an agent decided, shown under its step as soon as that agent finishes. */
function Thought({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <p className="text-muted-foreground border-muted-foreground/20 mt-0.5 ml-5 border-l-2 pl-2.5 text-xs leading-relaxed break-words whitespace-pre-wrap">
      {text}
    </p>
  );
}

function StepRow({ label, thought }: { label: string; thought?: string }) {
  return (
    <li>
      <div className="flex items-center gap-2 text-sm">
        <CheckCircle2Icon aria-hidden="true" className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <span className="text-foreground/80">{label}</span>
      </div>
      <Thought text={thought} />
    </li>
  );
}

export function ProgressTree({ steps, isStreaming }: { steps: ProgressStep[]; isStreaming: boolean }) {
  if (steps.length === 0 && !isStreaming) return null;

  return (
    <div role="status" aria-live="polite" aria-busy={isStreaming} className="space-y-1.5">
      <ul className="space-y-2">
        {steps.map((step) =>
          step.kind === "single" ? (
            <StepRow key={step.key} label={step.label} thought={step.thought} />
          ) : (
            <li key={step.key} className="space-y-1.5">
              <div className="flex items-center gap-2 text-sm">
                {step.children.length >= step.total ? (
                  <CheckCircle2Icon aria-hidden="true" className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <span className="border-muted-foreground/40 border-t-foreground size-3.5 shrink-0 animate-spin rounded-full border-2" />
                )}
                <span className="text-foreground/80">{step.label}</span>
                <span className="text-muted-foreground text-xs">(parallel)</span>
              </div>
              <ul className="space-y-1 pl-5">
                {step.children.map((child) => (
                  <li key={child.node}>
                    <div className="text-muted-foreground flex items-center gap-2 text-xs">
                      <span className="bg-emerald-600 dark:bg-emerald-400 size-1 shrink-0 rounded-full" />
                      {child.label}
                    </div>
                    <Thought text={child.thought} />
                  </li>
                ))}
              </ul>
            </li>
          ),
        )}
      </ul>
      {isStreaming && (
        <div className="flex items-center gap-2 text-sm">
          <span className="border-muted-foreground/40 border-t-foreground size-3.5 shrink-0 animate-spin rounded-full border-2" />
          <span className="text-muted-foreground">Thinking…</span>
        </div>
      )}
    </div>
  );
}
