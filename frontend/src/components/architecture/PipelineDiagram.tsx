import { useEffect, useRef } from "react";
import { EDGES, KIND_INFO, NODES, NODE_H, NODE_W, VIEW_HEIGHT, VIEW_WIDTH, edgePath, nodeCenter, type ArchNode } from "@/lib/architecture";

export interface DiagramProps {
  /** Nodes the packet is on right now (several during a parallel stage). */
  activeIds?: string[];
  /** Nodes already passed. */
  visitedIds?: string[];
  /** Node whose detail panel is open. */
  selectedId?: string | null;
  /** Dim everything not on this path, e.g. while a question is playing. */
  dimUnvisited?: boolean;
  /** When non-empty, only these nodes stay bright (a selection's neighbours, or a filtered kind). */
  emphasisIds?: string[];
  /** Edge keys ("from>to") to animate as flowing data; when non-empty every other edge fades. */
  flowEdges?: string[];
  onSelect?: (node: ArchNode) => void;
  onHover?: (id: string | null) => void;
}

function Glyph({ kind, x, y }: { kind: ArchNode["kind"]; x: number; y: number }) {
  const color = KIND_INFO[kind].color;
  const common = { fill: "none", stroke: color, strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <g transform={`translate(${x} ${y})`} aria-hidden="true">
      {kind === "guard" && <path {...common} d="M0 -8 L7 -5 V1 C7 5 3 8 0 9 C-3 8 -7 5 -7 1 V-5 Z" />}
      {kind === "llm" && (
        <>
          <circle {...common} cx="0" cy="0" r="7" />
          <circle cx="-2.5" cy="-1" r="1.2" fill={color} />
          <circle cx="2.5" cy="-1" r="1.2" fill={color} />
          <path {...common} d="M-3 3 Q0 5.5 3 3" />
        </>
      )}
      {kind === "code" && <path {...common} d="M-3 -6 L-8 0 L-3 6 M3 -6 L8 0 L3 6" />}
      {kind === "data" && (
        <>
          <circle {...common} cx="-3" cy="-2" r="2.6" />
          <circle {...common} cx="4" cy="-4" r="2" />
          <circle {...common} cx="3" cy="4" r="2.6" />
          <path {...common} d="M-1 -1 L2 -3 M-1 0 L1 3" />
        </>
      )}
      {kind === "edge" && <path {...common} d="M-7 0 H7 M2 -5 L7 0 L2 5" />}
    </g>
  );
}

