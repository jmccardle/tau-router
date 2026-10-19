"""Implement every function so that `python3 check.py textutil` prints ALL PASS."""


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or touching [start, end] intervals; return sorted. (1,3),(3,5) -> (1,5)."""
    raise NotImplementedError


def wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap on spaces; words longer than width are split into width-sized pieces."""
    raise NotImplementedError


def luhn_ok(number: str) -> bool:
    """Luhn checksum over the digits of number; spaces allowed; any other character -> False; empty -> False."""
    raise NotImplementedError
