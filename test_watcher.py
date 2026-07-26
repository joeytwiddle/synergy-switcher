"""Test the LogWatcher end-to-end with a temp file."""
import tempfile
from pathlib import Path
from src.synergy_switcher.core import LogWatcher

def test():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        f.write("""core       [2026-07-27T10:00:00] - INFO    - starting\n""")
        log_path = Path(f.name)

    try:
        watcher = LogWatcher(log_path, local_screen="tortillalinux-ffc082e5")
        watcher.seek_to_end()

        events = watcher.read_new_events()
        assert events == [], f"expected no events, got {events}"

        with open(log_path, "a") as f:
            f.write('core       [2026-07-27T10:00:01] - INFO    - switch from "remote" to "tortillalinux-ffc082e5" at 100,200\n')
            f.write('core       [2026-07-27T10:00:01] - INFO    - entering screen\n')

        events = watcher.read_new_events()
        assert len(events) == 2, f"expected 2 events, got {len(events)}: {events}"
        assert events[0].kind == "switched"
        assert events[0].from_screen == "remote"
        assert events[0].to_screen == "tortillalinux-ffc082e5"

        assert events[1].kind == "entered"
        assert events[1].from_screen == "remote"
        assert events[1].to_screen == "tortillalinux-ffc082e5"

        with open(log_path, "a") as f:
            f.write('core       [2026-07-27T10:00:02] - INFO    - switch from "tortillalinux-ffc082e5" to "remote" at 200,100\n')
            f.write('core       [2026-07-27T10:00:02] - INFO    - leaving screen\n')

        events = watcher.read_new_events()
        assert len(events) == 2, f"expected 2 events, got {len(events)}: {events}"
        assert events[0].kind == "switched"
        assert events[0].from_screen == "tortillalinux-ffc082e5"
        assert events[0].to_screen == "remote"
        assert events[1].kind == "left"
        assert events[1].from_screen == "tortillalinux-ffc082e5"
        assert events[1].to_screen == "remote"

        print("All watcher tests passed!")
    finally:
        log_path.unlink(missing_ok=True)

if __name__ == "__main__":
    test()
