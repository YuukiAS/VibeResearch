"""Path helpers for target repositories."""

from __future__ import annotations

from pathlib import Path


class VibePaths:
    def __init__(self, target: str | Path = "."):
        self.root = Path(target).expanduser().resolve()
        self.vibe = self.root / ".vibe"
        self.inbox = self.vibe / "inbox"
        self.state = self.vibe / "state"
        self.cycles = self.vibe / "cycles"
        self.runs = self.vibe / "runs"
        self.directions = self.vibe / "directions"
        self.branches = self.vibe / "branches"
        self.leaderboard = self.vibe / "leaderboard"
        self.scheduler = self.vibe / "scheduler"
        self.executor = self.vibe / "executor"
        self.research = self.vibe / "research"
        self.dashboard = self.vibe / "dashboard"
        self.prompts = self.vibe / "prompts"
        self.templates = self.executor / "templates"

    def require_initialized(self) -> None:
        if not self.vibe.exists():
            raise FileNotFoundError(f"{self.root} is not initialized; run `vibe init --target {self.root}`")

