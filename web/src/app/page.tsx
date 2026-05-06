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
import { fetchFixtures } from "@/lib/api";
import { startRunAction } from "./actions";

export default async function Home(): Promise<React.ReactElement> {
  const fixtures = await fetchFixtures();

  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <div className="mb-10 space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">Reconcile a supplier quote</h1>
        <p className="text-muted-foreground leading-relaxed">
          Pick one of the synthetic supplier-quote fixtures below. The agent extracts structured
          line items, matches each to the product master, surfaces divergence flags, and pauses for
          your approval before producing a PO.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Start a new run</CardTitle>
          <CardDescription>
            Each fixture is a quote in a different shape — clean tabular CSVs, prose emails,
            mixed-unit pack sizes, multi-row tier breaks. The same pipeline handles all of them.
          </CardDescription>
        </CardHeader>
        <form action={startRunAction}>
          <CardContent className="space-y-3">
            <Label htmlFor="fixture_filename">Fixture</Label>
            <select
              id="fixture_filename"
              name="fixture_filename"
              required
              defaultValue={fixtures[0] ?? ""}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
            >
              {fixtures.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </CardContent>
          <CardFooter className="justify-end">
            <Button type="submit">Run extraction</Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
