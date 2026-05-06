import { Badge } from "@/components/ui/badge";
import type { Flag } from "@/lib/schemas";

const labels: Record<Flag["kind"], string> = {
  unmatched: "unmatched",
  price_variance: "price variance",
  currency_mismatch: "currency mismatch",
  pack_size_drift: "pack size drift",
  uom_mismatch: "UoM mismatch",
};

export function FlagBadge({ flag }: { flag: Flag }): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-2">
      <Badge variant="destructive" className="font-mono text-[10px] uppercase tracking-wider">
        {labels[flag.kind]}
      </Badge>
      <span className="text-xs text-muted-foreground">{flag.detail}</span>
    </span>
  );
}
