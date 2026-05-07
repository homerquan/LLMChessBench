from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    position_id: str
    name: str
    fen: str
    category: str
    weight: float = 1.0


DEFAULT_POSITIONS = [
    Position(
        "opening_center",
        "Classical opening center",
        "rnbqkbnr/ppp2ppp/4p3/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R w KQkq - 0 3",
        "opening",
        0.9,
    ),
    Position(
        "opening_gambit",
        "King safety in a gambit",
        "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR b KQkq - 2 2",
        "opening",
        0.9,
    ),
    Position(
        "tactic_pin",
        "Pinned knight tactic",
        "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w kq - 6 7",
        "tactic",
        1.25,
    ),
    Position(
        "tactic_fork",
        "Fork pressure",
        "r2qk2r/ppp2ppp/2npbn2/4p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 b kq - 7 8",
        "tactic",
        1.25,
    ),
    Position(
        "middlegame_iqp",
        "Isolated queen pawn",
        "r2q1rk1/pp2bppp/2n1bn2/2pp4/3P4/2NBPN2/PPQ2PPP/R1B2RK1 w - - 0 10",
        "middlegame",
        1.1,
    ),
    Position(
        "middlegame_kingside",
        "Kingside attack choice",
        "r1bq1rk1/ppp2ppp/2np1n2/4p3/2B1P3/2NP1N1P/PPP2PP1/R1BQ1RK1 w - - 0 8",
        "middlegame",
        1.1,
    ),
    Position(
        "defense_under_fire",
        "Defensive resource",
        "r3r1k1/ppp2ppp/2n2n2/3qp3/3P4/2PB1N2/PP3PPP/R2QR1K1 b - - 0 15",
        "defense",
        1.15,
    ),
    Position(
        "endgame_rook",
        "Rook endgame activity",
        "8/5pk1/6p1/2R1p2p/4P2P/5PP1/5K2/r7 w - - 0 40",
        "endgame",
        1.2,
    ),
    Position(
        "endgame_king",
        "King and pawn race",
        "8/8/5k2/4p3/4P3/5K2/8/8 w - - 0 1",
        "endgame",
        1.0,
    ),
    Position(
        "mate_net",
        "Mate net awareness",
        "6k1/5ppp/8/8/8/8/5PPP/5RK1 w - - 0 1",
        "mate",
        1.3,
    ),
]


def get_positions(position_ids: list[str] | None = None) -> list[Position]:
    if not position_ids:
        return list(DEFAULT_POSITIONS)
    by_id = {position.position_id: position for position in DEFAULT_POSITIONS}
    missing = [position_id for position_id in position_ids if position_id not in by_id]
    if missing:
        raise ValueError(f"Unknown position id(s): {', '.join(missing)}")
    return [by_id[position_id] for position_id in position_ids]
