from __future__ import annotations

import sys


class BenchmarkProgress:
    def __init__(self, total: int, width: int = 32):
        self.total = max(1, total)
        self.width = width
        self.last = ""

    def update(self, completed: int):
        completed = min(self.total, max(0, completed))
        filled = int(self.width * completed / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        message = f"\r[{bar}] {completed}/{self.total}"
        sys.stdout.write(message)
        sys.stdout.flush()
        self.last = message

    def finish(self):
        self.update(self.total)
        self.newline()

    def newline(self):
        if self.last:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.last = ""
