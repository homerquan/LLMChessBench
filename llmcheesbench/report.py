from __future__ import annotations

import json
import math
from pathlib import Path


def generate_report(benchmarks_dir: str | Path = "benchmarks") -> None:
    benchmark_path = Path(benchmarks_dir)
    if not benchmark_path.exists():
        print("No benchmarks folder found.")
        return

    reports = []
    for benchmark_file in sorted(benchmark_path.glob("*.json")):
        if benchmark_file.name.endswith(".live.json"):
            continue
        try:
            data = json.loads(benchmark_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("benchmark") not in {"LLMCheesBench", "ChessBench"}:
            continue

        summary = data["summary"]
        reports.append(
            {
                "model": data.get("model_name") or data.get("model") or benchmark_file.stem,
                "positions": int(summary.get("positions", 0)),
                "legal": int(summary.get("legal_moves", 0)),
                "forfeits": int(summary.get("forfeits", 0)),
                "matches": int(summary.get("exact_engine_matches", 0)),
                "score": float(summary.get("normalized_score", 0.0)),
                "cbi": llmcheesbench_index(summary),
            }
        )

    if not reports:
        print("No LLMCheesBench result files found.")
        return

    reports.sort(key=lambda item: (item["cbi"], item["score"]), reverse=True)
    print("| Model | Positions | Legal | Forfeits | Engine Matches | Score | CBI |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for report in reports:
        print(
            f"| {report['model']} "
            f"| {report['positions']} "
            f"| {report['legal']} "
            f"| {report['forfeits']} "
            f"| {report['matches']} "
            f"| {report['score']:.2f} "
            f"| {report['cbi']:.1f} |"
        )


def llmcheesbench_index(summary: dict) -> float:
    categories = summary.get("by_category")
    if not isinstance(categories, dict) or not categories:
        return float(summary.get("normalized_score", 0.0)) * 10.0

    scores = [max(0.01, float(stats.get("normalized_score", 0.0)) / 100.0) for stats in categories.values()]
    arithmetic = sum(scores) / len(scores)
    geometric = math.exp(sum(math.log(score) for score in scores) / len(scores))
    legality = float(summary.get("legal_moves", 0)) / max(1.0, float(summary.get("positions", 0)))
    match_rate = float(summary.get("exact_engine_matches", 0)) / max(1.0, float(summary.get("positions", 0)))
    return round(1000.0 * (0.60 * arithmetic + 0.25 * geometric + 0.10 * legality + 0.05 * match_rate), 1)
