import { QuoteIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Citation } from "@/lib/api";

export function CitationsList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <QuoteIcon aria-hidden="true" className="text-muted-foreground size-3.5" />
      <span className="text-muted-foreground text-xs">Sources:</span>
      {citations.map((citation) => (
        <Tooltip key={citation.source_hash}>
          <TooltipTrigger asChild>
            <span className="bg-muted text-muted-foreground cursor-default rounded px-1.5 py-0.5 text-[11px]">
              <span className="font-mono">{citation.source_hash.slice(0, 8)}</span>
              {citation.title && <span className="ml-1.5 max-w-64 truncate align-bottom inline-block">{citation.title}</span>}
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <div className="space-y-0.5 text-xs">
              <p className="font-mono">{citation.source_hash}</p>
              {citation.title && <p>{citation.title}</p>}
              {(citation.doc_type || citation.date) && (
                <p className="opacity-80">{[citation.doc_type, citation.date].filter(Boolean).join(" · ")}</p>
              )}
            </div>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
