import { AlertCircleIcon } from "lucide-react";
import { AssistantAvatar } from "@/components/chat/AssistantAvatar";
import { Separator } from "@/components/ui/separator";
import { ProgressTree } from "@/components/chat/ProgressTree";
import { ResultTabs } from "@/components/chat/ResultTabs";
import { ReasoningDisclosure } from "@/components/chat/ReasoningDisclosure";
import { RouteBadge } from "@/components/chat/RouteBadge";
import { SuggestedQuestions } from "@/components/chat/SuggestedQuestions";
import type { ChatMessage } from "@/hooks/useChat";

export function AssistantMessage({
  message,
  onSelectSuggestion,
  suggestionsDisabled,
}: {
  message: ChatMessage;
  onSelectSuggestion: (question: string) => void;
  suggestionsDisabled: boolean;
}) {
  const { response, error, content, progress, isStreaming } = message;

  return (
    <div className="flex items-start gap-3">
      <AssistantAvatar thinking={isStreaming} />
      <div className="min-w-0 flex-1 space-y-3">
        {isStreaming ? (
          <ProgressTree steps={progress} isStreaming />
        ) : error ? (
          <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm">
            <AlertCircleIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>{content}</span>
          </div>
        ) : (
          <>
            {response && (
              <div className="flex items-center gap-2">
                <RouteBadge route={response.route} />
              </div>
            )}
            <ResultTabs response={response} content={content} />

            <ReasoningDisclosure steps={progress} />

            {response && response.suggested_questions.length > 0 && (
              <>
                <Separator />
                <SuggestedQuestions
                  questions={response.suggested_questions}
                  onSelect={onSelectSuggestion}
                  disabled={suggestionsDisabled}
                />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
