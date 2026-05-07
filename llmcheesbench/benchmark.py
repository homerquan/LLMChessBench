from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import chess

from llmcheesbench.engine import EngineConfig, UCIEngine, centipawn_loss, move_quality_score, resolve_engine_path
from llmcheesbench.llm_player import LLMMoveError, LLMPlayer, LLMRequestError
from llmcheesbench.model_config import load_model_config
from llmcheesbench.positions import Position, get_positions
from llmcheesbench.web_report import default_live_data_path, default_web_path, write_live_data, write_web_report


BENCHMARK_DIR = Path.cwd() / "benchmarks"
REASONING_LOG_DIR = Path("/tmp/llmcheesbench")


@dataclass
class BenchmarkSummary:
    positions: int = 0
    legal_moves: int = 0
    forfeits: int = 0
    exact_engine_matches: int = 0
    weighted_score: float = 0.0
    total_weight: float = 0.0
    by_category: dict[str, dict[str, float | int]] = field(default_factory=dict)


class BenchmarkLLMCallError(RuntimeError):
    pass


class BenchmarkRunner:
    def __init__(
        self,
        model_config,
        positions: list[Position] | None = None,
        engine_config: EngineConfig | None = None,
        llm_player: LLMPlayer | None = None,
        progress_callback=None,
        live_callback=None,
        verbose: bool = False,
        debug_http: bool = False,
        run_id: str | None = None,
        stream=None,
    ):
        self.model_config = model_config
        self.positions = positions or get_positions()
        self.run_id = run_id or uuid4().hex
        self.reasoning_log_path = REASONING_LOG_DIR / f"{self.run_id}.log"
        self.engine_config = engine_config or EngineConfig(path=resolve_engine_path(None))
        self.llm_player = llm_player or LLMPlayer(
            model_config,
            debug_http=debug_http,
            reasoning_log_path=self.reasoning_log_path,
        )
        self.progress_callback = progress_callback
        self.live_callback = live_callback
        self.verbose = verbose
        self.stream = stream or sys.stdout

    @property
    def total_positions(self) -> int:
        return len(self.positions)

    def run(self) -> dict:
        results = []
        summary = BenchmarkSummary()
        completed = 0
        self._report_progress(completed)
        self._report_live(results, summary, "running")

        with UCIEngine(self.engine_config) as engine:
            for position in self.positions:
                result = self._run_position(position, engine)
                results.append(result)
                update_summary(summary, result)
                completed += 1
                self._report_progress(completed)
                self._report_live(results, summary, "running")

        return self._build_report(results, summary, "complete")

    def _build_report(self, results: list[dict], summary: BenchmarkSummary, status: str) -> dict:
        return {
            "benchmark": "LLMCheesBench",
            "status": status,
            "model": self.model_config.model_id,
            "model_name": self.model_config.display_name,
            "provider": self.model_config.provider_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "reasoning_log": str(self.reasoning_log_path),
            "engine": {
                "path": self.engine_config.path,
                "movetime_ms": self.engine_config.movetime_ms,
                "depth": self.engine_config.depth,
                "threads": self.engine_config.threads,
                "hash_mb": self.engine_config.hash_mb,
                "multipv": self.engine_config.multipv,
            },
            "positions_requested": [position.position_id for position in self.positions],
            "position_manifest": [position_manifest(position) for position in self.positions],
            "completed_positions": len(results),
            "total_positions": len(self.positions),
            "summary": finalize_summary(summary),
            "positions": results,
        }

    def _report_live(self, results: list[dict], summary: BenchmarkSummary, status: str) -> None:
        if self.live_callback:
            self.live_callback(self._build_report(results, summary, status))

    def _run_position(self, position: Position, engine: UCIEngine) -> dict:
        board = chess.Board(position.fen)
        engine_lines = engine.analyze(board)
        fallback = engine_lines[0].move.uci() if engine_lines else next(iter(board.legal_moves)).uci()
        self._log(f"{position.position_id}: {position.name}")
        self._log(board.unicode(empty_square="."))
        try:
            move, response_text = self.llm_player.choose_move(position.name, board, fallback)
        except LLMRequestError as error:
            return forfeit_result(position, board, engine_lines, str(error), "llm_request_error")
        except LLMMoveError as error:
            return forfeit_result(position, board, engine_lines, str(error), "llm_forfeit")

        chosen_line = engine.analyze_move(board, move)
        loss = centipawn_loss(engine_lines, chosen_line)
        quality = move_quality_score(loss)
        weighted = quality * position.weight
        best_move = engine_lines[0].move if engine_lines else None
        return {
            "position_id": position.position_id,
            "position_name": position.name,
            "category": position.category,
            "weight": position.weight,
            "fen": position.fen,
            "side_to_move": "white" if board.turn == chess.WHITE else "black",
            "outcome": "legal_move",
            "move": move.uci(),
            "move_san": board.san(move),
            "response": response_text,
            "engine_best_move": best_move.uci() if best_move else None,
            "engine_best_san": board.san(best_move) if best_move else None,
            "exact_engine_match": bool(best_move and move == best_move),
            "centipawn_loss": loss,
            "score": quality,
            "weighted_score": weighted,
            "chosen_engine_line": serialize_engine_lines(board, [chosen_line])[0],
            "engine_lines": serialize_engine_lines(board, engine_lines),
        }

    def _report_progress(self, completed: int):
        if self.progress_callback:
            self.progress_callback(completed, self.total_positions)

    def _log(self, message: str):
        if self.verbose:
            self.stream.write(f"{message}\n")
            self.stream.flush()


