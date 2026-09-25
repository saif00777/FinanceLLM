import { useRef, useState, type KeyboardEvent } from "react";
import { SendHorizonalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const MAX_LENGTH = 2000;

export function ChatInput({ onSend, disabled }: { onSend: (question: string) => void; disabled: boolean }) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    requestAnimationFrame(() => {
      if (textareaRef.current) textareaRef.current.style.height = "auto";
    });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const handleInput = (event: React.FormEvent<HTMLTextAreaElement>) => {
    const el = event.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="bg-background border-t p-4">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask about transactions, spending trends, or the bank's documents…"
          aria-label="Ask a question"
          maxLength={MAX_LENGTH}
          rows={1}
          disabled={disabled}
          className="max-h-48 min-h-11 resize-none py-2.5"
        />
        <Button
          type="button"
          size="icon"
          className="size-11 shrink-0 rounded-xl"
          disabled={disabled || value.trim().length === 0}
          onClick={submit}
          aria-label="Send question"
        >
          <SendHorizonalIcon aria-hidden="true" className="size-4" />
        </Button>
      </div>
      <p className="text-muted-foreground mx-auto mt-2 max-w-3xl text-center text-xs">
        Answers are grounded in the transaction dataset and the (synthetic) bank documents — not financial advice.
      </p>
    </div>
  );
}
