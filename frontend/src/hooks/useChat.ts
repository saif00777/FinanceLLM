import { useCallback, useState } from "react";
import { streamChatMessage, type ChatResponse } from "@/lib/api";
import { appendProgressStep, attachThought, type ProgressStep } from "@/lib/graphNodes";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  error?: string;
  progress: ProgressStep[];
  isStreaming: boolean;
}

function makeId(): string {
  return crypto.randomUUID();
}

export function useChat(options: { onAuthError?: (message: string) => void } = {}) {
  const { onAuthError } = options;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  const sendMessage = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isSending) return;

      const userMessage: ChatMessage = { id: makeId(), role: "user", content: trimmed, progress: [], isStreaming: false };
      const assistantId = makeId();
      const assistantPlaceholder: ChatMessage = { id: assistantId, role: "assistant", content: "", progress: [], isStreaming: true };
      setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
      setIsSending(true);

      const updateAssistant = (patch: Partial<ChatMessage>) =>
        setMessages((prev) => prev.map((message) => (message.id === assistantId ? { ...message, ...patch } : message)));

      let eventIndex = 0;
      await streamChatMessage(trimmed, conversationId, {
        onProgress: (node) => {
          eventIndex += 1;
          const index = eventIndex;
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, progress: appendProgressStep(message.progress, node, index) } : message,
            ),
          );
        },
        onThought: (node, text) => {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, progress: attachThought(message.progress, node, text) } : message,
            ),
          );
        },
        onResult: (response) => {
          setConversationId(response.conversation_id);
          updateAssistant({ content: response.answer, response, isStreaming: false });
        },
        onError: (message, _requestId, code) => {
          updateAssistant({ content: message, error: message, isStreaming: false });
          if (code === "invalid_api_key" || code === "missing_api_key") onAuthError?.(message);
        },
      });
      setIsSending(false);
    },
    [conversationId, isSending, onAuthError],
  );

  const startNewConversation = useCallback(() => {
    setMessages([]);
    setConversationId(null);
  }, []);

  return { messages, isSending, sendMessage, startNewConversation };
}
