import { useEffect, useRef } from "react";
import { PanelLeftIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { useSidebar } from "@/components/ui/sidebar";
import { AssistantMessage } from "@/components/chat/AssistantMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { EmptyState } from "@/components/chat/EmptyState";
import { UserMessage } from "@/components/chat/UserMessage";
import type { ChatMessage } from "@/hooks/useChat";

export function ChatView({
  messages,
  isSending,
  onSend,
}: {
  messages: ChatMessage[];
  isSending: boolean;
  onSend: (question: string) => void;
}) {
  const { toggleSidebar } = useSidebar();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isSending]);

  return (
    <div className="flex h-svh min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <Button variant="ghost" size="icon" onClick={toggleSidebar} aria-label="Toggle sidebar">
          <PanelLeftIcon aria-hidden="true" className="size-4" />
        </Button>
        <span className="text-sm font-medium">Financial Assistant</span>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </header>

      {messages.length === 0 ? (
        <EmptyState onSelect={onSend} />
      ) : (
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
            {messages.map((message) =>
              message.role === "user" ? (
                <UserMessage key={message.id} content={message.content} />
              ) : (
                <AssistantMessage key={message.id} message={message} onSelectSuggestion={onSend} suggestionsDisabled={isSending} />
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      <ChatInput onSend={onSend} disabled={isSending} />
    </div>
  );
}