def forfeit_result(position: Position, board: chess.Board, engine_lines, error: str, reason: str) -> dict:
    best_move = engine_lines[0].move if engine_lines else None
    return {
        "position_id": position.position_id,
        "position_name": position.name,
        "category": position.category,
        "weight": position.weight,
        "fen": position.fen,
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "outcome": reason,
        "error": error,
        "move": None,
        "engine_best_move": best_move.uci() if best_move else None,
        "engine_best_san": board.san(best_move) if best_move else None,
        "exact_engine_match": False,
        "centipawn_loss": None,
        "score": 0.0,
        "weighted_score": 0.0,
        "engine_lines": serialize_engine_lines(board, engine_lines),
    }


def serialize_engine_lines(board: chess.Board, lines) -> list[dict]:
    records = []
    for line in lines:
        records.append(
            {
                "move": line.move.uci(),
                "san": board.san(line.move),
                "score_cp": line.score_cp,
                "pv": line.pv,
            }
        )
    return records


def position_manifest(position: Position) -> dict:
    board = chess.Board(position.fen)
    return {
        "position_id": position.position_id,
        "position_name": position.name,
        "category": position.category,
        "weight": position.weight,
        "fen": position.fen,
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
    }


def update_summary(summary: BenchmarkSummary, result: dict) -> None:
    summary.positions += 1
    summary.total_weight += float(result["weight"])
    summary.weighted_score += float(result["weighted_score"])
    if result["outcome"] == "legal_move":
        summary.legal_moves += 1
    else:
        summary.forfeits += 1
    if result["exact_engine_match"]:
        summary.exact_engine_matches += 1

    category = result["category"]
    bucket = summary.by_category.setdefault(
        category,
        {"positions": 0, "score": 0.0, "weight": 0.0, "exact_engine_matches": 0, "forfeits": 0},
    )
    bucket["positions"] += 1
    bucket["score"] += float(result["weighted_score"])
    bucket["weight"] += float(result["weight"])
    bucket["exact_engine_matches"] += 1 if result["exact_engine_match"] else 0
    bucket["forfeits"] += 1 if result["outcome"] != "legal_move" else 0


def finalize_summary(summary: BenchmarkSummary) -> dict:
    normalized = 100.0 * summary.weighted_score / summary.total_weight if summary.total_weight else 0.0
    by_category = {}
    for category, stats in summary.by_category.items():
        weight = float(stats["weight"])
        category_score = 100.0 * float(stats["score"]) / weight if weight else 0.0
        by_category[category] = {**stats, "normalized_score": round(category_score, 2)}
    return {
        "positions": summary.positions,
        "legal_moves": summary.legal_moves,
        "forfeits": summary.forfeits,
        "exact_engine_matches": summary.exact_engine_matches,
        "weighted_score": round(summary.weighted_score, 4),
        "total_weight": round(summary.total_weight, 4),
        "normalized_score": round(normalized, 2),
        "by_category": by_category,
    }


def run_benchmark(args, progress_callback=None, start_callback=None) -> tuple[Path, dict]:
    model_config = load_model_config(args.model, args.model_file)
    position_ids = [item.strip() for item in args.positions.split(",") if item.strip()] if args.positions else None
    output_path = BENCHMARK_DIR / f"{model_config.config_name}.json"
    web_path = default_web_path(output_path)
    live_data_path = default_live_data_path(web_path)

    def live_callback(report: dict) -> None:
        if getattr(args, "show_web", False):
            write_live_data(report, live_data_path)

    engine_config = EngineConfig(
        path=resolve_engine_path(args.engine),
        movetime_ms=args.movetime,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash,
        multipv=args.multipv,
    )
    runner = BenchmarkRunner(
        model_config,
        positions=get_positions(position_ids),
        engine_config=engine_config,
        progress_callback=progress_callback,
        live_callback=live_callback,
        verbose=args.verbose,
        debug_http=args.debug_http,
    )
    if getattr(args, "show_web", False):
        initial_report = runner._build_report([], BenchmarkSummary(), "running")
        write_live_data(initial_report, live_data_path)
        write_web_report(initial_report, web_path, live_data_path)
    if start_callback:
        start_callback(runner)
    report = runner.run()
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if getattr(args, "show_web", False):
        write_live_data(report, live_data_path)
        write_web_report(report, web_path, live_data_path)
    return output_path, report
