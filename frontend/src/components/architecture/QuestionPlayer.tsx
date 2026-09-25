import { useEffect, useMemo, useState } from "react";
import { CheckCircle2Icon, PauseIcon, PlayIcon, RotateCcwIcon, StepBackIcon, StepForwardIcon } from "lucide-react";
import { PipelineDiagram } from "@/components/architecture/PipelineDiagram";
import { LABELS, SCENARIOS } from "@/lib/architecture";
import { buildFrames, delayForSpeed, stepFrame } from "@/lib/architectureFlow";

const SPEEDS = [0.5, 1, 2] as const;

const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const iconButton =
  "inline-flex size-10 items-center justify-center rounded-xl border border-white/15 bg-white/5 text-white/85 transition-colors hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-35";

export function QuestionPlayer() {
  const [scenarioId, setScenarioId] = useState(SCENARIOS[0].id);
  const [index, setIndex] = useState(0);
  // People who ask for reduced motion get the steps one at a time instead of an auto-playing animation.
  const [playing, setPlaying] = useState(() => !prefersReducedMotion());
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);

  const scenario = SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[0];
  const frames = useMemo(() => buildFrames(scenario, LABELS), [scenario]);
  const frame = frames[index];
  const atEnd = index >= frames.length - 1;
  const running = playing && !atEnd;

  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(() => {
      const next = stepFrame(index, frames.length, 1);
      setIndex(next.index);
      if (next.atEnd) setPlaying(false);
    }, delayForSpeed(speed));
    return () => window.clearTimeout(timer);
  }, [running, index, speed, frames.length]);

  function choose(id: string) {
    setScenarioId(id);
    setIndex(0);
    setPlaying(!prefersReducedMotion());
  }

  function togglePlay() {
    if (atEnd) {
      setIndex(0);
      setPlaying(true);
    } else {
      setPlaying(!running);
    }
  }

  function step(direction: 1 | -1) {
    setPlaying(false);
    setIndex((i) => stepFrame(i, frames.length, direction).index);
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="max-w-2xl text-white/65">Pick a question and watch its data packet travel through the machine. Pause it, step through it, or drag the timeline to any moment.</p>
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Choose a question">
          {SCENARIOS.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                aria-pressed={item.id === scenarioId}
                onClick={() => choose(item.id)}
                className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none ${item.id === scenarioId ? "border-blue-300/60 bg-blue-400/20 text-white" : "border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10"}`}
              >
                {item.title}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <div className="order-2 lg:order-1">
          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#070b18]/80 p-3 sm:p-5">
            <PipelineDiagram activeIds={frame.activeIds} visitedIds={frame.visitedIds} dimUnvisited />
          </div>
        </div>

        <div className="order-1 space-y-4 lg:sticky lg:top-4 lg:order-2 lg:self-start">
          <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-4 backdrop-blur">
            <p className="text-xs font-medium tracking-wide text-blue-300 uppercase">{scenario.title}</p>
            <p className="mt-2 rounded-lg bg-black/30 px-3 py-2 font-mono text-sm">“{scenario.question}”</p>
            <p className="mt-2 text-sm text-white/55">{scenario.blurb}</p>
          </div>

          <div key={frame.index} className="arch-pop rounded-2xl border border-blue-300/25 bg-blue-400/[0.07] p-4" role="status" aria-live="polite">
            <div className="flex items-center justify-between text-xs text-white/55">
              <span>
                Step {index + 1} of {frames.length}
              </span>
              {frame.parallel && <span className="rounded bg-cyan-400/15 px-1.5 py-0.5 text-cyan-200">runs in parallel</span>}
            </div>
            <h3 className="mt-1 text-lg font-semibold tracking-tight">{frame.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-white/80">{frame.note}</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2" role="group" aria-label="Playback controls">
                <button type="button" className={iconButton} onClick={() => { setPlaying(false); setIndex(0); }} disabled={index === 0} aria-label="Back to the start">
                  <RotateCcwIcon aria-hidden="true" className="size-4" />
                </button>
                <button type="button" className={iconButton} onClick={() => step(-1)} disabled={index === 0} aria-label="Previous step">
                  <StepBackIcon aria-hidden="true" className="size-4" />
                </button>
                <button type="button" className={`${iconButton} !w-12 border-blue-300/50 bg-blue-500/25`} onClick={togglePlay} aria-label={running ? "Pause" : atEnd ? "Replay" : "Play"}>
                  {running ? <PauseIcon aria-hidden="true" className="size-4" /> : atEnd ? <RotateCcwIcon aria-hidden="true" className="size-4" /> : <PlayIcon aria-hidden="true" className="size-4" />}
                </button>
                <button type="button" className={iconButton} onClick={() => step(1)} disabled={atEnd} aria-label="Next step">
                  <StepForwardIcon aria-hidden="true" className="size-4" />
                </button>
              </div>
              <div className="flex items-center gap-1" role="group" aria-label="Playback speed">
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={speed === s}
                    onClick={() => setSpeed(s)}
                    className={`rounded-lg px-2.5 py-1.5 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none ${speed === s ? "bg-white/15 text-white" : "text-white/55 hover:bg-white/10"}`}
                  >
                    {s}×
                  </button>
                ))}
              </div>
            </div>

            <input
              type="range"
              min={0}
              max={frames.length - 1}
              value={index}
              onChange={(event) => {
                setPlaying(false);
                setIndex(Number(event.target.value));
              }}
              aria-label="Timeline"
              aria-valuetext={`Step ${index + 1} of ${frames.length}: ${frame.title}`}
              className="mt-4 h-2 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-blue-400"
            />
          </div>

          <ol className="max-h-64 space-y-0.5 overflow-y-auto rounded-2xl border border-white/10 bg-white/[0.03] p-2" aria-label="Steps">
            {frames.map((f) => {
              const done = f.index < index;
              const current = f.index === index;
              return (
                <li key={f.index}>
                  <button
                    type="button"
                    onClick={() => {
                      setPlaying(false);
                      setIndex(f.index);
                    }}
                    aria-current={current ? "step" : undefined}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none ${current ? "bg-blue-400/20 text-white" : "text-white/65 hover:bg-white/[0.07]"}`}
                  >
                    {done ? <CheckCircle2Icon aria-hidden="true" className="size-4 shrink-0 text-emerald-400" /> : <span className={`size-2 shrink-0 rounded-full ${current ? "bg-blue-300 arch-pulse" : "bg-white/25"}`} aria-hidden="true" />}
                    <span className="truncate">{f.title}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}
