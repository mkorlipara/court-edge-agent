"""Run slate analysis from the command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.agents.slate_agent import run_slate_analysis


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run full NBA slate edge analysis")
    parser.add_argument("--date", dest="game_date", default=None, help="ISO date (YYYY-MM-DD)")
    parser.add_argument(
        "--markets",
        nargs="+",
        default=None,
        help="Markets to analyze (points rebounds assists threes_made)",
    )
    parser.add_argument("--min-edge", type=float, default=1.5, help="Minimum absolute edge filter")
    parser.add_argument("--top-n", type=int, default=10, help="Number of ranked picks to return")
    parser.add_argument("--output", default=None, help="Optional path to save full JSON result")
    return parser


def _print_table(result: dict) -> None:
    if result.get("error"):
        print(f"Error: {result['error']} (date={result.get('date')})")
        return

    picks = result.get("top_picks", [])
    print(
        f"Date: {result.get('date')} | Games: {result.get('games_on_slate')} | "
        f"Candidates: {result.get('candidates_evaluated')} | "
        f"Edges >= threshold: {result.get('edges_above_threshold')}"
    )
    if result.get("note"):
        print(f"Note: {result['note']}")
    if not picks:
        print("No qualifying picks found.")
        return

    print("\nRank | Player              | Team | Opp | Mkt         | Line | HGB   | LLM   | Edge")
    print("-" * 84)
    for pick in picks:
        print(
            f"{pick['rank']:>4} | "
            f"{pick['player_name'][:18]:<18} | "
            f"{pick['team']:<4} | "
            f"{pick['opponent']:<3} | "
            f"{pick['market']:<11} | "
            f"{pick['prop_line']:>4.1f} | "
            f"{pick['hgb_projection']:>5.1f} | "
            f"{pick['llm_projection']:>5.1f} | "
            f"{pick['edge']:>5.1f}"
        )


async def _run(args: argparse.Namespace) -> dict:
    return await run_slate_analysis(
        game_date=args.game_date,
        markets=args.markets,
        min_edge=args.min_edge,
        top_n=args.top_n,
    )


def main() -> None:
    args = _build_parser().parse_args()
    result = asyncio.run(_run(args))
    _print_table(result)

    if args.output:
        with Path(args.output).open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved full result to {args.output}")


if __name__ == "__main__":
    main()
