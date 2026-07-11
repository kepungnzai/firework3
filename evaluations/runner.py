"""Evaluation runner CLI.

Loads the JSON cases under ``evaluations/datasets``, runs each through the agent
orchestrator, scores it, prints a summary table, and writes a JSON report under
``evaluations/reports``.

Examples (from the repo root, using the workspace venv):

    # Offline baseline — deterministic planner, should score 100%.
    .venv/Scripts/python.exe -m evaluations.runner

    # Evaluate the live Foundry model (calendar/email stay deterministic):
    #   set FAKE_PROVIDERS handled by --use-llm; provide the endpoint first.
    .venv/Scripts/python.exe -m evaluations.runner --use-llm

    # Run a single case and print full per-check detail.
    .venv/Scripts/python.exe -m evaluations.runner --case appointment_happy_path -v
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from apptshared.config import get_settings

from evaluations.harness import run_case, set_mode
from evaluations.metrics import CaseScore, evaluate

DATASET_DIR = Path(__file__).parent / "datasets"
REPORT_DIR = Path(__file__).parent / "reports"


def _load_specs(dataset_dir: Path, only: str | None) -> list[dict]:
    specs = []
    for path in sorted(dataset_dir.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec.setdefault("name", path.stem)
        if only and spec["name"] != only:
            continue
        specs.append(spec)
    return specs


def _run_all(specs: list[dict]) -> list[CaseScore]:
    scores = []
    for spec in specs:
        run = asyncio.run(run_case(spec))
        scores.append(evaluate(spec, run))
    return scores


def _print_summary(scores: list[CaseScore], verbose: bool) -> None:
    name_w = max((len(s.name) for s in scores), default=4)
    print(f"\n{'CASE':<{name_w}}  RESULT  CHECKS")
    print("-" * (name_w + 40))
    for s in scores:
        badge = "PASS" if s.passed else "FAIL"
        failed = [k for k, ok in s.checks.items() if not ok]
        summary = "ok" if not failed else "failed: " + ", ".join(failed)
        acc = s.metrics.get("trace_step_accuracy")
        acc_str = f"  (step_acc={acc})" if acc is not None else ""
        print(f"{s.name:<{name_w}}  {badge:<6}  {summary}{acc_str}")
        if verbose and (failed or True):
            for key in ("status", "reason", "tools", "recipients", "message_missing"):
                if key in s.details:
                    print(f"    {key}: {s.details[key]}")

    passed = sum(1 for s in scores if s.passed)
    total = len(scores)
    rate = (passed / total * 100) if total else 0.0
    print("-" * (name_w + 40))
    print(f"PASS RATE: {passed}/{total} ({rate:.1f}%)\n")


def _write_report(scores: list[CaseScore], mode: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = REPORT_DIR / f"eval-{mode}-{stamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total": len(scores),
        "passed": sum(1 for s in scores if s.passed),
        "cases": [
            {
                "name": s.name,
                "passed": s.passed,
                "checks": s.checks,
                "metrics": s.metrics,
                "details": s.details,
            }
            for s in scores
        ],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run appointment-agent LLM evaluations")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Evaluate the live Foundry planner/composer (FAKE_PROVIDERS=false).",
    )
    parser.add_argument("--case", help="Run only the named case.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_DIR,
        help="Directory of *.json evaluation cases.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-check detail.")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 (do not fail CI on a failing case).",
    )
    args = parser.parse_args()

    set_mode(args.use_llm)
    mode = "llm" if args.use_llm else "scripted"
    if args.use_llm and not get_settings().azure_ai_project_endpoint:
        print(
            "WARNING: --use-llm set but AZURE_AI_PROJECT_ENDPOINT is empty; the "
            "planner will fall back to the canonical sequence."
        )

    specs = _load_specs(args.dataset, args.case)
    if not specs:
        print(f"No evaluation cases found in {args.dataset}")
        sys.exit(2)

    scores = _run_all(specs)
    _print_summary(scores, args.verbose)
    report = _write_report(scores, mode)
    print(f"Report written to {report}")

    if not args.no_fail and any(not s.passed for s in scores):
        sys.exit(1)


if __name__ == "__main__":
    main()
