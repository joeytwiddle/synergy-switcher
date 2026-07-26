"""Quick test for synergy log parsing."""
from src.synergy_switcher.core import parse_log_line, Event

def test():
    cases = [
        (
            'core       [2026-07-27T13:47:05] - INFO    - switch from "tortillalinux-ffc082e5" to "silvermacbook-523445cf" at 1511,199',
            Event(kind="switched", from_screen="tortillalinux-ffc082e5", to_screen="silvermacbook-523445cf", timestamp="2026-07-27T13:47:05")
        ),
        (
            'core       [2026-07-27T13:47:05] - INFO    - leaving screen',
            Event(kind="left", timestamp="2026-07-27T13:47:05")
        ),
        (
            'core       [2026-07-27T13:47:06] - INFO    - entering screen',
            Event(kind="entered", timestamp="2026-07-27T13:47:06")
        ),
        (
            'core       [2026-07-27T10:23:55] - NOTE    - started client',
            None
        ),
        (
            'service    [2026-07-27T15:32:53] - INFO    - process is now exiting',
            None
        ),
        (
            'not a synergy log line',
            None
        ),
    ]

    for line, expected in cases:
        result = parse_log_line(line)
        if expected is None:
            assert result is None, f"expected None, got {result}"
        else:
            assert result is not None, f"expected {expected}, got None"
            assert result.kind == expected.kind, f"kind: {result.kind} != {expected.kind}"
            assert result.from_screen == expected.from_screen, f"from: {result.from_screen} != {expected.from_screen}"
            assert result.to_screen == expected.to_screen, f"to: {result.to_screen} != {expected.to_screen}"
            assert result.timestamp == expected.timestamp, f"timestamp: {result.timestamp} != {expected.timestamp}"

    print("All tests passed!")

if __name__ == "__main__":
    test()
