import { CompassIcon, KeyRoundIcon, LandmarkIcon, MessageSquarePlusIcon, ShieldCheckIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
} from "@/components/ui/sidebar";

export function AppSidebar({ onNewChat, hasMessages, onChangeKey, onHowItWorks }: { onNewChat: () => void; hasMessages: boolean; onChangeKey?: () => void; onHowItWorks?: () => void }) {
  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader className="gap-3 px-3 py-3">
        <div className="flex items-center gap-2 px-1">
          <span className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
            <LandmarkIcon aria-hidden="true" className="size-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Financial Assistant</span>
        </div>
        <Button variant="outline" className="justify-start gap-2" onClick={onNewChat} disabled={!hasMessages}>
          <MessageSquarePlusIcon aria-hidden="true" className="size-4" />
          New chat
        </Button>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>What you can ask</SidebarGroupLabel>
          <SidebarGroupContent className="text-muted-foreground px-2 text-sm leading-relaxed">
            <ul className="list-disc space-y-1.5 pl-4">
              <li>Spending, income, and merchant-category trends</li>
              <li>Transaction totals by year, card, or merchant</li>
              <li>Larkspur Ridge Bank documents: financials, credit, compliance, customer communications</li>
            </ul>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="gap-2 px-3 pb-3">
        {onHowItWorks && (
          <Button variant="ghost" size="sm" className="text-muted-foreground justify-start gap-2" onClick={onHowItWorks}>
            <CompassIcon aria-hidden="true" className="size-4" />
            How it works
          </Button>
        )}
        {onChangeKey && (
          <Button variant="ghost" size="sm" className="text-muted-foreground justify-start gap-2" onClick={onChangeKey}>
            <KeyRoundIcon aria-hidden="true" className="size-4" />
            Change API key
          </Button>
        )}
        <div className="text-muted-foreground flex items-start gap-2 text-xs leading-relaxed">
          <ShieldCheckIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>Every query is policy-validated before it runs. No credentials or raw source tables are ever exposed.</span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
