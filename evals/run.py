"""Run the LangGraph workflow against the synthetic-quote eval corpus and report drift.

Iterates ``data/synthetic_quotes/*.expected.json`` as the anchor set (the held-out
demo in ``data/prompt_examples/`` is excluded by directory). For each fixture,
invokes the compiled graph (``extract → tools* → match → flag``) — execution halts
at ``interrupt_before=["approval"]`` — pulls the raw fenced JSON from the final
assistant message for a precision-preserving compare via :mod:`evals.comparator`,
and collects the populated ``state["matches"]`` for cascade/flag observability.

Output: per-fixture summary line, per-field-name failure breakdown, per-cascade-tier
and per-flag-kind counts, and a JSON artifact at ``evals/runs/<timestamp>.json``
that includes the comparator output plus the serialized match results.

Requires postgres (``match_node`` and ``flag_node`` both connect via
``procure_agent.db.connect``). Run ``docker compose up -d`` and apply migrations
before invoking.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.comparator import FieldComparison, FixtureResult, compare
from procure_agent.agent import JSON_BLOCK
from procure_agent.graph import graph
from procure_agent.state import MatchResult, QuoteWorkflowState

ROOT = Path(__file__).resolve().parents[1]
QUOTES_DIR = ROOT / "data" / "synthetic_quotes"
RUNS_DIR = ROOT / "evals" / "runs"

SOURCE_EXTS: tuple[str, ...] = (".txt", ".csv", ".md", ".docx", ".eml")


@dataclass(frozen=True, slots=True)
class EvalRow:
    """One fixture's full eval output: comparator buckets + match observability."""

    fixture: str
    result: FixtureResult
    matches: list[MatchResult]


def _source_for(stem: str) -> Path | None:
    for ext in SOURCE_EXTS:
        candidate = QUOTES_DIR / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _flatten(result: FixtureResult) -> list[FieldComparison]:
    flat = list(result.quote_fields)
    for line in result.matched_lines:
        flat.extend(line)
    return flat


def _bucket_counts(fields: Iterable[FieldComparison]) -> Counter:
    return Counter(f.bucket for f in fields)


def _per_field_breakdown(rows: list[EvalRow]) -> dict[str, Counter]:
    by_path: dict[str, Counter] = {}
    for row in rows:
        for fc in _flatten(row.result):
            by_path.setdefault(fc.path, Counter())[fc.bucket] += 1
    return by_path


def _extract_predicted_json(messages: list[dict]) -> str:
    """Pull the fenced JSON block from the final assistant message in graph state.

    Mirrors :func:`procure_agent.agent.extract_json_block` but reads from the
    state-stored content blocks (preserved verbatim by ``extract_node``) so the
    comparator sees source precision exactly as the model emitted it.
    """
    content = messages[-1]["content"]
    text = "".join(block.text for block in content if block.type == "text")
    match = JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no fenced json block in final assistant message")
    return match.group(1)


def _run_one(stem: str, source: Path, golden_path: Path) -> EvalRow:
    initial_state: QuoteWorkflowState = {
        "fixture_filename": source.name,
        "messages": [
            {"role": "user", "content": f"Extract the quote in {source.name} as JSON."}
        ],
    }
    config = {"configurable": {"thread_id": f"eval-{stem}"}}
    final_state = graph.invoke(initial_state, config=config)
    predicted = json.loads(_extract_predicted_json(final_state["messages"]))
    golden = json.loads(golden_path.read_text())
    result = compare(predicted, golden, stem)
    matches: list[MatchResult] = final_state.get("matches", [])
    return EvalRow(fixture=stem, result=result, matches=matches)


def _print_fixture(row: EvalRow) -> None:
    c = _bucket_counts(_flatten(row.result))
    matched = len(row.result.matched_lines)
    p = matched / row.result.line_count_predicted if row.result.line_count_predicted else 1.0
    rec = matched / row.result.line_count_golden if row.result.line_count_golden else 1.0
    total = sum(c.values())
    print(
        f"  {row.fixture:50} field={c['match']}/{total} "
        f"fmt={c.get('format_drift', 0)} mis={c.get('value_mismatch', 0)} "
        f"lines P={p:.2f} R={rec:.2f}"
    )
    if row.matches:
        method_counts = Counter(m.match_method.value for m in row.matches)
        flag_counts = Counter(f.kind.value for m in row.matches for f in m.flags)
        method_summary = " ".join(f"{k}={v}" for k, v in sorted(method_counts.items()))
        flag_summary = (
            " ".join(f"{k}={v}" for k, v in sorted(flag_counts.items()))
            if flag_counts
            else "none"
        )
        print(f"    match: {method_summary}")
        print(f"    flags: {flag_summary}")


