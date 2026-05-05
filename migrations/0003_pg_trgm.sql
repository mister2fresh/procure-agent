-- Enable trigram similarity for fuzzy SKU/description match in the products
-- master. Supplier-side SKU drift (missing dashes, transposed prefixes,
-- pack-suffix appended) needs character-level fuzzy matching that ILIKE and
-- full-text search both fail at; pg_trgm is the right tool for short
-- identifier strings. GIN indexes back the % operator and similarity() ORDER
-- BY so the match query stays sub-millisecond as the catalog grows past 146.
--
-- Installed into public so similarity()/% resolve regardless of search_path.
-- Supabase ships pg_trgm pre-installed (in the extensions schema); the
-- IF NOT EXISTS short-circuits there and the existing install is reused.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE INDEX idx_products_sku_trgm
    ON procure_agent.products
    USING gin (sku gin_trgm_ops);

CREATE INDEX idx_products_description_trgm
    ON procure_agent.products
    USING gin (description gin_trgm_ops);
