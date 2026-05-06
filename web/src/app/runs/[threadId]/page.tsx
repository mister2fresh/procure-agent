import Link from "next/link";
import { notFound } from "next/navigation";
import { PoPreview } from "@/components/po-preview";
import { QuoteHeader } from "@/components/quote-header";
import { SourcePanel } from "@/components/source-panel";
import { buttonVariants } from "@/components/ui/button";
import { ApiError, fetchFixtureSource, fetchSnapshot } from "@/lib/api";
import { DecisionForm } from "./decision-form";

export default async function RunPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}): Promise<React.ReactElement> {
  const { threadId } = await params;

  const snapshot = await fetchSnapshot(threadId).catch((e) => {
    if (e instanceof ApiError && e.status === 404) {
      return null;
    }
    throw e;
  });
  if (!snapshot) {
    notFound();
  }

  if (!snapshot.quote) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10 space-y-4">
        <p className="text-muted-foreground">Run is still extracting. Refresh in a moment.</p>
        <Link href={`/runs/${threadId}`} className={buttonVariants({ variant: "secondary" })}>
          Refresh
        </Link>
      </div>
    );
  }

  const source = snapshot.fixture_filename
    ? await fetchFixtureSource(snapshot.fixture_filename).catch(() => null)
    : null;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10 space-y-8">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Run</div>
          <code className="text-xs font-mono text-muted-foreground">{threadId}</code>
        </div>
        <Link href="/" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          Start over
        </Link>
      </div>

      <QuoteHeader quote={snapshot.quote} fixtureFilename={snapshot.fixture_filename} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {source && snapshot.fixture_filename ? (
          <SourcePanel filename={snapshot.fixture_filename} source={source} />
        ) : (
          <div className="text-sm text-muted-foreground">Source unavailable.</div>
        )}
        <div>
          {snapshot.status === "pending_approval" ? (
            <DecisionForm threadId={threadId} quote={snapshot.quote} matches={snapshot.matches} />
          ) : snapshot.status === "completed" ? (
            <PoPreview quote={snapshot.quote} matches={snapshot.matches} />
          ) : (
            <p className="text-muted-foreground">Run is still in progress.</p>
          )}
        </div>
      </div>
    </div>
  );
}
