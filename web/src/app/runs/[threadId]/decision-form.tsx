"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { resumeRunAction } from "@/app/actions";
import { LineReviewCard, type LineReviewState } from "@/components/line-review-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { LineDecision, MatchResult, Product, Quote } from "@/lib/schemas";

export function DecisionForm({
  threadId,
  quote,
  matches,
  matchedProducts,
}: {
  threadId: string;
  quote: Quote;
  matches: MatchResult[];
  matchedProducts: Record<string, Product>;
}): React.ReactElement {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("Demo Reviewer");
  const [notes, setNotes] = useState("");
  const [perLine, setPerLine] = useState<Record<number, LineReviewState>>(() =>
    Object.fromEntries(matches.map((m) => [m.line_index, { action: "approve", override_sku: "" }])),
  );

  function handleSubmit(): void {
    setError(null);
    const decisions: LineDecision[] = [];
    for (const m of matches) {
      const s = perLine[m.line_index];
      if (s.action === "override" && !s.override_sku.trim()) {
        setError(`Line #${m.line_index + 1}: override SKU is required`);
        return;
      }
      decisions.push({
        line_index: m.line_index,
        action: s.action,
        override_sku: s.action === "override" ? s.override_sku.trim() : null,
        notes: null,
      });
    }
    startTransition(async () => {
      const result = await resumeRunAction(threadId, reviewer, notes || null, decisions);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      router.refresh();
    });
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight">Review &amp; decide</h2>
        <p className="text-sm text-muted-foreground">
          One decision per line. Override requires a SKU from the product master.
        </p>
      </div>

      <div className="space-y-4">
        {matches.map((match) => (
          <LineReviewCard
            key={match.line_index}
            match={match}
            line={quote.line_items[match.line_index]}
            matchedProduct={match.matched_sku ? (matchedProducts[match.matched_sku] ?? null) : null}
            state={perLine[match.line_index]}
            onChange={(next) => setPerLine((prev) => ({ ...prev, [match.line_index]: next }))}
          />
        ))}
      </div>

      <div className="rounded-md border border-border p-4 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="reviewer">Reviewer</Label>
            <Input id="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="notes">Overall notes (optional)</Label>
          <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Cannot resume</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex justify-end">
        <Button onClick={handleSubmit} disabled={pending} type="button">
          {pending ? "Resuming…" : "Approve & resume"}
        </Button>
      </div>
    </div>
  );
}