def _print_total(rows: list[EvalRow]) -> None:
    total = Counter()
    for row in rows:
        total.update(_bucket_counts(_flatten(row.result)))
    n = sum(total.values())
    if not n:
        return
    print(
        f"\n  TOTAL field-match={total['match']}/{n} ({total['match'] / n:.1%})  "
        f"format_drift={total.get('format_drift', 0)}  "
        f"value_mismatch={total.get('value_mismatch', 0)}"
    )

    method_total: Counter = Counter()
    flag_total: Counter = Counter()
    for row in rows:
        method_total.update(m.match_method.value for m in row.matches)
        flag_total.update(f.kind.value for m in row.matches for f in m.flags)
    if method_total:
        line_total = sum(method_total.values())
        method_summary = " ".join(f"{k}={v}" for k, v in sorted(method_total.items()))
        print(f"  TOTAL lines={line_total}  match-tier: {method_summary}")
    if flag_total:
        flag_summary = " ".join(f"{k}={v}" for k, v in sorted(flag_total.items()))
        print(f"  TOTAL flags raised: {flag_summary}")


def _print_breakdown(rows: list[EvalRow]) -> None:
    print("\n=== per-field breakdown (failures only) ===")
    for path, counts in sorted(_per_field_breakdown(rows).items()):
        if counts.get("value_mismatch", 0) or counts.get("format_drift", 0):
            print(
                f"  {path:42} match={counts['match']}  "
                f"fmt={counts.get('format_drift', 0)}  "
                f"mis={counts.get('value_mismatch', 0)}"
            )


def _fc_to_dict(fc: FieldComparison) -> dict[str, Any]:
    return {"path": fc.path, "bucket": fc.bucket, "predicted": fc.predicted, "golden": fc.golden}


def _row_to_dict(row: EvalRow) -> dict[str, Any]:
    return {
        "fixture": row.fixture,
        "quote_fields": [_fc_to_dict(fc) for fc in row.result.quote_fields],
        "matched_lines": [
            [_fc_to_dict(fc) for fc in line] for line in row.result.matched_lines
        ],
        "only_predicted": row.result.only_predicted,
        "only_golden": row.result.only_golden,
        "line_count_predicted": row.result.line_count_predicted,
        "line_count_golden": row.result.line_count_golden,
        "matches": [m.model_dump(mode="json") for m in row.matches],
    }


def _write_artifact(rows: list[EvalRow]) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact = RUNS_DIR / f"{timestamp}.json"
    artifact.write_text(
        json.dumps([_row_to_dict(row) for row in rows], indent=2, default=str)
    )
    return artifact


def _select_goldens(filters: list[str]) -> list[Path]:
    """Return goldens to run. Empty filters = full corpus; else stems are matched as a prefix."""
    all_goldens = sorted(QUOTES_DIR.glob("*.expected.json"))
    if not filters:
        return all_goldens
    return [g for g in all_goldens if any(g.stem.startswith(f) for f in filters)]


def main() -> None:
    print("=== eval summary ===")
    rows: list[EvalRow] = []
    for golden_path in _select_goldens(sys.argv[1:]):
        stem = golden_path.stem.removesuffix(".expected")
        source = _source_for(stem)
        if source is None:
            print(f"  SKIP {stem} (no source)")
            continue
        try:
            row = _run_one(stem, source, golden_path)
        except Exception as exc:  # noqa: BLE001 — CLI boundary; report and continue
            print(f"  FAIL {stem}: {type(exc).__name__}: {exc}")
            continue
        rows.append(row)
        _print_fixture(row)

    _print_total(rows)
    _print_breakdown(rows)
    artifact = _write_artifact(rows)
    print(f"\nartifact: {artifact.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