export function PipelineDiagram({
  activeIds = [],
  visitedIds = [],
  selectedId = null,
  dimUnvisited = false,
  emphasisIds = [],
  flowEdges = [],
  onSelect,
  onHover,
}: DiagramProps) {
  const activeRef = useRef<SVGGElement | null>(null);
  const active = new Set(activeIds);
  const visited = new Set(visitedIds);
  const emphasis = new Set(emphasisIds);
  const flowing = new Set(flowEdges);
  const activeKey = activeIds.join("|");

  // Keep the packet in view as it travels down the (tall) map.
  useEffect(() => {
    if (!activeKey || !activeRef.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    activeRef.current.scrollIntoView({ block: "center", inline: "center", behavior: reduce ? "auto" : "smooth" });
  }, [activeKey]);

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      role="group"
      aria-label="Diagram of how a question flows through the assistant"
      className="h-auto w-full min-w-[540px] select-none"
    >
      <defs>
        <filter id="arch-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
        </marker>
      </defs>

      {/* Edges */}
      <g fill="none">
        {EDGES.map((edge) => {
          const { d, labelAt } = edgePath(edge);
          const key = `${edge.from}>${edge.to}`;
          const focusing = flowing.size > 0;
          const live = focusing ? flowing.has(key) : active.has(edge.to) && (visited.has(edge.from) || active.has(edge.from));
          const passed = !focusing && visited.has(edge.from) && (visited.has(edge.to) || active.has(edge.to));
          const tone = edge.kind === "stop" ? "text-rose-400" : edge.kind === "loop" ? "text-amber-400" : "text-blue-300";
          return (
            <g key={`${edge.from}>${edge.to}`} className={tone}>
              <path d={d} stroke="currentColor" strokeWidth={live ? 2.4 : 1.4} strokeOpacity={live ? 0.95 : passed ? 0.6 : dimUnvisited || focusing ? 0.1 : 0.28} markerEnd="url(#arch-arrow)" strokeDasharray={edge.kind === "loop" || edge.kind === "stop" ? "5 5" : live ? "8 6" : undefined} className={live ? "arch-flow" : undefined} />
              {edge.label && (
                <text x={labelAt.x} y={labelAt.y} textAnchor={edge.kind === "stop" && edge.to === "suggestions" ? "start" : "middle"} className="fill-white/45 text-[10px]" style={{ paintOrder: "stroke", stroke: "#04060f", strokeWidth: 4 }}>
                  {edge.label}
                </text>
              )}
            </g>
          );
        })}
      </g>

      {/* Nodes */}
      {NODES.map((node) => {
        const { x, y } = nodeCenter(node);
        const info = KIND_INFO[node.kind];
        const isActive = active.has(node.id);
        const isVisited = visited.has(node.id);
        const isSelected = selectedId === node.id;
        const dim = (dimUnvisited && !isActive && !isVisited) || (emphasis.size > 0 && !emphasis.has(node.id) && !isActive);
        const interactive = Boolean(onSelect);
        return (
          <g
            key={node.id}
            ref={isActive && activeIds[0] === node.id ? activeRef : undefined}
            transform={`translate(${x - NODE_W / 2} ${y - NODE_H / 2})`}
            opacity={dim ? 0.3 : 1}
            style={{ transition: "opacity 0.35s ease" }}
            className={interactive ? "cursor-pointer outline-none" : undefined}
            role={interactive ? "button" : undefined}
            tabIndex={interactive ? 0 : undefined}
            aria-label={interactive ? `${node.label}: ${node.summary}` : undefined}
            aria-pressed={interactive ? isSelected : undefined}
            onClick={() => onSelect?.(node)}
            onMouseEnter={() => onHover?.(node.id)}
            onMouseLeave={() => onHover?.(null)}
            onFocus={() => onHover?.(node.id)}
            onBlur={() => onHover?.(null)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect?.(node);
              }
            }}
          >
            <rect
              width={NODE_W}
              height={NODE_H}
              rx={14}
              fill={isActive ? `${info.color}26` : "#0b1020"}
              stroke={info.color}
              strokeWidth={isActive || isSelected ? 2.4 : 1.2}
              strokeOpacity={isActive || isSelected ? 1 : 0.55}
              filter={isActive ? "url(#arch-glow)" : undefined}
              className={`${interactive ? "transition-[stroke-width,fill] duration-200 hover:fill-[#131a30]" : ""} ${isActive ? "arch-pulse" : ""}`}
            />
            <Glyph kind={node.kind} x={22} y={NODE_H / 2} />
            <text x={40} y={NODE_H / 2 - 3} className="fill-white text-[12.5px] font-semibold">
              {node.label}
            </text>
            <text x={40} y={NODE_H / 2 + 12} style={{ fill: info.color }} className="text-[9.5px] opacity-90">
              {info.label}
            </text>
            {isVisited && !isActive && (
              <g transform={`translate(${NODE_W - 2} 2)`} aria-hidden="true">
                <circle r="8" fill="#10b981" />
                <path d="M-3.5 0 L-1 2.6 L3.8 -2.6" fill="none" stroke="#04060f" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </g>
            )}
          </g>
        );
      })}

      {/* The data packet: one glowing dot per active node */}
      {activeIds.map((id) => {
        const { x, y } = nodeCenter(NODES.find((n) => n.id === id)!);
        return (
          <g key={id} style={{ transform: `translate(${x - NODE_W / 2 + 4}px, ${y - NODE_H / 2 - 4}px)` }} className="arch-packet" aria-hidden="true">
            <circle r="7" fill="#fde68a" filter="url(#arch-glow)" />
            <circle r="3.2" fill="#fff" />
          </g>
        );
      })}
    </svg>
  );
}
