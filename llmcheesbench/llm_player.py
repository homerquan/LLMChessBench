from __future__ import annotations

import json
import re
import threading
import time
from http.client import HTTPException
from pathlib import Path
from urllib import error, request

import chess


MOVE_RE = re.compile(
    r"\b(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O-O|O-O|0-0-0|0-0|[a-h][1-8][a-h][1-8][qrbn]?)\b"
)


class LLMMoveError(RuntimeError):
    pass


class LLMRequestError(LLMMoveError):
    pass


class RequestRateLimiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / max(1, rpm)
        self.next_request_at = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.interval
        if delay:
            time.sleep(delay)


class LLMPlayer:
    def __init__(self, model_config, debug_http: bool = False, reasoning_log_path: Path | None = None):
        self.model_config = model_config
        self.debug_http = debug_http
        self.reasoning_log_path = Path(reasoning_log_path) if reasoning_log_path else None
        self.rate_limiter = RequestRateLimiter(model_config.rate_limit_rpm)

    def choose_move(self, position_name: str, board: chess.Board, fallback_uci: str, attempt_limit: int = 4) -> tuple[chess.Move, str]:
        last_error = None
        for attempt in range(1, attempt_limit + 1):
            prompt = build_prompt(position_name, board, fallback_uci, attempt, last_error)
            response_text = self._chat(prompt, attempt)
            move = parse_move_response(response_text, board)
            if move:
                return move, response_text
            last_error = f"Could not find an exact legal UCI or SAN move in response: {response_text!r}"
        raise LLMMoveError(last_error or "Model did not return a legal move.")

    def _chat(self, prompt: str, attempt: int) -> str:
        api_key = self.model_config.get_api_key()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.model_config.model_id,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 1024,
        }
        payload.update(self.model_config.extra_body)
        self.rate_limiter.wait()
        response_body = self._post_json(f"{self.model_config.base_url}/chat/completions", headers, payload)
        message, reasoning = parse_chat_response(response_body)
        content = normalize_content(message.get("content"), reasoning)
        self._log(prompt, attempt, response_body, message, reasoning)
        return content

    def _post_json(self, endpoint: str, headers: dict[str, str], payload: dict) -> str:
        data = json.dumps(payload).encode("utf-8")
        http_request = request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self.model_config.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = ""
            if self.debug_http:
                try:
                    detail = "\n" + exc.read().decode("utf-8")
                except Exception:
                    detail = "\n<failed to read response body>"
            raise LLMRequestError(f"Request to {endpoint} failed: {exc}{detail}") from exc
        except (error.URLError, HTTPException, OSError) as exc:
            raise LLMRequestError(f"Request to {endpoint} failed: {exc}") from exc

    def _log(self, prompt: str, attempt: int, response_body: str, message: dict, reasoning: str):
        if not self.reasoning_log_path:
            return
        self.reasoning_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reasoning_log_path.open("a", encoding="utf-8") as handle:
            json.dump(
                {
                    "model": self.model_config.model_id,
                    "attempt": attempt,
                    "prompt": prompt,
                    "message": message,
                    "reasoning": reasoning,
                    "raw_response": response_body,
                },
                handle,
            )
            handle.write("\n")


def system_prompt() -> str:
    return (
        "You are playing chess in a move-quality benchmark. "
        "Return exactly one legal move at the start of your reply, preferably UCI such as e2e4. "
        "Do not resign and do not write analysis before the move."
    )


def build_prompt(position_name: str, board: chess.Board, fallback_uci: str, attempt: int, last_error: str | None) -> str:
    legal_uci = [move.uci() for move in board.legal_moves]
    legal_san = [board.san(move) for move in board.legal_moves]
    prompt = [
        f"Position: {position_name}",
        f"Side to move: {'White' if board.turn == chess.WHITE else 'Black'}.",
        "Choose the strongest legal chess move for the side to move.",
        f"FEN: {board.fen()}",
        f"Board:\n{board.unicode(empty_square='.')}",
        f"LEGAL_UCI_MOVES: {', '.join(legal_uci)}",
        f"LEGAL_SAN_MOVES: {', '.join(legal_san)}",
        f"If unsure, choose this legal fallback move: {fallback_uci}",
        "Critical response rule: the first characters of your reply must be exactly one move from LEGAL_UCI_MOVES or LEGAL_SAN_MOVES.",
    ]
    if last_error:
        prompt.extend(["", f"Previous attempt {attempt - 1} was rejected: {last_error}", "Try again with one exact legal move."])
    return "\n".join(prompt)


def parse_move_response(response_text: str, board: chess.Board) -> chess.Move | None:
    stripped = str(response_text).strip()
    legal_by_uci = {move.uci().lower(): move for move in board.legal_moves}

    first_token = stripped.split(maxsplit=1)[0].strip("`.,:;()[]{}") if stripped else ""
    for candidate in [first_token, *[match.group(0) for match in MOVE_RE.finditer(stripped)]]:
        normalized = candidate.replace("0", "O").strip()
        move = legal_by_uci.get(candidate.lower())
        if move:
            return move
        try:
            parsed = board.parse_san(normalized)
        except ValueError:
            continue
        if parsed in board.legal_moves:
            return parsed
    return None


def parse_chat_response(response_body: str) -> tuple[dict, str]:
    try:
        payload = json.loads(response_body)
        choice = payload["choices"][0]
        message = choice.get("message") or {"content": choice.get("text", "")}
        reasoning = message.get("reasoning") or choice.get("reasoning", "")
        return message, reasoning
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMRequestError(f"Unexpected model response: {response_body}") from exc


def normalize_content(content, reasoning: str = "") -> str:
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    content = "" if content is None else str(content).strip()
    return content or str(reasoning).strip()
