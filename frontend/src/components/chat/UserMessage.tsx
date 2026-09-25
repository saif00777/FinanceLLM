export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <p className="bg-primary text-primary-foreground max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
        {content}
      </p>
    </div>
  );
}
