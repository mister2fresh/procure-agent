"""Smoke tests for the procure_agent.db query layer.

Hits the real database (local docker via DATABASE_URL) so trigram queries,
enum casting, and Pydantic hydration all run end-to-end. Skips when the DB
is unreachable -- same pattern as test_migrations.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from procure_agent.db import (
    connect,
    find_products_by_description_similarity,
    find_products_by_sku_similarity,
    get_product,
)
from procure_agent.schemas import Product

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def _require_db() -> None:
    """Skip the module if DATABASE_URL is unset or the server is unreachable."""
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(url):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"DATABASE_URL unreachable: {exc}")


def test_get_product_hydrates_pydantic_model() -> None:
    with connect() as conn:
        product = get_product(conn, "STRAP-PP-58")
    assert isinstance(product, Product)
    assert product.sku == "STRAP-PP-58"
    assert product.description == "Polypropylene strapping machine grade"


def test_get_product_unknown_sku_returns_none() -> None:
    with connect() as conn:
        product = get_product(conn, "DOES-NOT-EXIST-9999")
    assert product is None


def test_sku_similarity_recovers_drifted_sku() -> None:
    """Dashes-dropped variant of a real SKU still resolves via trigrams."""
    with connect() as conn:
        results = find_products_by_sku_similarity(conn, "STRAPPP58")
    assert any(hit.product.sku == "STRAP-PP-58" for hit in results)


def test_sku_similarity_ranks_exact_match_first() -> None:
    with connect() as conn:
        results = find_products_by_sku_similarity(conn, "STRAP-PP-58", limit=10)
    assert results, "expected at least one match"
    assert results[0].product.sku == "STRAP-PP-58"
    assert results[0].score == pytest.approx(1.0)


def test_sku_similarity_score_in_unit_range() -> None:
    """Trigram scores survive the round-trip into ``ScoredProduct.score``."""
    with connect() as conn:
        results = find_products_by_sku_similarity(conn, "STRAPPP58", limit=10)
    assert results, "expected at least one match"
    for hit in results:
        assert 0.0 < hit.score <= 1.0


def test_sku_similarity_respects_limit() -> None:
    with connect() as conn:
        results = find_products_by_sku_similarity(conn, "AL", limit=3, threshold=0.0)
    assert len(results) <= 3


def test_sku_similarity_garbage_returns_empty() -> None:
    with connect() as conn:
        results = find_products_by_sku_similarity(conn, "ZZZZZZZZZZ-NOPE-99999")
    assert results == []


def test_description_similarity_finds_known_product() -> None:
    """A description fragment locates the canonical row."""
    with connect() as conn:
        results = find_products_by_description_similarity(conn, "polypropylene strapping")
    assert any(hit.product.sku == "STRAP-PP-58" for hit in results)


def test_description_similarity_ranks_closest_first() -> None:
    with connect() as conn:
        results = find_products_by_description_similarity(conn, "Aloe vera extract food grade")
    assert results, "expected at least one match"
    assert results[0].product.sku == "AL101"
