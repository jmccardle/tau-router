"""Implement every function so that `python3 check.py durations` prints ALL PASS."""


def parse_duration(text: str) -> int:
    """'1h30m' -> 5400. Units d, h, m, s, each at most once, in that order. Raise ValueError otherwise."""
    raise NotImplementedError


def format_duration(seconds: int) -> str:
    """5400 -> '1h30m'; 0 -> '0s'; omit zero units; negative raises ValueError."""
    raise NotImplementedError
