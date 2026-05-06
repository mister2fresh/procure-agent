import { fetchFixtureSource, fetchFixtures } from "@/lib/api";
import { FixturePicker } from "./fixture-picker";

export default async function Home(): Promise<React.ReactElement> {
  const fixtures = await fetchFixtures();
  const initial = fixtures[0] ?? "";
  const initialSource = initial ? await fetchFixtureSource(initial).catch(() => null) : null;

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

      <FixturePicker fixtures={fixtures} initialSource={initialSource} />
    </div>
  );
}
