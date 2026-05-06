"""Postgres query layer for procure_agent.

Thin wrapper around psycopg. Opens connections from ``DATABASE_URL``, runs
hand-written SQL, hydrates rows into :class:`Product`. Match/flag node bodies
in :mod:`procure_agent.graph` call into here for product-master lookups.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from procure_agent.schemas import Product


@dataclass(frozen=True, slots=True)
class ScoredProduct:
    """A product paired with the trigram similarity score that surfaced it.

    Returned by the fuzzy-match helpers so callers (notably ``match_node``)
    can record the score on ``MatchResult.confidence`` without re-running
    ``similarity()``.
    """

    product: Product
    score: float


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Open a procure_agent connection from ``DATABASE_URL``.

    Sets ``row_factory=dict_row`` so columns come back keyed for Pydantic
    hydration, and ``search_path=procure_agent,public`` so unqualified table
    names resolve to the procure_agent schema while pg_trgm operators in
    public stay visible.

    Yields:
        Open ``psycopg.Connection``. The context manager closes it on exit.

    Raises:
        RuntimeError: ``DATABASE_URL`` is not set.
        psycopg.OperationalError: The server is unreachable.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET search_path = procure_agent, public")
        yield conn


def get_product(conn: psycopg.Connection, sku: str) -> Product | None:
    """Look up one product by exact SKU.

    Args:
        conn: Open connection (use :func:`connect`).
        sku: Exact SKU to match.

    Returns:
        The matching :class:`Product`, or ``None`` if no row matches.
    """
    row = conn.execute("SELECT * FROM products WHERE sku = %s", (sku,)).fetchone()
    return Product.model_validate(row) if row else None


def _hydrate_scored(rows: list[dict]) -> list[ScoredProduct]:
    """Hydrate ``(product, score)`` pairs from rows with a ``score`` column."""
    return [
        ScoredProduct(
            product=Product.model_validate({k: v for k, v in r.items() if k != "score"}),
            score=float(r["score"]),
        )
        for r in rows
    ]


def find_products_by_sku_similarity(
    conn: psycopg.Connection,
    sku: str,
    limit: int = 5,
    threshold: float = 0.3,
) -> list[ScoredProduct]:
    """Find products whose SKU is fuzzily similar to ``sku``.

    Uses pg_trgm trigram similarity against ``products.sku``. Survives the
    common supplier-side SKU drifts (dashes dropped, prefixes transposed,
    pack codes suffixed) that exact lookup and ``ILIKE`` both miss.

    Args:
        conn: Open connection.
        sku: Candidate SKU string from a quote line item.
        limit: Maximum rows to return.
        threshold: Minimum trigram similarity (0.0-1.0) to include.

    Returns:
        Scored products ordered by similarity descending. Empty list when
        no row clears ``threshold``.
    """
    rows = conn.execute(
        """
        SELECT *, similarity(sku, %s) AS score
        FROM products
        WHERE similarity(sku, %s) >= %s
        ORDER BY score DESC, sku ASC
        LIMIT %s
        """,
        (sku, sku, threshold, limit),
    ).fetchall()
    return _hydrate_scored(rows)


def get_products_by_skus(conn: psycopg.Connection, skus: list[str]) -> dict[str, Product]:
    """Bulk lookup by SKU. Returns a dict keyed by SKU; missing rows are simply absent."""
    if not skus:
        return {}
    rows = conn.execute("SELECT * FROM products WHERE sku = ANY(%s)", (skus,)).fetchall()
    return {r["sku"]: Product.model_validate(r) for r in rows}


def search_products(conn: psycopg.Connection, query: str, limit: int = 20) -> list[Product]:
    """Typeahead search across SKU and description.

    Plain ``ILIKE %q%`` against both columns; SKU hits sort first since a reviewer
    typing in the override picker is usually typing a SKU prefix. Empty query
    returns the first ``limit`` products by SKU so the picker is never blank on
    open.
    """
    pattern = f"%{query}%" if query else "%"
    rows = conn.execute(
        """
        SELECT *,
            CASE WHEN sku ILIKE %s THEN 0 ELSE 1 END AS sku_match
        FROM products
        WHERE sku ILIKE %s OR description ILIKE %s
        ORDER BY sku_match, sku
        LIMIT %s
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [Product.model_validate({k: v for k, v in r.items() if k != "sku_match"}) for r in rows]


