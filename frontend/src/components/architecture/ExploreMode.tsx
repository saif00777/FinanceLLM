import { useMemo, useState } from "react";
import { PipelineDiagram } from "@/components/architecture/PipelineDiagram";
import { NodeDetail } from "@/components/architecture/shared";
import { EDGES, KIND_INFO, NODES, NODE_BY_ID, type ArchNode, type NodeKind } from "@/lib/architecture";
import { connections } from "@/lib/architectureFlow";

export function ExploreMode() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [kind, setKind] = useState<NodeKind | null>(null);

  // Hovering previews a component's connections; selecting pins them.
  const focusId = hoverId ?? selectedId;
  const focus = useMemo(() => (focusId ? connections(focusId, EDGES) : null), [focusId]);
  const selected = useMemo(() => (selectedId ? connections(selectedId, EDGES) : null), [selectedId]);

  const emphasisIds = focus && focusId ? [focusId, ...focus.neighborIds] : kind ? NODES.filter((n) => n.kind === kind).map((n) => n.id) : [];
  const flowEdges = focus ? [...focus.incoming, ...focus.outgoing].map((e) => `${e.from}>${e.to}`) : [];

  function select(node: ArchNode) {
    setSelectedId(node.id);
    setKind(null);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
      <div className="order-2 lg:order-1">
        <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#070b18]/80 p-3 sm:p-5">
          <PipelineDiagram selectedId={selectedId} emphasisIds={emphasisIds} flowEdges={flowEdges} onSelect={select} onHover={setHoverId} />
        </div>
      </div>

      <div className="order-1 space-y-4 lg:sticky lg:top-4 lg:order-2 lg:self-start">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
          <p className="px-1 pb-2 text-xs font-medium tracking-wide text-white/50 uppercase">Highlight by kind</p>
          <ul className="flex flex-wrap gap-1.5" aria-label="Filter components by kind">
            {(Object.keys(KIND_INFO) as NodeKind[]).map((k) => {
              const info = KIND_INFO[k];
              const on = kind === k;
              return (
                <li key={k}>
                  <button
                    type="button"
                    aria-pressed={on}
                    title={info.blurb}
                    onClick={() => {
                      setKind(on ? null : k);
                      setSelectedId(null);
                    }}
                    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none ${on ? "border-white/40 bg-white/15 text-white" : "border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/10"}`}
                  >
                    <span className="size-2.5 rounded-full" style={{ background: info.color }} aria-hidden="true" />
                    {info.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <NodeDetail
          node={selectedId ? NODE_BY_ID[selectedId] : null}
          fedBy={selected ? [...new Set(selected.incoming.map((e) => e.from))] : []}
          handsTo={selected ? [...new Set(selected.outgoing.map((e) => e.to))] : []}
          onJump={(id) => {
            setSelectedId(id);
            setKind(null);
          }}
        />
      </div>
    </div>
  );
}
