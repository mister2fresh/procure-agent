"""FastAPI HITL endpoint over the LangGraph quote-reconciliation workflow.

Three endpoints:
    POST /runs               — start a run; invokes the graph to its
                               ``interrupt_before=["approval"]`` pause point
    GET  /runs/{thread_id}   — fetch the snapshot at the current pause, or
                               the final state after resume
    POST /runs/{thread_id}/resume — inject a :class:`HumanDecision` and run
                                    to END

Plus two helpers:
    GET  /fixtures           — list available synthetic-quote fixtures so the
                               frontend can populate a dropdown
    GET  /health             — Railway healthcheck; cheap, no DB call

Connection strategy: per-request ``PostgresSaver.from_conn_string`` context
manager. Demo traffic is recruiter-scale; a connection pool is the next-day
optimization, not a v1 requirement.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

from procure_agent.agent import read_file
from procure_agent.db import (
    connect,
    get_agent_run_id_by_thread_id,
    get_products_by_skus,
    insert_agent_run,
    search_products,
    update_agent_run,
)
from procure_agent.graph import build_graph
from procure_agent.schemas import Product
from procure_agent.state import (
    HumanDecision,
    LineAction,
    LineDecision,
    MatchResult,
    QuoteWorkflowState,
)

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
QUOTES_DIR = REPO_ROOT / "data" / "synthetic_quotes"
SOURCE_EXTS = {".txt", ".csv", ".md", ".docx", ".eml"}

app = FastAPI(title="procure-agent HITL", version="0.1.0")

# Browser-side dev calls hit the API directly during local dev; in production
# the Next.js service proxies same-origin so CORS is moot. ``CORS_ORIGINS`` is
# a comma-separated allowlist; defaults cover the local dev origin.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Railway healthcheck. Cheap; intentionally does not hit the DB."""
    return {"status": "ok"}


def _database_url() -> str:
    """Read DATABASE_URL or 503 — caller is responsible for surfacing the error."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    return url


# --- request / response models ----------------------------------------------


class StartRunRequest(BaseModel):
    """Kick off a new graph run against a synthetic-quote fixture."""

    fixture_filename: str = Field(..., description="Filename inside data/synthetic_quotes/")
    thread_id: str | None = Field(
        None,
        description="Caller-supplied checkpoint thread_id. Auto-generated when omitted.",
    )


class ResumeRequest(BaseModel):
    """Human-reviewer payload for the ``approval`` interrupt.

    ``decided_at`` is set server-side at this boundary — clients omit it.
    """

    reviewer: str
    line_decisions: list[LineDecision]
    overall_notes: str | None = None


class RunSnapshot(BaseModel):
    """Public-facing view of a run. Excludes the LLM ``messages`` history."""

    thread_id: str
    status: str
    fixture_filename: str | None = None
    quote: dict[str, Any] | None = None
    matches: list[MatchResult] = Field(default_factory=list)
    matched_products: dict[str, Product] = Field(
        default_factory=dict,
        description=(
            "Catalog rows for every SKU referenced by ``matches``, keyed by SKU. "
            "Bundled into the snapshot so the UI can render per-line master detail "
            "in one fetch."
        ),
    )
    human_decision: HumanDecision | None = None


# --- helpers ----------------------------------------------------------------


def _status_for(snapshot_next: tuple[str, ...]) -> str:
    """Map LangGraph's ``snapshot.next`` to a public status string."""
    if not snapshot_next:
        return "completed"
    if snapshot_next == ("approval",):
        return "pending_approval"
    return "in_progress"


def _record_run_state(
    run_id: str | None, thread_id: str, values: dict, status: str
) -> None:
    """Update the ``agent_runs`` row with a status transition and ``final_state``.

    No-op when ``run_id`` is ``None`` (run was started before agent_runs wiring
    or the insert was skipped). Stamps ``completed_at`` only on the terminal
    ``"completed"`` status — non-terminal transitions like ``"pending_approval"``
    leave it null so the row reflects an in-flight run.
    """
    if not run_id:
        return
    with connect() as conn:
        update_agent_run(
            conn,
            run_id=run_id,
            status=status,
            final_state=_serialize_final_state(thread_id, values),
            completed=(status == "completed"),
        )


