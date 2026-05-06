import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SourcePanel({
  filename,
  source,
}: {
  filename: string;
  source: string;
}): React.ReactElement {
  return (
    <Card className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-hidden">
      <CardHeader className="space-y-1">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">Source quote</div>
        <CardTitle className="text-sm font-mono break-all">{filename}</CardTitle>
      </CardHeader>
      <CardContent className="lg:overflow-auto lg:max-h-[calc(100vh-10rem)]">
        <pre className="whitespace-pre-wrap break-words text-xs font-mono leading-relaxed text-foreground/90">
          {source}
        </pre>
      </CardContent>
    </Card>
  );
}
