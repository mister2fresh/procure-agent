"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { LineAction, MatchResult, Product, QuoteLineItem } from "@/lib/schemas";
import { FlagBadge } from "./flag-badge";
import { MatchedProduct } from "./matched-product";
import { ProductCombobox } from "./product-combobox";

export type LineReviewState = {
  action: LineAction;
  override_sku: string;
};

export function LineReviewCard({
  match,
  line,
  matchedProduct,
  state,
  onChange,
}: {
  match: MatchResult;
  line: QuoteLineItem;
  matchedProduct: Product | null;
  state: LineReviewState;
  onChange: (next: LineReviewState) => void;
}): React.ReactElement {
  const idx = match.line_index;

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Line #{idx + 1}
            </div>
            <div className="text-base">{line.description}</div>
          </div>
          <div className="text-right text-sm font-mono">
            <div>
              qty {line.quantity} {line.uom}
            </div>
            <div className="text-muted-foreground">
              {line.unit_price} {line.currency ?? ""}/ea
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
          <div>
            <span className="text-muted-foreground">supplier_sku:</span>{" "}
            <span className="font-mono">{line.supplier_sku ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">requested_sku:</span>{" "}
            <span className="font-mono">{line.requested_sku ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">matched:</span>{" "}
            <span className="font-mono">{match.matched_sku ?? "unmatched"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">method:</span>{" "}
            <span className="font-mono">{match.match_method}</span>
            <span className="ml-2 text-muted-foreground">({match.confidence.toFixed(2)})</span>
          </div>
        </div>

        {matchedProduct ? <MatchedProduct product={matchedProduct} /> : null}

        {match.flags.length > 0 ? (
          <div className="flex flex-col gap-2 rounded-md border border-destructive/20 bg-destructive/5 p-3">
            {match.flags.map((flag) => (
              <FlagBadge key={`${flag.kind}-${flag.detail}`} flag={flag} />
            ))}
          </div>
        ) : null}

        <div className="space-y-3 pt-1">
          <RadioGroup
            value={state.action}
            onValueChange={(v) =>
              onChange({
                action: v as LineAction,
                override_sku: v === "override" ? state.override_sku : "",
              })
            }
            className="flex flex-wrap gap-6"
          >
            {(["approve", "reject", "override"] as const).map((a) => (
              <div key={a} className="flex items-center gap-2">
                <RadioGroupItem value={a} id={`action-${idx}-${a}`} />
                <Label htmlFor={`action-${idx}-${a}`} className="font-normal capitalize">
                  {a}
                </Label>
              </div>
            ))}
          </RadioGroup>

          {state.action === "override" ? (
            <ProductCombobox
              inputId={`override-${idx}`}
              value={state.override_sku}
              onChange={(sku) => onChange({ ...state, override_sku: sku })}
            />
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