def _mark_run_failed(run_id: str | None) -> None:
    """Mark the ``agent_runs`` row failed and stamp ``completed_at``.

    No ``final_state`` payload — partial graph state on exception is rarely
    coherent, and the status row alone is sufficient to surface the failure
    in eval/README contexts. Add structured failure detail later if debugging
    against the row becomes a recurring need.
    """
    if not run_id:
        return
    with connect() as conn:
        update_agent_run(conn, run_id=run_id, status="failed", completed=True)


def _serialize_final_state(thread_id: str, values: dict) -> dict[str, Any]:
    """Project ``QuoteWorkflowState`` to the JSONB-bound shape stored on
    ``agent_runs.final_state``.

    Mirrors :func:`_to_snapshot` minus ``matched_products`` (catalog-side data,
    re-fetchable from ``products``) and minus ``messages`` (full LLM trace,
    bloats fast and isn't needed for replay). ``thread_id`` is stashed so a row
    can be back-mapped to its LangGraph checkpoint without a schema migration.

    Pydantic models are dumped in JSON-mode so Decimals/dates/UUIDs round-trip
    as JSON-native scalars rather than Python repr strings.
    """
    quote = values.get("quote")
    matches: list[MatchResult] = values.get("matches", [])
    human_decision: HumanDecision | None = values.get("human_decision")
    return {
        "thread_id": thread_id,
        "fixture_filename": values.get("fixture_filename"),
        "quote": quote.model_dump(mode="json") if quote else None,
        "matches": [m.model_dump(mode="json") for m in matches],
        "human_decision": (
            human_decision.model_dump(mode="json") if human_decision else None
        ),
    }


def _to_snapshot(thread_id: str, values: dict, next_nodes: tuple[str, ...]) -> RunSnapshot:
    """Serialize the relevant parts of state for the API response."""
    quote = values.get("quote")
    matches: list[MatchResult] = values.get("matches", [])
    matched_skus = sorted({m.matched_sku for m in matches if m.matched_sku})
    matched_products: dict[str, Product] = {}
    if matched_skus:
        with connect() as conn:
            matched_products = get_products_by_skus(conn, matched_skus)
    return RunSnapshot(
        thread_id=thread_id,
        status=_status_for(next_nodes),
        fixture_filename=values.get("fixture_filename"),
        quote=quote.model_dump(mode="json") if quote else None,
        matches=matches,
        matched_products=matched_products,
        human_decision=values.get("human_decision"),
    )


def _validate_decisions(decisions: list[LineDecision], matches: list[MatchResult]) -> None:
    """Ensure one decision per match, indices align. 422 on mismatch."""
    if len(decisions) != len(matches):
        raise HTTPException(
            status_code=422,
            detail=(
                f"line_decisions length {len(decisions)} does not match "
                f"matches length {len(matches)}"
            ),
        )
    expected = {m.line_index for m in matches}
    actual = {d.line_index for d in decisions}
    if expected != actual:
        raise HTTPException(
            status_code=422,
            detail=f"line_index sets differ — expected {sorted(expected)}, got {sorted(actual)}",
        )


def _validate_override_skus(decisions: list[LineDecision]) -> None:
    """422 if any ``override_sku`` does not resolve to a catalog product.

    Fail-fast at the boundary: a typo'd SKU should be rejected before the
    graph resumes, not after ``approval_node`` re-runs flags and trips on a
    missing product row.
    """
    skus = [d.override_sku for d in decisions if d.action == LineAction.OVERRIDE]
    if not skus:
        return
    with connect() as conn:
        rows = conn.execute(
            "SELECT sku FROM products WHERE sku = ANY(%s)", (skus,)
        ).fetchall()
    found = {r["sku"] for r in rows}
    missing = sorted(s for s in skus if s not in found)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"override_sku not found in catalog: {missing}",
        )


# --- endpoints --------------------------------------------------------------


@app.get("/fixtures")
def list_fixtures() -> list[str]:
    """List demo-ready fixtures — source files that have a paired .expected.json.

    Fixtures without a golden are kept in the corpus intentionally (e.g. shapes
    the v1 schema can't yet represent) but are not shown to the demo dropdown,
    since the agent will fail extraction against them.
    """
    sources = [p for p in QUOTES_DIR.iterdir() if p.suffix in SOURCE_EXTS]
    visible: list[str] = []
    for src in sources:
        stem = src.name.removesuffix(src.suffix)
        if stem.endswith(".notes"):
            continue
        if (QUOTES_DIR / f"{stem}.expected.json").is_file():
            visible.append(src.name)
    return sorted(visible)


