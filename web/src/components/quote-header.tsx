import { Card, CardContent } from "@/components/ui/card";
import type { Quote } from "@/lib/schemas";

function MetaCell({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="space-y-1">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

export function QuoteHeader({
  quote,
  fixtureFilename,
}: {
  quote: Quote;
  fixtureFilename: string | null;
}): React.ReactElement {
  return (
    <Card>
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-1">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">Supplier</div>
          <h2 className="text-2xl font-semibold tracking-tight">{quote.supplier_name}</h2>
          {fixtureFilename ? (
            <div className="text-xs font-mono text-muted-foreground">{fixtureFilename}</div>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <MetaCell label="Supplier ref" value={quote.supplier_ref ?? "—"} />
          <MetaCell label="Customer ref" value={quote.customer_ref ?? "—"} />
          <MetaCell label="RFQ ref" value={quote.rfq_ref ?? "—"} />
          <MetaCell label="Issued" value={quote.issued_date ?? "—"} />
          <MetaCell label="Valid through" value={quote.valid_through ?? "—"} />
          <MetaCell label="Payment terms" value={quote.payment_terms ?? "—"} />
          <MetaCell label="Shipping" value={quote.shipping_terms ?? "—"} />
        </div>
      </CardContent>
    </Card>
  );
}
