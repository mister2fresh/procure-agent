import { z } from "zod";

// Mirrors src/procure_agent/state.py and src/procure_agent/schemas.py.
// Decimal/date fields arrive as strings (FastAPI JSON-mode serialization).

export const matchMethodSchema = z.enum([
  "supplier_sku_exact",
  "requested_sku_exact",
  "supplier_sku_fuzzy",
  "requested_sku_fuzzy",
  "description_fuzzy",
  "unmatched",
  "human_override",
]);
export type MatchMethod = z.infer<typeof matchMethodSchema>;

export const exceptionKindSchema = z.enum([
  "unmatched",
  "price_variance",
  "currency_mismatch",
  "pack_size_drift",
  "uom_mismatch",
]);
export type ExceptionKind = z.infer<typeof exceptionKindSchema>;

export const lineActionSchema = z.enum(["approve", "reject", "override"]);
export type LineAction = z.infer<typeof lineActionSchema>;

export const runStatusSchema = z.enum(["pending_approval", "completed", "in_progress"]);
export type RunStatus = z.infer<typeof runStatusSchema>;

export const flagSchema = z.object({
  kind: exceptionKindSchema,
  detail: z.string(),
});
export type Flag = z.infer<typeof flagSchema>;

export const tierPriceSchema = z.object({
  min_qty: z.string(),
  unit_price: z.string(),
});
export type TierPrice = z.infer<typeof tierPriceSchema>;

export const quoteLineItemSchema = z.object({
  requested_sku: z.string().nullable(),
  supplier_sku: z.string().nullable(),
  description: z.string(),
  pack_size: z.string().nullable(),
  quantity: z.string(),
  uom: z.string(),
  unit_price: z.string(),
  currency: z.string().nullable(),
  tier_prices: z.array(tierPriceSchema),
  min_order_qty: z.string().nullable(),
  notes: z.string().nullable(),
});
export type QuoteLineItem = z.infer<typeof quoteLineItemSchema>;

export const quoteSchema = z.object({
  supplier_name: z.string(),
  supplier_ref: z.string().nullable(),
  customer_ref: z.string().nullable(),
  rfq_ref: z.string().nullable(),
  issued_date: z.string().nullable(),
  valid_through: z.string().nullable(),
  line_items: z.array(quoteLineItemSchema),
  payment_terms: z.string().nullable(),
  shipping_terms: z.string().nullable(),
  raw_notes: z.string().nullable(),
});
export type Quote = z.infer<typeof quoteSchema>;

export const productSchema = z.object({
  sku: z.string(),
  description: z.string(),
  category: z.string(),
  uom: z.string(),
  pack_size: z.string().nullable(),
  preferred_supplier_name: z.string(),
  last_paid_unit_price: z.string(),
  last_paid_currency: z.string().nullable(),
  last_paid_date: z.string(),
  reorder_point: z.number().int(),
  on_hand_qty: z.number().int(),
  lead_time_days: z.number().int(),
});
export type Product = z.infer<typeof productSchema>;

export const matchResultSchema = z.object({
  line_index: z.number().int(),
  matched_sku: z.string().nullable(),
  match_method: matchMethodSchema,
  confidence: z.number(),
  flags: z.array(flagSchema),
  human_action: lineActionSchema.nullable(),
});
export type MatchResult = z.infer<typeof matchResultSchema>;

export const lineDecisionSchema = z
  .object({
    line_index: z.number().int(),
    action: lineActionSchema,
    override_sku: z.string().nullable(),
    notes: z.string().nullable(),
  })
  .refine(
    (d) =>
      (d.action === "override" && !!d.override_sku) ||
      (d.action !== "override" && d.override_sku === null),
    { message: "override_sku is required for OVERRIDE and forbidden otherwise" },
  );
export type LineDecision = z.infer<typeof lineDecisionSchema>;

export const humanDecisionSchema = z.object({
  reviewer: z.string(),
  decided_at: z.string(),
  line_decisions: z.array(lineDecisionSchema),
  overall_notes: z.string().nullable(),
});
export type HumanDecision = z.infer<typeof humanDecisionSchema>;

export const runSnapshotSchema = z.object({
  thread_id: z.string(),
  status: runStatusSchema,
  fixture_filename: z.string().nullable(),
  quote: quoteSchema.nullable(),
  matches: z.array(matchResultSchema),
  matched_products: z.record(z.string(), productSchema),
  human_decision: humanDecisionSchema.nullable(),
});
export type RunSnapshot = z.infer<typeof runSnapshotSchema>;

export const resumeRequestSchema = z.object({
  reviewer: z.string().min(1),
  line_decisions: z.array(lineDecisionSchema),
  overall_notes: z.string().nullable(),
});
export type ResumeRequest = z.infer<typeof resumeRequestSchema>;
