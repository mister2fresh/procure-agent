import type { Product } from "@/lib/schemas";

function Field({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div>
      <span className="text-muted-foreground">{label}:</span>{" "}
      <span className="font-mono">{value}</span>
    </div>
  );
}

export function MatchedProduct({ product }: { product: Product }): React.ReactElement {
  return (
    <div className="rounded-md border bg-muted/30 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="space-y-0.5">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            Master record
          </div>
          <div className="text-sm">{product.description}</div>
        </div>
        <div className="text-right text-xs font-mono text-muted-foreground">{product.sku}</div>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
        <Field label="pack_size" value={product.pack_size ?? "—"} />
        <Field label="uom" value={product.uom} />
        <Field label="on_hand" value={String(product.on_hand_qty)} />
        <Field
          label="last_paid"
          value={`${product.last_paid_unit_price} ${product.last_paid_currency ?? ""}`}
        />
        <Field label="last_paid_date" value={product.last_paid_date} />
        <Field label="preferred_supplier" value={product.preferred_supplier_name} />
      </div>
    </div>
  );
}
