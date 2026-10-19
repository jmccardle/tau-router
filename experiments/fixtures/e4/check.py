"""Run: python3 check.py — prints each failing check, then a PASS count."""

import solution as s

CHECKS = [
    ("parse 1h30m", lambda: s.parse_duration("1h30m") == 5400),
    ("parse 2d", lambda: s.parse_duration("2d") == 172800),
    ("parse 1d2h3m4s", lambda: s.parse_duration("1d2h3m4s") == 93784),
    ("parse rejects 30m1h", lambda: _raises(s.parse_duration, "30m1h")),
    ("parse rejects empty", lambda: _raises(s.parse_duration, "")),
    ("parse rejects 1x", lambda: _raises(s.parse_duration, "1x")),
    ("format 5400", lambda: s.format_duration(5400) == "1h30m"),
    ("format 0", lambda: s.format_duration(0) == "0s"),
    ("format 93784", lambda: s.format_duration(93784) == "1d2h3m4s"),
    ("format 86401", lambda: s.format_duration(86401) == "1d1s"),
    ("format negative", lambda: _raises(s.format_duration, -1)),
    ("roman 1994", lambda: s.to_roman(1994) == "MCMXCIV"),
    ("roman 3999", lambda: s.to_roman(3999) == "MMMCMXCIX"),
    ("roman 0 raises", lambda: _raises(s.to_roman, 0)),
    ("from_roman XLII", lambda: s.from_roman("XLII") == 42),
    ("from_roman rejects IIII", lambda: _raises(s.from_roman, "IIII")),
    ("from_roman rejects IC", lambda: _raises(s.from_roman, "IC")),
    ("roman roundtrip", lambda: all(s.from_roman(s.to_roman(n)) == n for n in range(1, 4000))),
    ("merge touching", lambda: s.merge_intervals([(3, 5), (1, 3)]) == [(1, 5)]),
    ("merge nested", lambda: s.merge_intervals([(1, 10), (2, 3), (12, 14)]) == [(1, 10), (12, 14)]),
    ("merge empty", lambda: s.merge_intervals([]) == []),
    ("wrap basic", lambda: s.wrap("the quick brown fox", 10) == ["the quick", "brown fox"]),
    ("wrap long word", lambda: s.wrap("abcdefghij xy", 4) == ["abcd", "efgh", "ij", "xy"]),
    ("wrap exact", lambda: s.wrap("abcd efgh", 4) == ["abcd", "efgh"]),
    ("luhn valid", lambda: s.luhn_ok("4539 1488 0343 6467") is True),
    ("luhn invalid", lambda: s.luhn_ok("8273 1232 7352 0569") is False),
    ("luhn letters", lambda: s.luhn_ok("4539a1488") is False),
    ("luhn empty", lambda: s.luhn_ok("") is False),
]


def _raises(fn, arg):
    try:
        fn(arg)
    except ValueError:
        return True
    except Exception:
        return False
    return False


passed = 0
for name, check in CHECKS:
    try:
        ok = check()
    except Exception as exc:  # noqa: BLE001
        ok = False
        name += f" ({type(exc).__name__})"
    if ok:
        passed += 1
    else:
        print("FAIL", name)
print(f"{passed}/{len(CHECKS)} passed")
if passed == len(CHECKS):
    print("ALL PASS")
