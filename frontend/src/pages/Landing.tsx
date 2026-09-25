import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRightIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  CompassIcon,
  EyeIcon,
  EyeOffIcon,
  FileSearchIcon,
  KeyRoundIcon,
  LandmarkIcon,
  Loader2Icon,
  LockKeyholeIcon,
  RadioIcon,
  ShieldCheckIcon,
  SparklesIcon,
  TerminalSquareIcon,
} from "lucide-react";
import { useDarkBody } from "@/hooks/useDarkBody";
import { clearApiKey, getApiKey, saveApiKey, takeLandingNotice } from "@/lib/apiKey";
import { validateApiKey, type KeyCheckResult } from "@/lib/api";

type Phase = "idle" | "checking" | "verified" | "failed";

const HINTS: Record<string, string> = {
  bad_format: "Keys start with sk- and contain no spaces. Copy the whole key from platform.openai.com/api-keys.",
  invalid_key: "Create a new key at platform.openai.com/api-keys and paste it here.",
  no_quota: "Add credit or raise the spending limit on the OpenAI account this key belongs to.",
  no_model_access: "Use a key from a project that has access to the models this assistant uses.",
};

const FEATURES = [
  { icon: TerminalSquareIcon, title: "Ask in plain English", text: "Questions become read-only SQL that is validated before it ever runs." },
  { icon: RadioIcon, title: "Watch it think", text: "Every agent streams what it decided, live, with its assumptions." },
  { icon: FileSearchIcon, title: "Data and documents", text: "Answers from transaction data and the bank's own documents, with citations." },
];

const TRUST = [
  { icon: LockKeyholeIcon, text: "Kept in this tab only" },
  { icon: ShieldCheckIcon, text: "Never written to disk or logs" },
  { icon: SparklesIcon, text: "Tested before launch" },
];

