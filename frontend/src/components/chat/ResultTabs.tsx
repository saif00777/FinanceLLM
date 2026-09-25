import { CompassIcon, BarChart3Icon, TableIcon, MessageSquareTextIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AnalysisPanel } from "@/components/chat/AnalysisPanel";
import { AssumptionsPanel } from "@/components/chat/AssumptionsPanel";
import { ChartRenderer } from "@/components/chat/ChartRenderer";
import { CitationsList } from "@/components/chat/CitationsList";
import { ResultsTable } from "@/components/chat/ResultsTable";
import { SqlDisclosure } from "@/components/chat/SqlDisclosure";
import type { ChatResponse } from "@/lib/api";

/** Answer is always there; Assumptions, Chart and Table appear only when the response has something to show. */
export function ResultTabs({ response, content }: { response: ChatResponse | undefined; content: string }) {
  const assumptions = response?.assumptions ?? [];
  const hasRows = !!response && response.rows.length > 0;
  const hasChart = hasRows && !!response?.chart;

  const answer = (
    <>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
      {response?.sql && <SqlDisclosure sql={response.sql} />}
      {response?.analysis && <AnalysisPanel analysis={response.analysis} />}
      {response && response.citations.length > 0 && <CitationsList citations={response.citations} />}
    </>
  );

  if (assumptions.length === 0 && !hasRows) return <div className="space-y-3">{answer}</div>;

  return (
    <Tabs defaultValue="answer">
      <TabsList aria-label="Answer views">
        <TabsTrigger value="answer">
          <MessageSquareTextIcon aria-hidden="true" className="size-3.5" />
          Answer
        </TabsTrigger>
        {assumptions.length > 0 && (
          <TabsTrigger value="assumptions">
            <CompassIcon aria-hidden="true" className="size-3.5" />
            Assumptions ({assumptions.length})
          </TabsTrigger>
        )}
        {hasChart && (
          <TabsTrigger value="chart">
            <BarChart3Icon aria-hidden="true" className="size-3.5" />
            Chart
          </TabsTrigger>
        )}
        {hasRows && (
          <TabsTrigger value="table">
            <TableIcon aria-hidden="true" className="size-3.5" />
            Table ({response.row_count})
          </TabsTrigger>
        )}
      </TabsList>
      <TabsContent value="answer">{answer}</TabsContent>
      {assumptions.length > 0 && (
        <TabsContent value="assumptions">
          <AssumptionsPanel assumptions={assumptions} />
        </TabsContent>
      )}
      {hasChart && response?.chart && (
        <TabsContent value="chart">
          <ChartRenderer chart={response.chart} columns={response.columns} rows={response.rows} />
        </TabsContent>
      )}
      {hasRows && (
        <TabsContent value="table">
          <ResultsTable columns={response.columns} rows={response.rows} />
        </TabsContent>
      )}
    </Tabs>
  );
}
