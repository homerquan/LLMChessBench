from __future__ import annotations

import argparse
from pathlib import Path

from llmcheesbench.benchmark import BenchmarkLLMCallError, run_benchmark
from llmcheesbench.engine import EngineConfig, UCIEngine, resolve_engine_path
from llmcheesbench.positions import DEFAULT_POSITIONS, get_positions
from llmcheesbench.progress import BenchmarkProgress
from llmcheesbench.report import generate_report
from llmcheesbench.web_report import default_web_path, serve_web_report, start_web_report_server, write_web_report


def run_cli(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list-positions":
        return list_positions()
    if args.command == "engine-best":
        return engine_best(args)
    if args.command == "benchmark":
        return benchmark_command(args)
    if args.command == "report":
        generate_report()
        return 0
    if args.command == "show-web":
        return show_web_command(args)
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run chess LLM benchmarks against a local UCI engine.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-positions", help="Show available chess benchmark positions.")

    engine_parser = subparsers.add_parser("engine-best", help="Print the engine's best moves for the position suite.")
    add_engine_args(engine_parser)
    engine_parser.add_argument("--positions", help="Comma-separated position ids. Default: all positions.")

    benchmark_parser = subparsers.add_parser("benchmark", help="Benchmark an LLM on chess positions.")
    model_group = benchmark_parser.add_mutually_exclusive_group(required=True)
    model_group.add_argument("--model", help="Model config name in the models folder.")
    model_group.add_argument("--model-file", help="Path to a custom model JSON config file.")
    benchmark_parser.add_argument("--positions", help="Comma-separated position ids. Default: all positions.")
    benchmark_parser.add_argument("--show-web", action="store_true", help="Write an interactive HTML replay next to the JSON result.")
    benchmark_parser.add_argument("--web-port", type=int, default=0, help="Port for --show-web. Default: choose an open port.")
    benchmark_parser.add_argument("-v", "--verbose", action="store_true", help="Print boards and moves.")
    benchmark_parser.add_argument("--debug-http", action="store_true", help="Print provider HTTP error detail.")
    add_engine_args(benchmark_parser)

    subparsers.add_parser("report", help="Report saved LLMCheesBench results.")

    show_parser = subparsers.add_parser("show-web", help="Create an interactive HTML replay from a saved benchmark JSON.")
    show_parser.add_argument("benchmark", nargs="?", default="benchmarks/ollama-nemotron-3-super.json", help="Benchmark JSON path.")
    show_parser.add_argument("--output", help="HTML output path. Default: same path with .html suffix.")
    show_parser.add_argument("--port", type=int, default=0, help="Port for the local web server. Default: choose an open port.")
    return parser


def add_engine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", help="Path to a UCI engine. Defaults to LLMCHEESBENCH_ENGINE or stockfish in PATH.")
    parser.add_argument("--movetime", type=int, default=1000, help="Engine analysis time per position in milliseconds.")
    parser.add_argument("--depth", type=int, default=None, help="Optional fixed engine depth instead of movetime.")
    parser.add_argument("--threads", type=int, default=1, help="Engine CPU threads.")
    parser.add_argument("--hash", type=int, default=256, help="Engine hash size in MB.")
    parser.add_argument("--multipv", type=int, default=4, help="Number of engine candidate lines to score directly.")


def list_positions() -> int:
    print("Available positions:")
    for position in DEFAULT_POSITIONS:
        print(f"- {position.position_id}: {position.name} ({position.category}, weight={position.weight})")
    return 0


def engine_best(args) -> int:
    position_ids = [item.strip() for item in args.positions.split(",") if item.strip()] if args.positions else None
    positions = get_positions(position_ids)
    try:
        config = EngineConfig(
            path=resolve_engine_path(args.engine),
            movetime_ms=args.movetime,
            depth=args.depth,
            threads=args.threads,
            hash_mb=args.hash,
            multipv=args.multipv,
        )
    except FileNotFoundError as error:
        print(error)
        return 1
    with UCIEngine(config) as engine:
        for position in positions:
            import chess

            board = chess.Board(position.fen)
            lines = engine.analyze(board)
            best = lines[0] if lines else None
            if best:
                print(f"{position.position_id}: {best.move.uci()} {board.san(best.move)} ({best.score_cp} cp)")
            else:
                print(f"{position.position_id}: no engine move")
    return 0


def benchmark_command(args) -> int:
    position_count = len(get_positions([item.strip() for item in args.positions.split(",") if item.strip()] if args.positions else None))
    progress = BenchmarkProgress(position_count)
    web_port = args.web_port or 0
    web_server = None

    def start_message(runner):
        nonlocal web_server
        if args.show_web:
            output_path = Path("benchmarks") / f"{runner.model_config.config_name}.json"
            web_path = default_web_path(output_path)
            web_server = start_web_report_server(web_path, web_port)
            print(f"Web replay available now: {web_server.url}")
            print("Open it while the benchmark runs; unfinished positions show as waiting.")
        print(f"LLM reasoning process log in: {runner.reasoning_log_path}")

    try:
        output_path, report = run_benchmark(
            args,
            progress_callback=lambda completed, total: progress.update(completed),
            start_callback=start_message,
        )
    except BenchmarkLLMCallError as error:
        progress.newline()
        print(error)
        print("Benchmark was not saved.")
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        progress.newline()
        print(error)
        return 1
    progress.finish()
    summary = report["summary"]
    print(f"Saved benchmark to {output_path}")
    print(
        f"Score: {summary['normalized_score']:.2f}, "
        f"legal moves: {summary['legal_moves']}/{summary['positions']}, "
        f"engine matches: {summary['exact_engine_matches']}, "
        f"forfeits: {summary['forfeits']}"
    )
    if args.show_web:
        web_path = default_web_path(output_path)
        print(f"Saved web replay to {web_path}")
        if web_server:
            print(f"Web replay updated at: {web_server.url}")
            print("Press Ctrl-C to stop the web replay server.")
            web_server.wait_until_interrupted()
        else:
            serve_web_report(web_path, web_port)
    return 0


def show_web_command(args) -> int:
    import json

    benchmark_path = Path(args.benchmark)
    if not benchmark_path.exists():
        print(f"Benchmark file not found: {benchmark_path}")
        return 1
    report = json.loads(benchmark_path.read_text(encoding="utf-8"))
    output_path = Path(args.output) if args.output else default_web_path(benchmark_path)
    write_web_report(report, output_path)
    print(f"Saved web replay to {output_path}")
    serve_web_report(output_path, args.port)
    return 0