export function Landing({ onLaunch, onHowItWorks }: { onLaunch: () => void; onHowItWorks?: () => void }) {
  useDarkBody();
  const [value, setValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<KeyCheckResult | null>(null);
  const [shaking, setShaking] = useState(false);
  const [notice] = useState(() => takeLandingNotice());
  const [savedKey] = useState(() => getApiKey());
  const abort = useRef<AbortController | null>(null);
  const launchTimer = useRef<number | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    return () => {
      abort.current?.abort();
      window.clearTimeout(launchTimer.current);
    };
  }, []);

  const trimmed = value.trim();
  const busy = phase === "checking" || phase === "verified";

  async function launch(event: FormEvent) {
    event.preventDefault();
    if (!trimmed || busy) return;
    setPhase("checking");
    setResult(null);
    abort.current = new AbortController();
    try {
      const outcome = await validateApiKey(trimmed, abort.current.signal);
      setResult(outcome);
      if (outcome.valid) {
        saveApiKey(trimmed);
        setPhase("verified");
        // Let the person see the green checks before the page changes.
        launchTimer.current = window.setTimeout(onLaunch, 900);
      } else {
        setPhase("failed");
        setShaking(true);
        inputRef.current?.focus();
      }
    } catch {
      /* aborted because the page was left */
    }
  }

  function forgetSavedKey() {
    clearApiKey();
    window.location.reload();
  }

  return (
    <div className="dark relative isolate min-h-svh overflow-clip bg-[#04060f] text-white selection:bg-blue-500/40">
      {/* Atmosphere: drifting colour orbs, a fading grid and a vignette. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="landing-orb absolute -top-40 -left-32 size-[34rem] rounded-full bg-blue-600/40 blur-[120px]" />
        <div className="landing-orb absolute top-1/3 -right-40 size-[30rem] rounded-full bg-violet-600/30 blur-[120px]" style={{ animationDelay: "-5s" }} />
        <div className="landing-orb absolute -bottom-48 left-1/4 size-[28rem] rounded-full bg-cyan-500/20 blur-[120px]" style={{ animationDelay: "-9s" }} />
        <div className="landing-grid absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,#04060f_100%)]" />
      </div>

      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-600/30">
            <LandmarkIcon aria-hidden="true" className="size-[18px]" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Financial Assistant</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70 backdrop-blur md:inline-flex">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            Text-to-SQL · Document RAG
          </span>
          {onHowItWorks && (
            <button type="button" onClick={onHowItWorks} className="inline-flex items-center gap-1.5 rounded-full border border-blue-300/30 bg-blue-400/10 px-3.5 py-1.5 text-xs font-medium text-blue-100 transition-colors hover:bg-blue-400/20 focus-visible:ring-2 focus-visible:ring-blue-300/60 focus-visible:outline-none">
              <CompassIcon aria-hidden="true" className="size-3.5" />
              How it works
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-6xl grid-cols-[minmax(0,1fr)] items-center gap-12 px-6 pt-8 pb-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:gap-16 lg:pt-16">
        <section className="landing-rise min-w-0 space-y-7">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-blue-200 backdrop-blur">
            <SparklesIcon aria-hidden="true" className="size-3.5" />
            Bring your own OpenAI key
          </span>
          <h1 className="text-4xl leading-[1.05] font-semibold tracking-tight text-balance sm:text-6xl">
            Ask your financial data{" "}
            <span className="bg-gradient-to-r from-blue-300 via-indigo-300 to-cyan-200 bg-clip-text text-transparent">anything.</span>
          </h1>
          <p className="max-w-xl text-lg leading-relaxed text-pretty text-white/65">
            A multi-agent assistant that queries your transactions and reads the bank's documents, shows its reasoning as it goes, and
            tells you every assumption it made.
          </p>

          <ul className="grid gap-3 pt-2 sm:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, text }, index) => (
              <li
                key={title}
                className="landing-rise rounded-2xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-sm transition-colors hover:border-white/20 hover:bg-white/[0.06]"
                style={{ animationDelay: `${150 + index * 90}ms` }}
              >
                <Icon aria-hidden="true" className="mb-3 size-5 text-blue-300" />
                <p className="text-sm font-medium">{title}</p>
                <p className="mt-1 text-xs leading-relaxed text-white/55">{text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="landing-rise min-w-0" style={{ animationDelay: "120ms" }} aria-labelledby="key-heading">
          <div className="relative rounded-3xl border border-white/10 bg-white/[0.05] p-6 shadow-2xl shadow-black/50 backdrop-blur-2xl sm:p-8">
            <div aria-hidden="true" className="pointer-events-none absolute inset-x-8 -top-px h-px bg-gradient-to-r from-transparent via-blue-300/60 to-transparent" />
            <div className="mb-6 flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-blue-500/15 ring-1 ring-blue-400/30">
                <KeyRoundIcon aria-hidden="true" className="size-5 text-blue-300" />
              </span>
              <div>
                <h2 id="key-heading" className="text-lg font-semibold tracking-tight">
                  Connect your OpenAI key
                </h2>
                <p className="text-sm text-white/55">We test it before you launch.</p>
              </div>
            </div>

            {notice && phase === "idle" && (
              <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2.5 text-sm text-amber-100">
                <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                {notice}
              </div>
            )}

            <form onSubmit={launch} noValidate className="space-y-4">
              <div className={shaking ? "landing-shake" : undefined} onAnimationEnd={() => setShaking(false)}>
                <label htmlFor="api-key" className="mb-2 block text-sm font-medium text-white/80">
                  OpenAI API key
                </label>
                <div
                  className={`group flex items-center rounded-xl border bg-black/30 transition-colors focus-within:ring-2 ${
                    phase === "failed"
                      ? "border-red-400/60 focus-within:ring-red-400/40"
                      : "border-white/10 focus-within:border-blue-400/60 focus-within:ring-blue-400/30"
                  }`}
                >
                  <input
                    ref={inputRef}
                    id="api-key"
                    name="openai-key"
                    type={reveal ? "text" : "password"}
                    value={value}
                    onChange={(event) => {
                      setValue(event.target.value);
                      if (phase === "failed") setPhase("idle");
                    }}
                    placeholder="sk-proj-…"
                    autoComplete="off"
                    autoCapitalize="off"
                    spellCheck={false}
                    disabled={busy}
                    aria-invalid={phase === "failed"}
                    aria-describedby="key-status"
                    data-1p-ignore
                    className="w-full min-w-0 flex-1 bg-transparent px-4 py-3 font-mono text-sm text-white outline-none placeholder:text-white/30 disabled:opacity-60"
                  />
                  <button
                    type="button"
                    onClick={() => setReveal((shown) => !shown)}
                    aria-label={reveal ? "Hide key" : "Show key"}
                    aria-pressed={reveal}
                    className="mr-1.5 rounded-lg p-2 text-white/50 transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:outline-none"
                  >
                    {reveal ? <EyeOffIcon aria-hidden="true" className="size-4" /> : <EyeIcon aria-hidden="true" className="size-4" />}
                  </button>
                </div>
              </div>

              <div id="key-status" role="status" aria-live="polite" className="min-h-[1.25rem] text-sm">
                {phase === "checking" && (
                  <p className="flex items-center gap-2 text-white/70">
                    <Loader2Icon aria-hidden="true" className="size-4 animate-spin" />
                    Testing your key with OpenAI…
                  </p>
                )}
                {result && (phase === "verified" || phase === "failed") && (
                  <div className="space-y-2">
                    {result.checks.length > 0 && (
                      <ul className="flex flex-wrap gap-2">
                        {result.checks.map((check) => (
                          <li
                            key={check.name}
                            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                              check.ok ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200" : "border-red-400/30 bg-red-400/10 text-red-200"
                            }`}
                          >
                            {check.ok ? <CheckCircle2Icon aria-hidden="true" className="size-3.5" /> : <CircleAlertIcon aria-hidden="true" className="size-3.5" />}
                            {check.name}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className={phase === "verified" ? "text-emerald-300" : "text-red-300"}>{result.message}</p>
                    {phase === "failed" && HINTS[result.code] && <p className="text-xs text-white/50">{HINTS[result.code]}</p>}
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={!trimmed || busy}
                className="group relative inline-flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-blue-500 via-indigo-500 to-violet-500 px-5 py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-600/30 transition-all hover:shadow-blue-500/50 focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#04060f] focus-visible:outline-none enabled:hover:-translate-y-px enabled:active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {phase === "checking" ? (
                  <>
                    <Loader2Icon aria-hidden="true" className="size-4 animate-spin" />
                    Verifying…
                  </>
                ) : phase === "verified" ? (
                  <>
                    <CheckCircle2Icon aria-hidden="true" className="size-4" />
                    Verified — launching
                  </>
                ) : (
                  <>
                    Launch
                    <ArrowRightIcon aria-hidden="true" className="size-4 transition-transform group-enabled:group-hover:translate-x-0.5" />
                  </>
                )}
              </button>
            </form>

            {savedKey && !busy && (
              <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm">
                <span className="text-white/60">A verified key is saved for this tab.</span>
                <span className="flex items-center gap-1">
                  <button type="button" onClick={onLaunch} className="rounded-md px-2 py-1 font-medium text-blue-300 hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:outline-none">
                    Continue
                  </button>
                  <button type="button" onClick={forgetSavedKey} className="rounded-md px-2 py-1 text-white/50 hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:outline-none">
                    Forget
                  </button>
                </span>
              </div>
            )}

            <ul className="mt-6 flex flex-wrap gap-x-5 gap-y-2 border-t border-white/10 pt-5 text-xs text-white/50">
              {TRUST.map(({ icon: Icon, text }) => (
                <li key={text} className="inline-flex items-center gap-1.5">
                  <Icon aria-hidden="true" className="size-3.5 text-white/40" />
                  {text}
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-4 px-2 text-center text-xs leading-relaxed text-white/35">
            Your key is sent only to this app's backend to call OpenAI on your behalf. Use a key with a spending limit.
          </p>
        </section>
      </main>
    </div>
  );
}
