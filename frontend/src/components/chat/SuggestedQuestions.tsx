import { SparklesIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SuggestedQuestions({
  questions,
  onSelect,
  disabled,
}: {
  questions: string[];
  onSelect: (question: string) => void;
  disabled: boolean;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SparklesIcon aria-hidden="true" className="text-muted-foreground size-3.5" />
      {questions.map((question) => (
        <Button
          key={question}
          type="button"
          variant="outline"
          size="sm"
          className="h-auto rounded-full px-3 py-1.5 text-xs font-normal whitespace-normal"
          disabled={disabled}
          onClick={() => onSelect(question)}
        >
          {question}
        </Button>
      ))}
    </div>
  );
}