def insert_agent_run(
    conn: psycopg.Connection,
    *,
    workflow: str,
    fixture_filename: str | None,
    thread_id: str,
    status: str,
) -> str:
    """Insert a new ``agent_runs`` row at run start. Returns the row id.

    ``started_at`` defaults to ``now()`` server-side. ``final_state``,
    ``completed_at``, ``quote_id``, and ``langsmith_run_id`` are filled in by
    :func:`update_agent_run` once the run reaches a terminal state.

    Args:
        conn: Open connection.
        workflow: Workflow identifier (e.g. ``"quote_reconciliation"``).
        fixture_filename: Fixture name when the run is fixture-driven; ``None``
            for ad-hoc invocations.
        thread_id: LangGraph checkpoint thread_id; the correlator the resume
            endpoint uses to find this row.
        status: Initial status string (typically ``"running"``).

    Returns:
        The new row's UUID, stringified.
    """
    row = conn.execute(
        """
        INSERT INTO agent_runs (workflow, fixture_filename, thread_id, status)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (workflow, fixture_filename, thread_id, status),
    ).fetchone()
    return str(row["id"])


def get_agent_run_id_by_thread_id(
    conn: psycopg.Connection, thread_id: str
) -> str | None:
    """Look up the most-recent ``agent_runs.id`` for a ``thread_id``.

    A thread_id is reusable in principle (a caller could pass the same one to
    two ``POST /runs`` calls); ``ORDER BY started_at DESC LIMIT 1`` resolves
    that ambiguity to "the live run we'd be resuming."

    Returns:
        The row id stringified, or ``None`` if no row matches — typical when
        the run was started before agent_runs wiring landed.
    """
    row = conn.execute(
        """
        SELECT id FROM agent_runs
        WHERE thread_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (thread_id,),
    ).fetchone()
    return str(row["id"]) if row else None


def update_agent_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    status: str,
    final_state: dict | None = None,
    langsmith_run_id: str | None = None,
    completed: bool = False,
) -> None:
    """Update an ``agent_runs`` row — status transition and/or terminal write.

    Designed for the API-handler write path: ``start_run`` updates to
    ``pending_approval`` after the graph hits the interrupt; ``resume_run``
    updates to ``completed`` (with ``completed=True`` to stamp ``completed_at``)
    after the graph reaches END; either may transition to ``failed`` from a
    handler-level ``except`` block.

    Args:
        conn: Open connection.
        run_id: Row id from :func:`insert_agent_run`.
        status: New status string.
        final_state: JSONB-bound projection of ``QuoteWorkflowState``. Pass
            ``None`` on intermediate transitions.
        langsmith_run_id: LangSmith span correlator. Pass ``None`` if unknown.
        completed: When ``True``, stamp ``completed_at = now()``. Pair with a
            terminal status (``completed``/``failed``).
    """
    sets = ["status = %s"]
    params: list = [status]
    if final_state is not None:
        sets.append("final_state = %s")
        params.append(Json(final_state))
    if langsmith_run_id is not None:
        sets.append("langsmith_run_id = %s")
        params.append(langsmith_run_id)
    if completed:
        sets.append("completed_at = now()")
    params.append(run_id)
    conn.execute(
        f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
    )


def find_products_by_description_similarity(
    conn: psycopg.Connection,
    description: str,
    limit: int = 5,
    threshold: float = 0.45,
) -> list[ScoredProduct]:
    """Find products whose description is fuzzily similar to ``description``.

    Same trigram approach as :func:`find_products_by_sku_similarity`, against
    ``products.description``. Useful when the supplier omitted a SKU or sent
    a prose-only quote.

    Args:
        conn: Open connection.
        description: Candidate description string from a quote line item.
        limit: Maximum rows to return.
        threshold: Minimum trigram similarity (0.0-1.0) to include.

    Returns:
        Scored products ordered by similarity descending.
    """
    rows = conn.execute(
        """
        SELECT *, similarity(description, %s) AS score
        FROM products
        WHERE similarity(description, %s) >= %s
        ORDER BY score DESC, sku ASC
        LIMIT %s
        """,
        (description, description, threshold, limit),
    ).fetchall()
    return _hydrate_scored(rows)
