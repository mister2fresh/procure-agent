import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { MatchResult, Quote } from "@/lib/schemas";
import { FlagBadge } from "./flag-badge";

export function PoPreview({
  quote,
  matches,
}: {
  quote: Quote;
  matches: MatchResult[];
}): React.ReactElement {
  const approved = matches.filter(
    (m) => m.human_action === "approve" || m.human_action === "override",
  );
  const rejected = matches.filter((m) => m.human_action === "reject");

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            <span>Proposed PO</span>
            <Badge variant="secondary">
              {approved.length} of {matches.length} lines
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {approved.length === 0 ? (
            <p className="text-sm text-muted-foreground">No lines approved.</p>
          ) : (
            approved.map((match) => {
              const line = quote.line_items[match.line_index];
              return (
                <div
                  key={match.line_index}
                  className="rounded-md border border-border p-4 space-y-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="flex items-baseline gap-3">
                      <span className="font-mono text-sm font-semibold">{match.matched_sku}</span>
                      <span className="text-sm">{line.description}</span>
                    </div>
                    <Badge variant={match.human_action === "override" ? "default" : "secondary"}>
                      {match.human_action}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
                    <div>
                      <span className="text-muted-foreground">qty:</span>{" "}
                      <span className="font-mono">
                        {line.quantity} {line.uom}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">unit price:</span>{" "}
                      <span className="font-mono">
                        {line.unit_price} {line.currency ?? ""}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">match:</span>{" "}
                      <span className="font-mono">{match.match_method}</span>
                    </div>
                  </div>
                  {match.flags.length > 0 ? (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {match.flags.map((flag) => (
                        <FlagBadge key={`${flag.kind}-${flag.detail}`} flag={flag} />
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      {rejected.length > 0 ? (
        <>
          <Separator />
          <Card>
            <CardHeader>
              <CardTitle className="text-muted-foreground">Rejected</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {rejected.map((match) => {
                const line = quote.line_items[match.line_index];
                return (
                  <div key={match.line_index} className="text-sm text-muted-foreground">
                    <span className="line-through">{line.description}</span>
                    <span className="ml-2 font-mono text-xs">
                      ({line.quantity} {line.uom})
                    </span>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
