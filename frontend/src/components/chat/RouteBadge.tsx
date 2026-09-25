import { AlertTriangleIcon, CheckCircle2Icon, HelpCircleIcon, ShieldAlertIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ChatRoute } from "@/lib/api";

const ROUTE_META: Record<ChatRoute, { label: string; icon: typeof CheckCircle2Icon; className: string }> = {
  answered: {
    label: "Answered",
    icon: CheckCircle2Icon,
    className: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  },
  clarify: {
    label: "Needs clarification",
    icon: HelpCircleIcon,
    className: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300",
  },
  repair: {
    label: "Couldn't validate a query",
    icon: AlertTriangleIcon,
    className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  },
  abstain: {
    label: "Request declined",
    icon: ShieldAlertIcon,
    className: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300",
  },
};

export function RouteBadge({ route }: { route: ChatRoute }) {
  const meta = ROUTE_META[route] ?? ROUTE_META.clarify;
  const Icon = meta.icon;
  return (
    <Badge variant="outline" className={`gap-1.5 font-normal ${meta.className}`}>
      <Icon aria-hidden="true" className="size-3.5" />
      {meta.label}
    </Badge>
  );
}
