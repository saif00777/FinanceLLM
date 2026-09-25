import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export function ResultsTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (columns.length === 0 || rows.length === 0) return null;

  return (
    <ScrollArea className="w-full rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column} className="font-mono text-xs whitespace-nowrap">
                {column}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, rowIndex) => (
            // eslint-disable-next-line react/no-array-index-key -- rows carry no stable identity from the backend
            <TableRow key={rowIndex}>
              {row.map((value, cellIndex) => (
                // eslint-disable-next-line react/no-array-index-key
                <TableCell key={cellIndex} className="whitespace-nowrap tabular-nums">
                  {formatCell(value)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
}
