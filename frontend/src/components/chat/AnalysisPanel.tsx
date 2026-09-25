import { LightbulbIcon, TriangleAlertIcon } from "lucide-react";
import type { AnalysisPayload } from "@/lib/api";

export function AnalysisPanel({ analysis }: { analysis: AnalysisPayload }) {
  const insights = analysis.insights ?? [];
  const caveats = analysis.caveats ?? [];
  if (insights.length === 0 && caveats.length === 0) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {insights.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
            <LightbulbIcon aria-hidden="true" className="size-3.5" />
            Insights
          </h4>
          <ul className="space-y-1 text-sm">
            {insights.map((insight) => (
              <li key={insight} className="text-foreground/90 leading-snug">
                {insight}
              </li>
            ))}
          </ul>
        </div>
      )}
      {caveats.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
            <TriangleAlertIcon aria-hidden="true" className="size-3.5" />
            Caveats
          </h4>
          <ul className="space-y-1 text-sm">
            {caveats.map((caveat) => (
              <li key={caveat} className="text-muted-foreground leading-snug">
                {caveat}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
