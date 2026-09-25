import { KIND_INFO, NODE_BY_ID, type ArchNode } from "@/lib/architecture";

function LinkChips({ title, ids, onJump }: { title: string; ids: string[]; onJump: (id: string) => void }) {
  if (ids.length === 0) return null;
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-white/45 uppercase">{title}</dt>
      <dd className="mt-1.5 flex flex-wrap gap-1.5">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onJump(id)}
            className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/80 transition-colors hover:border-blue-300/50 hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none"
          >
            {NODE_BY_ID[id].label}
          </button>
        ))}
      </dd>
    </div>
  );
}

export function NodeDetail({ node, fedBy, handsTo, onJump }: { node: ArchNode | null; fedBy: string[]; handsTo: string[]; onJump: (id: string) => void }) {
  if (!node) {
    return (
      <div className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-6 text-center text-sm text-white/50">
        Hover or tap any component on the map. Its connections light up, and this panel explains what it does and what it can never do.
      </div>
    );
  }
  const info = KIND_INFO[node.kind];
  return (
    <article key={node.id} className="arch-pop rounded-2xl border border-white/10 bg-white/[0.05] p-5 backdrop-blur" aria-live="polite">
      <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium" style={{ color: info.color, borderColor: `${info.color}66`, background: `${info.color}1a` }}>
        {info.label}
      </span>
      <h3 className="mt-3 text-xl font-semibold tracking-tight">{node.label}</h3>
      <p className="mt-1 text-sm text-white/65">{node.summary}</p>

      <dl className="mt-4 space-y-3 text-sm">
        <div>
          <dt className="text-xs font-medium tracking-wide text-emerald-300 uppercase">What it does</dt>
          <dd className="mt-0.5 leading-relaxed text-white/85">{node.does}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium tracking-wide text-rose-300 uppercase">What it can never do</dt>
          <dd className="mt-0.5 leading-relaxed text-white/85">{node.never}</dd>
        </div>
        <LinkChips title="Receives from" ids={fedBy} onJump={onJump} />
        <LinkChips title="Hands over to" ids={handsTo} onJump={onJump} />
      </dl>

      <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="Built with">
        {node.uses.map((tool) => (
          <li key={tool} className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-white/70">
            {tool}
          </li>
        ))}
      </ul>

      <p className="mt-4 rounded-xl border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
        <span className="font-semibold">Good to know: </span>
        {node.fact}
      </p>
    </article>
  );
}
