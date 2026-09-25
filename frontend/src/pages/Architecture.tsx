import { useEffect } from "react";
import { ArrowLeftIcon, CompassIcon, LandmarkIcon, PlayIcon, ShieldCheckIcon } from "lucide-react";
import { ExploreMode } from "@/components/architecture/ExploreMode";
import { QuestionPlayer } from "@/components/architecture/QuestionPlayer";
import { SqlGateInspector } from "@/components/architecture/SqlGateInspector";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDarkBody } from "@/hooks/useDarkBody";
import { NODES } from "@/lib/architecture";

export function Architecture({ onBack, backLabel, onOpenChat }: { onBack: () => void; backLabel: string; onOpenChat?: () => void }) {
  useDarkBody();

  // An earlier version of this page saved game progress here; it is no longer used, so clear it.
  useEffect(() => {
    try {
      localStorage.removeItem("financial-assistant.architecture-progress.v1");
    } catch {
      /* storage blocked: nothing to clear */
    }
  }, []);

  return (
    <div className="dark relative isolate min-h-svh overflow-x-clip bg-[#04060f] text-white selection:bg-blue-500/40">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="landing-orb absolute -top-40 -left-32 size-[32rem] rounded-full bg-blue-600/30 blur-[120px]" />
        <div className="landing-orb absolute top-1/2 -right-40 size-[28rem] rounded-full bg-violet-600/25 blur-[120px]" style={{ animationDelay: "-6s" }} />
        <div className="landing-grid absolute inset-0" />
      </div>

      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-white/70 hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none">
          <ArrowLeftIcon aria-hidden="true" className="size-4" />
          {backLabel}
        </button>
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600">
            <LandmarkIcon aria-hidden="true" className="size-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Financial Assistant</span>
        </div>
        {onOpenChat ? (
          <button type="button" onClick={onOpenChat} className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none">
            Open chat
          </button>
        ) : (
          <span className="w-20" aria-hidden="true" />
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl space-y-6 px-4 pb-20 sm:px-6">
        <section className="landing-rise max-w-3xl space-y-3 pt-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-blue-200">
            <CompassIcon aria-hidden="true" className="size-3.5" /> How it works
          </span>
          <h1 className="text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-5xl">
            Follow a question through{" "}
            <span className="bg-gradient-to-r from-blue-300 via-indigo-300 to-cyan-200 bg-clip-text text-transparent">the machine.</span>
          </h1>
          <p className="text-lg leading-relaxed text-white/65">
            {NODES.length} stops, each with one job and hard limits. Explore the map, watch a question travel through it, and see the SQL gate check a query rule by rule.
          </p>
        </section>

        <Tabs defaultValue="explore">
          <TabsList className="h-auto flex-wrap bg-white/10 p-1" aria-label="Views">
            <TabsTrigger value="explore" className="px-4 py-2 text-white/70 data-[state=active]:bg-white/15 data-[state=active]:text-white">
              <CompassIcon aria-hidden="true" className="size-4" /> Explore the map
            </TabsTrigger>
            <TabsTrigger value="watch" className="px-4 py-2 text-white/70 data-[state=active]:bg-white/15 data-[state=active]:text-white">
              <PlayIcon aria-hidden="true" className="size-4" /> Watch a question
            </TabsTrigger>
            <TabsTrigger value="gate" className="px-4 py-2 text-white/70 data-[state=active]:bg-white/15 data-[state=active]:text-white">
              <ShieldCheckIcon aria-hidden="true" className="size-4" /> SQL gate
            </TabsTrigger>
          </TabsList>
          <TabsContent value="explore" className="pt-2">
            <ExploreMode />
          </TabsContent>
          <TabsContent value="watch" className="pt-2">
            <QuestionPlayer />
          </TabsContent>
          <TabsContent value="gate" className="pt-2">
            <SqlGateInspector />
          </TabsContent>
        </Tabs>

        <p className="pt-4 text-center text-xs text-white/35">
          The map, the routes and the gate's checks are verified against the real workflow and SQL policy by automated tests, so this page cannot drift from the code.
        </p>
      </main>
    </div>
  );
}
