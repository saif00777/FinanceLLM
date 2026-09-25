import { useState } from "react";
import { ChevronRightIcon, ListTreeIcon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ProgressTree } from "@/components/chat/ProgressTree";
import type { ProgressStep } from "@/lib/graphNodes";

export function ReasoningDisclosure({ steps }: { steps: ProgressStep[] }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-1.5 rounded text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none">
        <ChevronRightIcon aria-hidden="true" className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`} />
        <ListTreeIcon aria-hidden="true" className="size-3.5" />
        {open ? "Hide reasoning steps" : "Show reasoning steps"}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 rounded-md border p-3">
          <ProgressTree steps={steps} isStreaming={false} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
