from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine


MATE_CP = 100000


@dataclass(frozen=True)
class EngineConfig:
    path: str
    movetime_ms: int = 1000
    depth: int | None = None
    threads: int = 1
    hash_mb: int = 256
    multipv: int = 4


@dataclass(frozen=True)
class EngineLine:
    move: chess.Move
    score_cp: int
    pv: list[str]


def resolve_engine_path(path: str | None = None) -> str:
    candidates = [
        path,
        os.environ.get("LLMCHEESBENCH_ENGINE"),
        os.environ.get("CHESSBENCH_ENGINE"),
        shutil.which("stockfish"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().exists():
            return str(Path(candidate).expanduser())
        if candidate and shutil.which(candidate):
            return str(shutil.which(candidate))
    raise FileNotFoundError(
        "No UCI engine found. Install Stockfish or set LLMCHEESBENCH_ENGINE=/path/to/stockfish "
        "or pass --engine /path/to/stockfish."
    )


class UCIEngine:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.engine = chess.engine.SimpleEngine.popen_uci(config.path)
        options = {}
        if "Threads" in self.engine.options:
            options["Threads"] = config.threads
        if "Hash" in self.engine.options:
            options["Hash"] = config.hash_mb
        if options:
            self.engine.configure(options)

    def analyze(self, board: chess.Board) -> list[EngineLine]:
        limit = chess.engine.Limit(depth=self.config.depth) if self.config.depth else chess.engine.Limit(time=self.config.movetime_ms / 1000)
        info = self.engine.analyse(board, limit, multipv=max(1, self.config.multipv))
        if isinstance(info, dict):
            info = [info]
        lines = []
        for item in info:
            pv = item.get("pv") or []
            if not pv:
                continue
            score = item["score"].pov(board.turn)
            lines.append(EngineLine(move=pv[0], score_cp=score_to_cp(score), pv=[move.uci() for move in pv]))
        return lines

    def analyze_move(self, board: chess.Board, move: chess.Move) -> EngineLine:
        limit = chess.engine.Limit(depth=self.config.depth) if self.config.depth else chess.engine.Limit(time=self.config.movetime_ms / 1000)
        info = self.engine.analyse(board, limit, root_moves=[move])
        pv = info.get("pv") or [move]
        score = info["score"].pov(board.turn)
        return EngineLine(move=move, score_cp=score_to_cp(score), pv=[item.uci() for item in pv])

    def close(self):
        self.engine.quit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def score_to_cp(score: chess.engine.PovScore) -> int:
    mate = score.mate()
    if mate is not None:
        sign = 1 if mate > 0 else -1
        return sign * (MATE_CP - min(999, abs(mate)))
    cp = score.score()
    return int(cp or 0)


def centipawn_loss(engine_lines: list[EngineLine], chosen_line: EngineLine) -> int:
    if not engine_lines:
        return 0
    best = max(line.score_cp for line in engine_lines)
    return max(0, best - chosen_line.score_cp)


def move_quality_score(cp_loss: int) -> float:
    if cp_loss <= 0:
        return 1.0
    if cp_loss >= 600:
        return 0.0
    return round(max(0.0, 1.0 - (cp_loss / 600.0) ** 0.75), 4)
