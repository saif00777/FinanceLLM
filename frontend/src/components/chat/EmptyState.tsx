import { LandmarkIcon } from "lucide-react";
import { SuggestedQuestions } from "@/components/chat/SuggestedQuestions";

const STARTER_QUESTIONS = [
  "Show total spending by merchant category",
  "What is the total positive recorded amount by year?",
  "What was the net interest margin in 2025, according to the documents?",
];

export function EmptyState({ onSelect }: { onSelect: (question: string) => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
      <span className="bg-primary/10 text-primary flex size-12 items-center justify-center rounded-2xl">
        <LandmarkIcon aria-hidden="true" className="size-6" />
      </span>
      <div className="space-y-1.5">
        <h1 className="text-lg font-semibold tracking-tight">Ask about your financial data and documents</h1>
        <p className="text-muted-foreground max-w-sm text-sm">
          Ask a natural-language question about transactions, spending, cards and merchant categories, or the bank's documents.
        </p>
      </div>
      <SuggestedQuestions questions={STARTER_QUESTIONS} onSelect={onSelect} disabled={false} />
    </div>
  );
}
