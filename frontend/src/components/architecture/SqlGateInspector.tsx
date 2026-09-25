import { Fragment, useEffect, useMemo, useState } from "react";
import { CheckCircle2Icon, CircleIcon, Loader2Icon, MinusIcon, PlayIcon, RotateCcwIcon, ShieldAlertIcon, ShieldCheckIcon, WrenchIcon, XCircleIcon } from "lucide-react";
import { GATE_CASES, GATE_CHECKS } from "@/lib/architecture";
import { evaluateGate, fixedSql, statusesAtStep, type CheckStatus } from "@/lib/architectureFlow";

const STEP_MS = 620;
const SQL_WORDS = /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|ON|AS|DELETE|DROP TABLE|AND|OR|DESC|TRUE)\b/g;

const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Light keyword colouring. Splitting keeps every character; nothing is injected as HTML. */
function Sql({ text }: { text: string }) {
  return (
    <code>
      {text.split(SQL_WORDS).map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="font-semibold text-violet-300">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </code>
  );
}

const STATUS_STYLE: Record<CheckStatus, { icon: typeof CheckCircle2Icon; tone: string; label: string; spin?: boolean }> = {
  pending: { icon: CircleIcon, tone: "text-white/25", label: "waiting" },
  running: { icon: Loader2Icon, tone: "text-blue-300", label: "checking", spin: true },
  pass: { icon: CheckCircle2Icon, tone: "text-emerald-400", label: "passed" },
  fail: { icon: XCircleIcon, tone: "text-rose-400", label: "failed" },
  fixed: { icon: WrenchIcon, tone: "text-amber-300", label: "fixed" },
  skipped: { icon: MinusIcon, tone: "text-white/25", label: "not reached" },
};

const VERDICT_STYLE = {
  allow: { icon: ShieldCheckIcon, title: "Allowed", box: "border-emerald-400/40 bg-emerald-400/10", tone: "text-emerald-300" },
  fix: { icon: WrenchIcon, title: "Allowed after an automatic fix", box: "border-amber-400/40 bg-amber-400/10", tone: "text-amber-300" },
  block: { icon: ShieldAlertIcon, title: "Blocked", box: "border-rose-400/40 bg-rose-400/10", tone: "text-rose-300" },
} as const;

export function SqlGateInspector() {
  const [caseId, setCaseId] = useState(GATE_CASES[0].id);
  const [step, setStep] = useState(() => (prefersReducedMotion() ? GATE_CHECKS.length : 0));

  const query = GATE_CASES.find((c) => c.id === caseId) ?? GATE_CASES[0];
  const results = useMemo(() => evaluateGate(query, GATE_CHECKS), [query]);
  const finished = step >= results.length;
  const statuses = statusesAtStep(results, step);

  useEffect(() => {
    if (finished) return;
    const timer = window.setTimeout(() => setStep((s) => s + 1), STEP_MS);
    return () => window.clearTimeout(timer);
  }, [step, finished]);

  function inspect(id: string) {
    setCaseId(id);
    setStep(prefersReducedMotion() ? GATE_CHECKS.length : 0);
  }

  const verdict = VERDICT_STYLE[query.verdict];
  const VerdictIcon = verdict.icon;
  const fixed = fixedSql(query.sql);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
      <div className="space-y-3">
        <p className="text-white/65">Every query the AI writes goes through the same gate before it can touch the database. Pick one and watch it being checked, rule by rule.</p>
        <ul className="space-y-1.5" aria-label="Queries to inspect">
          {GATE_CASES.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                aria-pressed={item.id === caseId}
                onClick={() => inspect(item.id)}
                className={`w-full rounded-xl border px-3 py-2.5 text-left font-mono text-xs leading-snug transition-colors focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none ${item.id === caseId ? "border-blue-300/60 bg-blue-400/15 text-white" : "border-white/10 bg-white/[0.03] text-white/65 hover:bg-white/[0.07]"}`}
              >
                <span className="line-clamp-2 break-all">{item.sql}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <pre className="overflow-x-auto rounded-2xl border border-white/10 bg-[#070b18] p-4 font-mono text-sm leading-relaxed whitespace-pre-wrap text-white/90" aria-label="Query being inspected">
          <Sql text={query.sql} />
        </pre>

        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
            <div className="h-full rounded-full bg-gradient-to-r from-blue-400 to-cyan-300 transition-[width] duration-500 ease-out" style={{ width: `${Math.min(step / results.length, 1) * 100}%` }} />
          </div>
          <ol className="space-y-1" aria-label="Checks, in the order the gate runs them">
            {results.map((result, i) => {
              const status = statuses[i];
              const style = STATUS_STYLE[status];
              const Icon = style.icon;
              const settled = status !== "pending" && status !== "running";
              return (
                <li key={result.id} className={`flex items-start gap-3 rounded-xl px-3 py-2 transition-colors duration-300 ${status === "running" ? "bg-blue-400/10" : status === "fail" ? "bg-rose-400/10" : status === "fixed" ? "bg-amber-400/10" : ""}`}>
                  <span key={status} className={`mt-0.5 shrink-0 ${settled ? "arch-pop" : ""} ${style.tone}`}>
                    <Icon aria-hidden="true" className={`size-5 ${style.spin ? "animate-spin" : ""}`} />
                  </span>
                  <div className={status === "pending" || status === "skipped" ? "opacity-50" : ""}>
                    <p className="text-sm font-medium">
                      {result.label}
                      <span className="sr-only"> — {style.label}</span>
                    </p>
                    {(status === "running" || status === "fail" || status === "fixed") && <p className="arch-pop mt-0.5 text-xs leading-relaxed text-white/65">{result.detail}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>

        {finished ? (
          <div role="status" className={`arch-pop rounded-2xl border p-4 ${verdict.box}`}>
            <p className={`flex items-center gap-2 font-semibold ${verdict.tone}`}>
              <VerdictIcon aria-hidden="true" className="size-5" />
              {verdict.title}
            </p>
            <p className="mt-1 text-sm text-white/85">{query.why}</p>
            {query.verdict === "fix" && (
              <pre className="mt-3 overflow-x-auto rounded-lg bg-black/30 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-white/85" aria-label="The query as the gate returns it">
                <Sql text={fixed.slice(0, fixed.length - " LIMIT 100".length)} />
                <mark className="rounded bg-amber-300/25 px-1 text-amber-100"> LIMIT 100</mark>
              </pre>
            )}
            {query.verdict === "block" && <p className="mt-2 text-xs text-white/60">It never runs. The reason goes back to the SQL writer, which gets up to two more attempts.</p>}
            <button type="button" onClick={() => inspect(query.id)} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none">
              <RotateCcwIcon aria-hidden="true" className="size-4" /> Replay
            </button>
          </div>
        ) : (
          <button type="button" onClick={() => setStep(results.length)} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-white/55 hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none">
            <PlayIcon aria-hidden="true" className="size-4" /> Skip to the result
          </button>
        )}
      </div>
    </div>
  );
}
