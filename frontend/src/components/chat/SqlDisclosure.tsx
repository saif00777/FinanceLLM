import { useState } from "react";
import { ChevronRightIcon, DatabaseIcon } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

export function SqlDisclosure({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-1.5 rounded text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none">
        <ChevronRightIcon aria-hidden="true" className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`} />
        <DatabaseIcon aria-hidden="true" className="size-3.5" />
        {open ? "Hide generated SQL" : "Show generated SQL"}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="bg-muted mt-2 overflow-x-auto rounded-md border p-3 font-mono text-xs leading-relaxed">
          <code>{sql}</code>
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
