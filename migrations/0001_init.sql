-- Initial schema for procure-agent.
--
-- Owns the procure_agent namespace inside the host database. The schema name
-- mirrors the Supabase shape so local-docker dev and Supabase prod diverge
-- only in DATABASE_URL, never in DDL.

CREATE SCHEMA IF NOT EXISTS procure_agent;

SET search_path = procure_agent, public;

-- Enums mirror the StrEnums in src/procure_agent/schemas.py. Adding a value
-- requires a migration (intentional — catches typos and unplanned drift).
CREATE TYPE procure_agent.category AS ENUM (
    'bearings_drive',
    'cover_crop_seed',
    'fertilizer',
    'hardware_mro',
    'packaging',
    'soil_amendment'
);

CREATE TYPE procure_agent.uom AS ENUM (
    'kg',
    'lb',
    'oz',
    'gal',
    'l',
    'each',
    'case'
);

-- Product master. Mirrors Product in schemas.py 1:1. v1 is denormalized:
-- last_paid_*, on_hand_qty, reorder_point, lead_time_days collapse what an
-- ERP would split into products / price_history / inventory_levels.
CREATE TABLE procure_agent.products (
    sku                     text PRIMARY KEY,
    description             text NOT NULL,
    category                procure_agent.category NOT NULL,
    uom                     procure_agent.uom NOT NULL,
    pack_size               text,
    preferred_supplier_name text NOT NULL,
    last_paid_unit_price    numeric(12, 4) NOT NULL,
    last_paid_currency      text,
    last_paid_date          date NOT NULL,
    reorder_point           integer NOT NULL,
    on_hand_qty             integer NOT NULL,
    lead_time_days          integer NOT NULL
);

-- Extracted quote header. supplier_name is denormalized in v1 — splits out
-- to a suppliers table when supplier-onboarding ships in week 3.
CREATE TABLE procure_agent.quotes (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fixture_filename  text,
    supplier_name     text NOT NULL,
    supplier_ref      text,
    customer_ref      text,
    rfq_ref           text,
    issued_date       date,
    valid_through     date,
    payment_terms     text,
    shipping_terms    text,
    raw_notes         text,
    extracted_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per QuoteLineItem. uom is plain text (not the enum) so non-canonical
-- extraction output lands in the row instead of failing the INSERT — data
-- quality is the eval harness's job, not a constraint that masks failures.
CREATE TABLE procure_agent.quote_line_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id        uuid NOT NULL REFERENCES procure_agent.quotes (id) ON DELETE CASCADE,
    line_index      integer NOT NULL,
    requested_sku   text,
    supplier_sku    text,
    description     text NOT NULL,
    pack_size       text,
    quantity        numeric(14, 4) NOT NULL,
    uom             text NOT NULL,
    unit_price      numeric(12, 4) NOT NULL,
    currency        text,
    tier_prices     jsonb NOT NULL DEFAULT '[]'::jsonb,
    min_order_qty   numeric(14, 4),
    notes           text,
    UNIQUE (quote_id, line_index)
);

CREATE INDEX idx_qli_supplier_sku
    ON procure_agent.quote_line_items (supplier_sku)
    WHERE supplier_sku IS NOT NULL;

CREATE INDEX idx_qli_requested_sku
    ON procure_agent.quote_line_items (requested_sku)
    WHERE requested_sku IS NOT NULL;

-- Workflow trace. langsmith_run_id correlates back to the LangSmith span;
-- final_state snapshots QuoteWorkflowState at the terminal node so a run
-- can be rehydrated for the README's traced-sample-runs section.
CREATE TABLE procure_agent.agent_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow          text NOT NULL,
    fixture_filename  text,
    quote_id          uuid REFERENCES procure_agent.quotes (id) ON DELETE SET NULL,
    langsmith_run_id  text,
    status            text NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    final_state       jsonb
);

CREATE INDEX idx_agent_runs_workflow_started
    ON procure_agent.agent_runs (workflow, started_at DESC);
