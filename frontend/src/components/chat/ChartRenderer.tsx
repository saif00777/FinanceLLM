import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { ChartSpec } from "@/lib/api";

const MAX_POINTS = 25;

const chartConfig = {
  value: { label: "Value", color: "var(--chart-1)" },
} satisfies ChartConfig;

export function ChartRenderer({ chart, columns, rows }: { chart: ChartSpec; columns: string[]; rows: unknown[][] }) {
  const xKey = typeof chart.x === "string" ? chart.x : undefined;
  const yKey = typeof chart.y === "string" ? chart.y : undefined;
  if (!xKey || !yKey) return null;

  const xIndex = columns.indexOf(xKey);
  const yIndex = columns.indexOf(yKey);
  if (xIndex === -1 || yIndex === -1) return null;

  const data = rows
    .slice(0, MAX_POINTS)
    .map((row) => ({ label: String(row[xIndex] ?? "—"), value: Number(row[yIndex]) }))
    .filter((point) => Number.isFinite(point.value));
  if (data.length === 0) return null;

  const isTrend = typeof chart.type === "string" && chart.type.toLowerCase().includes("line");
  const truncated = rows.length > MAX_POINTS;

  return (
    <div className="space-y-1">
      <ChartContainer config={chartConfig} className="max-h-64 w-full">
        {isTrend ? (
          <LineChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} fontSize={12} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line dataKey="value" type="monotone" stroke="var(--chart-1)" strokeWidth={2} dot={false} />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} fontSize={12} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="value" fill="var(--chart-1)" radius={4} />
          </BarChart>
        )}
      </ChartContainer>
      {truncated && (
        <p className="text-muted-foreground text-xs">
          Showing the first {MAX_POINTS} of {rows.length} rows — see the full table below.
        </p>
      )}
    </div>
  );
}