@app.get("/fixtures/{filename}", response_class=PlainTextResponse)
def get_fixture_source(filename: Annotated[str, PathParam()]) -> str:
    """Return fixture text so the UI can show it next to the extraction.

    Delegates to the agent's ``read_file`` so docx fixtures get rendered to plain
    text the same way the extraction pipeline reads them.
    """
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid fixture filename")
    if (QUOTES_DIR / filename).suffix not in SOURCE_EXTS:
        raise HTTPException(status_code=404, detail=f"fixture not found: {filename}")
    try:
        return read_file(filename)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/products/search", response_model=list[Product])
def products_search(q: str = "", limit: int = 20) -> list[Product]:
    """Typeahead search across SKU and description for the override picker.

    Wraps in a try/except so a backend failure surfaces as a 500 with the
    exception message in ``detail`` — beats grepping logs when production
    behaves differently from local.
    """
    capped = max(1, min(limit, 50))
    try:
        with connect() as conn:
            return search_products(conn, q.strip(), limit=capped)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {e}",
        ) from e


@app.post("/runs", response_model=RunSnapshot)
def start_run(req: StartRunRequest) -> RunSnapshot:
    """Invoke the graph against ``fixture_filename`` until it hits ``approval``."""
    if not (QUOTES_DIR / req.fixture_filename).is_file():
        raise HTTPException(status_code=404, detail=f"fixture not found: {req.fixture_filename}")
    thread_id = req.thread_id or f"run-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    initial: QuoteWorkflowState = {
        "fixture_filename": req.fixture_filename,
        "messages": [
            {"role": "user", "content": f"Extract the quote in {req.fixture_filename} as JSON."}
        ],
    }
    with connect() as conn:
        run_id = insert_agent_run(
            conn,
            workflow="quote_reconciliation",
            fixture_filename=req.fixture_filename,
            thread_id=thread_id,
            status="running",
        )
    try:
        with PostgresSaver.from_conn_string(_database_url()) as cp:
            g = build_graph(cp)
            g.invoke(initial, config=config)
            snapshot = g.get_state(config)
    except Exception:
        _mark_run_failed(run_id)
        raise
    _record_run_state(run_id, thread_id, snapshot.values, _status_for(snapshot.next))
    return _to_snapshot(thread_id, snapshot.values, snapshot.next)


@app.get("/runs/{thread_id}", response_model=RunSnapshot)
def get_run(thread_id: Annotated[str, PathParam()]) -> RunSnapshot:
    """Fetch the latest checkpoint snapshot for ``thread_id``."""
    config = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(_database_url()) as cp:
        g = build_graph(cp)
        snapshot = g.get_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"no run found for thread_id={thread_id}")
    return _to_snapshot(thread_id, snapshot.values, snapshot.next)


@app.post("/runs/{thread_id}/resume", response_model=RunSnapshot)
def resume_run(
    thread_id: Annotated[str, PathParam()],
    req: ResumeRequest,
) -> RunSnapshot:
    """Inject ``HumanDecision`` and run the graph to END.

    409 if the run isn't paused at ``approval``. 422 if the decision payload's
    cardinality or indices don't match ``state['matches']`` — these are request
    validation failures, not graph failures, so they leave the agent_runs row
    untouched (status stays ``pending_approval``).
    """
    config = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(_database_url()) as cp:
        g = build_graph(cp)
        snapshot = g.get_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail=f"no run found for thread_id={thread_id}")
        if snapshot.next != ("approval",):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"run is not awaiting approval (next nodes: {snapshot.next}); "
                    "cannot resume"
                ),
            )
        _validate_decisions(req.line_decisions, snapshot.values.get("matches", []))
        _validate_override_skus(req.line_decisions)
        with connect() as conn:
            run_id = get_agent_run_id_by_thread_id(conn, thread_id)
        decision = HumanDecision(
            reviewer=req.reviewer,
            decided_at=datetime.now(UTC),
            line_decisions=req.line_decisions,
            overall_notes=req.overall_notes,
        )
        g.update_state(config, {"human_decision": decision})
        try:
            g.invoke(None, config=config)
            final = g.get_state(config)
        except Exception:
            _mark_run_failed(run_id)
            raise
    _record_run_state(run_id, thread_id, final.values, "completed")
    return _to_snapshot(thread_id, final.values, final.next)
