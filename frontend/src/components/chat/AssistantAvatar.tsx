/**
 * The assistant's avatar: the app's bank-facade mark (same glyph as the tab icon) on the brand gradient, with a small
 * sparkle badge marking it as the AI. While the assistant is working a soft ring pulses around it.
 */
export function AssistantAvatar({ thinking = false }: { thinking?: boolean }) {
  return (
    <span role="img" aria-label="Assistant" className="relative mt-0.5 inline-flex size-8 shrink-0">
      {thinking && <span aria-hidden="true" className="absolute -inset-1 rounded-full ring-2 ring-blue-400/50 motion-safe:animate-pulse" />}
      <span className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 shadow-sm shadow-blue-600/30">
        <svg viewBox="0 0 24 24" className="size-[18px]" aria-hidden="true">
          <path d="M12 3.2 20.8 9H3.2z" fill="#fff" />
          <circle cx="12" cy="6.9" r="1.1" fill="#f59e0b" />
          <rect x="5.4" y="11" width="3" height="7" rx="0.7" fill="#fff" />
          <rect x="10.5" y="11" width="3" height="7" rx="0.7" fill="#fff" />
          <rect x="15.6" y="11" width="3" height="7" rx="0.7" fill="#fff" />
          <rect x="3.6" y="19.4" width="16.8" height="2" rx="1" fill="#fff" />
        </svg>
      </span>
      <span aria-hidden="true" className="ring-background absolute -right-0.5 -bottom-0.5 flex size-3.5 items-center justify-center rounded-full bg-amber-400 ring-2">
        <svg viewBox="0 0 12 12" className="size-2">
          <path d="M6 0.8c.3 2.4 1.1 3.5 3.5 3.8-2.4.4-3.2 1.4-3.5 3.8-.3-2.4-1.1-3.4-3.5-3.8C4.9 4.3 5.7 3.2 6 .8z" fill="#3b2a05" />
          <circle cx="9.6" cy="9.4" r="1" fill="#3b2a05" />
        </svg>
      </span>
    </span>
  );
}
