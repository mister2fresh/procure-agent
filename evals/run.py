"""Run the agent against the synthetic-quote eval corpus and report drift.

Iterates ``data/synthetic_quotes/*.expected.json`` as the anchor set (so the
held-out demo in ``data/prompt_examples/`` is excluded by directory), runs the
agent, compares with ``evals.comparator``, prints a per-fixture summary plus a
per-field-name failure breakdown, and writes a JSON artifact to
``evals/runs/<timestamp>.json`` for diff-across-runs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.comparator import FieldComparison, FixtureResult, compare
from procure_agent.agent import _extract_json_block, run
from procure_agent.schemas import Quote

ROOT = Path(__file__).resolve().parents[1]
QUOTES_DIR = ROOT / "data" / "synthetic_quotes"
RUNS_DIR = ROOT / "evals" / "runs"

SOURCE_EXTS: tuple[str, ...] = (".txt", ".csv", ".md", ".docx", ".eml")


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


def _per_field_breakdown(results: list[FixtureResult]) -> dict[str, Counter]:
    by_path: dict[str, Counter] = {}
    for r in results:
        for fc in _flatten(r):
            by_path.setdefault(fc.path, Counter())[fc.bucket] += 1
    return by_path


def _run_one(stem: str, source: Path, golden_path: Path) -> FixtureResult:
    resp = run(f"Extract the quote in {source.name} as JSON.")
    predicted = json.loads(_extract_json_block(resp))
    Quote.model_validate(predicted)
    golden = json.loads(golden_path.read_text())
    return compare(predicted, golden, stem)


def _print_fixture(r: FixtureResult) -> None:
    c = _bucket_counts(_flatten(r))
    matched = len(r.matched_lines)
    p = matched / r.line_count_predicted if r.line_count_predicted else 1.0
    rec = matched / r.line_count_golden if r.line_count_golden else 1.0
    total = sum(c.values())
    print(
        f"  {r.fixture:50} field={c['match']}/{total} "
        f"fmt={c.get('format_drift', 0)} mis={c.get('value_mismatch', 0)} "
        f"lines P={p:.2f} R={rec:.2f}"
    )


def _print_total(results: list[FixtureResult]) -> None:
    total = Counter()
    for r in results:
        total.update(_bucket_counts(_flatten(r)))
    n = sum(total.values())
    if not n:
        return
    print(
        f"\n  TOTAL field-match={total['match']}/{n} ({total['match'] / n:.1%})  "
        f"format_drift={total.get('format_drift', 0)}  "
        f"value_mismatch={total.get('value_mismatch', 0)}"
    )


def _print_breakdown(results: list[FixtureResult]) -> None:
    print("\n=== per-field breakdown (failures only) ===")
    for path, counts in sorted(_per_field_breakdown(results).items()):
        if counts.get("value_mismatch", 0) or counts.get("format_drift", 0):
            print(
                f"  {path:42} match={counts['match']}  "
                f"fmt={counts.get('format_drift', 0)}  "
                f"mis={counts.get('value_mismatch', 0)}"
            )


def _fc_to_dict(fc: FieldComparison) -> dict[str, Any]:
    return {"path": fc.path, "bucket": fc.bucket, "predicted": fc.predicted, "golden": fc.golden}


def _result_to_dict(r: FixtureResult) -> dict[str, Any]:
    return {
        "fixture": r.fixture,
        "quote_fields": [_fc_to_dict(fc) for fc in r.quote_fields],
        "matched_lines": [[_fc_to_dict(fc) for fc in line] for line in r.matched_lines],
        "only_predicted": r.only_predicted,
        "only_golden": r.only_golden,
        "line_count_predicted": r.line_count_predicted,
        "line_count_golden": r.line_count_golden,
    }


def _write_artifact(results: list[FixtureResult]) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact = RUNS_DIR / f"{timestamp}.json"
    artifact.write_text(
        json.dumps([_result_to_dict(r) for r in results], indent=2, default=str)
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
    results: list[FixtureResult] = []
    for golden_path in _select_goldens(sys.argv[1:]):
        stem = golden_path.stem.removesuffix(".expected")
        source = _source_for(stem)
        if source is None:
            print(f"  SKIP {stem} (no source)")
            continue
        try:
            r = _run_one(stem, source, golden_path)
        except Exception as exc:  # noqa: BLE001 — CLI boundary; report and continue
            print(f"  FAIL {stem}: {type(exc).__name__}: {exc}")
            continue
        results.append(r)
        _print_fixture(r)

    _print_total(results)
    _print_breakdown(results)
    artifact = _write_artifact(results)
    print(f"\nartifact: {artifact.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
