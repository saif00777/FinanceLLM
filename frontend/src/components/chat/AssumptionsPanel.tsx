import { CompassIcon } from "lucide-react";

export function AssumptionsPanel({ assumptions }: { assumptions: string[] }) {
  if (assumptions.length === 0) {
    return <p className="text-muted-foreground text-sm">The bot did not have to assume anything to answer this question.</p>;
  }

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">What the bot took for granted to answer. Ask again with more detail if any of these is wrong.</p>
      <ul className="space-y-1.5">
        {assumptions.map((assumption) => (
          <li key={assumption} className="flex items-start gap-2 text-sm leading-snug">
            <CompassIcon aria-hidden="true" className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
            <span>{assumption}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
