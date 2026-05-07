# LLMCheesBench

LLMCheesBench is a BoardGameBench-style LLM benchmark for chess. It scores model move quality against a local UCI master engine, with Stockfish as the default recommendation for a personal PC.

The benchmark is designed around the practical question:

> Which LLM can make strong chess moves when judged by a real local chess engine?

Instead of forcing every model through long full games, LLMCheesBench uses a compact position curriculum. Each model receives a FEN, board diagram, legal UCI moves, and legal SAN moves. The model must reply with one legal move. A local engine analyzes the same position, and LLMCheesBench scores the model by centipawn loss:

- exact engine top move = full credit
- small centipawn loss = high partial credit
- large blunder = low or zero credit
- illegal or unparsable move = forfeit for that position

This makes the benchmark fast, replayable, and suitable for comparing local or API models on one computer.

## Why Stockfish

For a personal PC, Stockfish is the best default master algorithm to use as the oracle: it is free, popular, very strong, UCI-compatible, easy to install, and scales across CPU threads with `Threads` and `Hash` settings. LLMCheesBench also accepts other UCI engines, so you can compare against Berserk, Ethereal, Komodo, or Lc0 if you have them installed.

## Quick Start

From this folder:

```bash
pip install .
brew install stockfish
llmcheesbench list-positions
llmcheesbench engine-best --threads 8 --hash 1024 --movetime 2000
llmcheesbench benchmark --model-file ./models/example-openai-compatible.json --threads 8 --hash 1024 --movetime 2000
llmcheesbench report
```

The old `chessbench` command is kept as a compatibility alias, but `llmcheesbench` is the primary command.

If Stockfish is not in your `PATH`, pass it directly:

```bash
llmcheesbench benchmark --model my-model --engine /path/to/stockfish
```

or set:

```bash
export LLMCHEESBENCH_ENGINE=/path/to/stockfish
```

## Model Configs

Model configs use the same OpenAI-compatible shape as BoardGameBench and GomokuBench:

```json
{
  "provider": {
    "openrouter": {
      "name": "OpenRouter",
      "options": {
        "baseURL": "https://openrouter.ai/api/v1",
        "apiKeyEnv": "OPENROUTER_API_KEY"
      },
      "models": {
        "my-model": {
          "name": "My Model",
          "model": "provider/model-id",
          "rate_limit_rpm": 30,
          "timeout_seconds": 120
        }
      }
    }
  }
}
```

Put configs in `models/<name>.json` and run:

```bash
llmcheesbench benchmark --model <name>
```

or pass a file directly:

```bash
llmcheesbench benchmark --model-file /path/to/model.json
```

## Engine Settings

The most important knobs:

- `--threads`: CPU threads for the engine.
- `--hash`: engine hash table size in MB.
- `--movetime`: milliseconds per position.
- `--depth`: optional fixed depth instead of time.
- `--multipv`: number of candidate engine lines saved and scored directly.

Example for a stronger desktop run:

```bash
llmcheesbench benchmark --model my-model --threads 16 --hash 4096 --movetime 5000 --multipv 8
```

## Position Suite

Run the default curriculum:

```bash
llmcheesbench benchmark --model my-model
```

Run a subset:

```bash
llmcheesbench benchmark --model my-model --positions opening_center,tactic_pin,endgame_rook
```

Available position categories:

- opening
- tactic
- middlegame
- defense
- endgame
- mate

Use `llmcheesbench list-positions` to see the current IDs.

## Outputs

Reports are saved in `benchmarks/<model>.json` and include:

- model and provider metadata
- engine path and CPU/hash/search settings
- aggregate score and per-category scores
- every model move and raw response
- engine top lines with centipawn scores
- centipawn loss per position
- a reasoning/API log path under `/tmp/llmcheesbench`

To print a leaderboard table from saved benchmark files:

```bash
llmcheesbench report
```

To also create an interactive browser replay when running a benchmark:

```bash
llmcheesbench benchmark --model my-model --show-web
```

The command prints a local URL like `http://localhost:8765/my-model.html` and keeps the replay server running until you press Ctrl-C. To choose a port:

```bash
llmcheesbench benchmark --model my-model --show-web --web-port 8765
```

The web replay starts before the benchmark finishes. Completed positions appear as the run progresses, and unfinished positions stay marked as waiting. Use **Compare Both** to see the LLM move and the master-AI move highlighted together on the starting board.

To create a replay from an existing JSON result:

```bash
llmcheesbench show-web benchmarks/my-model.json
```

The HTML replay is saved next to the JSON file and can be opened directly in a browser.

## Notes

LLMCheesBench is an LLM benchmark, not a replacement for engine-vs-engine testing. If your goal is simply to pick the strongest chess engine for a personal PC, start with Stockfish, then compare against other UCI engines at the same thread, hash, and time controls.
