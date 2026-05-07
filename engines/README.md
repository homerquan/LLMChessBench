# Chess Engines

LLMCheesBench expects a UCI engine. The default target is Stockfish because it is free, very strong, actively maintained, widely packaged, and scales well across CPU threads.

Recommended local setup:

```bash
brew install stockfish
```

Then run:

```bash
llmcheesbench engine-best --threads 8 --hash 1024 --movetime 2000
```

Other popular single-PC UCI engines you can try:

- Stockfish: strongest default recommendation for CPU search.
- Berserk: strong open-source CPU engine and useful cross-check.
- Ethereal: strong open-source CPU engine with a different style.
- Lc0: neural-network engine; strongest with a good GPU, less ideal for CPU-only comparisons.

Pass any engine with:

```bash
llmcheesbench benchmark --model my-model --engine /path/to/engine --threads 8 --hash 1024
```
