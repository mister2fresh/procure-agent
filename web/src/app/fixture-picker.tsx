"use client";

import { useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { startRunAction } from "./actions";

export function FixturePicker({
  fixtures,
  initialSource,
}: {
  fixtures: string[];
  initialSource: string | null;
}): React.ReactElement {
  const visible = fixtures.filter((f) => !f.includes(".notes."));
  const initial = visible[0] ?? "";
  const [selected, setSelected] = useState(initial);
  const [source, setSource] = useState<string | null>(initialSource);
  const [loading, setLoading] = useState(false);
  const isFirstRun = useRef(true);

  useEffect(() => {
    if (!selected) return;
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/fixtures/${encodeURIComponent(selected)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : null))
      .then((text) => {
        if (!cancelled) setSource(text);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Start a new run</CardTitle>
        <CardDescription>
          Each fixture is a quote in a different shape — clean tabular CSVs, prose emails,
          mixed-unit pack sizes, multi-row tier breaks. The same pipeline handles all of them.
        </CardDescription>
      </CardHeader>
      <form action={startRunAction}>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="fixture_filename">Fixture</Label>
            <select
              id="fixture_filename"
              name="fixture_filename"
              required
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
            >
              {visible.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Source preview
            </div>
            <div className="rounded-md border border-input bg-muted/30 max-h-[420px] overflow-auto p-3">
              {source !== null ? (
                <pre className="whitespace-pre-wrap break-words text-xs font-mono leading-relaxed text-foreground/90">
                  {source}
                </pre>
              ) : loading ? (
                <p className="text-xs text-muted-foreground">Loading…</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Binary or unavailable — extraction handles it; preview is text-only.
                </p>
              )}
            </div>
          </div>
        </CardContent>
        <CardFooter className="justify-end">
          <SubmitButton />
        </CardFooter>
      </form>
    </Card>
  );
}

function SubmitButton(): React.ReactElement {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} aria-busy={pending}>
      {pending ? "Running extraction…" : "Run extraction"}
    </Button>
  );
}
