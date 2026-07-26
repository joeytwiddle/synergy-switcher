import os
import re
import sys
import time
import signal
import tomllib
import logging
import argparse
import subprocess
import shlex
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("synergy-switcher")

VERSION = "0.1.0"

# --- Default paths ---

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))

CONFIG_FILE = XDG_CONFIG_HOME / "synergy-switcher" / "config.toml"

SYNERGY_STATE_DIR = XDG_STATE_HOME / "Synergy"
SYNERGY_CONFIG_DIR = XDG_CONFIG_HOME / "Synergy"
SYNERGY_LOG = SYNERGY_STATE_DIR / "synergy.log"
SYNERGY_LOCAL_JSON = SYNERGY_CONFIG_DIR / "local.json"
SYNERGY_CONF = SYNERGY_CONFIG_DIR / "synergy.conf"

# --- Event ---

@dataclass
class Event:
    kind: str
    from_screen: Optional[str] = None
    to_screen: Optional[str] = None
    timestamp: Optional[str] = None

# --- Config ---

@dataclass
class ActionConfig:
    command: Optional[str] = None

    @classmethod
    def from_dict(cls, d) -> "ActionConfig":
        if isinstance(d, str):
            return cls(command=d)
        return cls(command=d.get("command") if isinstance(d, dict) else None)

@dataclass
class Config:
    log_path: Path = SYNERGY_LOG
    poll_interval: float = 0.5
    role_check_interval: float = 5.0
    OnEnterExec: ActionConfig = field(default_factory=ActionConfig)
    OnLeaveExec: ActionConfig = field(default_factory=ActionConfig)
    OnLeaveHostExec: ActionConfig = field(default_factory=ActionConfig)
    OnEnterRemoteExec: ActionConfig = field(default_factory=ActionConfig)
    OnRoleChangeExec: ActionConfig = field(default_factory=ActionConfig)
    screens: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()

        if not CONFIG_FILE.exists():
            log.info("no config at %s, using defaults", CONFIG_FILE)
            return cfg

        raw = CONFIG_FILE.read_bytes()
        try:
            data = tomllib.loads(raw.decode())
        except Exception as e:
            log.warning("failed to parse config: %s", e)
            return cfg

        if "log_path" in data:
            cfg.log_path = Path(data["log_path"]).expanduser()
        if "poll_interval" in data:
            cfg.poll_interval = float(data["poll_interval"])
        if "role_check_interval" in data:
            cfg.role_check_interval = float(data["role_check_interval"])
        if "screens" in data:
            cfg.screens = data["screens"]

        actions = data.get("actions", {})
        for key in ("OnEnterExec", "OnLeaveExec", "OnLeaveHostExec",
                     "OnEnterRemoteExec", "OnRoleChangeExec"):
            if key in actions:
                setattr(cfg, key, ActionConfig.from_dict(actions[key]))

        return cfg

# --- Synergy environment ---

def detect_synergy_role() -> str:
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if "synergy-core" not in line:
                continue
            if " server " in line:
                return "host"
            if " client " in line:
                return "remote"
    except Exception:
        pass
    return "unknown"

def detect_local_screen_name() -> Optional[str]:
    try:
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            m = re.search(r'--name\s+(\S+)', line)
            if m:
                return m.group(1)
    except Exception:
        pass

    if SYNERGY_CONF.exists():
        try:
            text = SYNERGY_CONF.read_text()
            m = re.search(r'(?:^|\n)\s+(\S+):\s*$', text, re.MULTILINE)
            if m:
                return m.group(1)
        except Exception:
            pass

    return None

def get_display_name(screen_name: str, screens_map: dict[str, str]) -> str:
    return screens_map.get(screen_name, screen_name)

# --- Log parsing ---

SWITCH_RE = re.compile(r'switch from "([^"]+)" to "([^"]+)" at \d+,\d+')
ENTER_RE = re.compile(r'entering screen')
LEAVE_RE = re.compile(r'leaving screen')
TIMESTAMP_RE = re.compile(r'\[([^\]]+)\]')

def parse_log_line(line: str) -> Optional[Event]:
    if " - " not in line:
        return None

    ts_match = TIMESTAMP_RE.search(line)
    timestamp = ts_match.group(1) if ts_match else None

    parts = line.split(" - ", 2)
    if len(parts) < 3:
        return None
    msg = parts[2]

    m = SWITCH_RE.search(msg)
    if m:
        return Event(kind="switched", from_screen=m.group(1), to_screen=m.group(2), timestamp=timestamp)

    if ENTER_RE.search(msg):
        return Event(kind="entered", timestamp=timestamp)

    if LEAVE_RE.search(msg):
        return Event(kind="left", timestamp=timestamp)

    return None

# --- Log watcher ---

class LogWatcher:
    def __init__(self, path: Path, local_screen: Optional[str]):
        self.path = path
        self.local_screen = local_screen
        self._pos = 0
        self._pending_switch: Optional[tuple[str, str]] = None

    def seek_to_end(self):
        if self.path.exists():
            self._pos = self.path.stat().st_size

    def read_new_events(self) -> list[Event]:
        if not self.path.exists():
            return []

        current_size = self.path.stat().st_size

        if current_size < self._pos:
            self._pos = 0

        if current_size <= self._pos:
            self._pos = current_size
            return []

        with open(self.path, "r") as f:
            f.seek(self._pos)
            new_data = f.read()
            self._pos = f.tell()

        events = []
        for line in new_data.splitlines():
            raw = parse_log_line(line)
            if not raw:
                continue

            if raw.kind == "switched":
                self._pending_switch = (raw.from_screen, raw.to_screen)
                events.append(raw)
                continue

            if raw.kind in ("entered", "left") and self._pending_switch:
                raw.from_screen, raw.to_screen = self._pending_switch

            events.append(raw)

        return events

# --- Action execution ---

ACTION_HANDLERS: dict[str, callable] = {}

def register_action_handler(action_type: str, handler: callable):
    ACTION_HANDLERS[action_type] = handler

def _try_run(action_cfg: ActionConfig, event: Event, cfg: Config, dry_run: bool):
    if not action_cfg.command:
        return
    if dry_run:
        log.info("[DRY-RUN] would run: %s", action_cfg.command)
    else:
        _run_command(action_cfg.command, event, cfg)

def run_actions(event: Event, cfg: Config, current_role: str, dry_run: bool = False):
    action_map = {
        "entered": cfg.OnEnterExec,
        "left": cfg.OnLeaveExec,
        "role_changed": cfg.OnRoleChangeExec,
    }
    action_cfg = action_map.get(event.kind)
    if action_cfg is not None:
        _try_run(action_cfg, event, cfg, dry_run)

    if event.kind == "left" and current_role == "host":
        _try_run(cfg.OnLeaveHostExec, event, cfg, dry_run)

    if event.kind == "entered" and current_role == "remote":
        _try_run(cfg.OnEnterRemoteExec, event, cfg, dry_run)

def _run_command(template: str, event: Event, cfg: Config):
    screen_map = cfg.screens or {}
    ctx = {
        "screen": event.to_screen or event.from_screen or "",
        "from": event.from_screen or "",
        "to": event.to_screen or "",
        "from_name": get_display_name(event.from_screen or "", screen_map),
        "to_name": get_display_name(event.to_screen or "", screen_map),
        "kind": event.kind,
        "timestamp": event.timestamp or "",
    }
    try:
        cmd_str = template.format(**ctx)
        subprocess.Popen(shlex.split(cmd_str), start_new_session=True)
    except Exception as e:
        log.error("failed to run command: %s", e)

register_action_handler("command", _run_command)

# --- Main ---

_should_run = True

def _signal_handler(signum, frame):
    global _should_run
    _should_run = False
    log.info("shutting down...")

def print_startup_banner(cfg: Config, role: str, local: Optional[str]):
    log.info("synergy-switcher v%s starting", VERSION)
    log.info("  role: %s", role)
    log.info("  local screen: %s", local)
    log.info("  watching: %s", cfg.log_path)
    if cfg.OnEnterExec.command:
        log.info("  OnEnterExec: %s", cfg.OnEnterExec.command)
    if cfg.OnLeaveExec.command:
        log.info("  OnLeaveExec: %s", cfg.OnLeaveExec.command)
    if cfg.OnLeaveHostExec.command:
        log.info("  OnLeaveHostExec: %s", cfg.OnLeaveHostExec.command)
    if cfg.OnEnterRemoteExec.command:
        log.info("  OnEnterRemoteExec: %s", cfg.OnEnterRemoteExec.command)
    if cfg.OnRoleChangeExec.command:
        log.info("  OnRoleChangeExec: %s", cfg.OnRoleChangeExec.command)

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="synergy-switcher")
    p.add_argument("--version", action="version", version=f"synergy-switcher {VERSION}")
    p.add_argument("--dry-run", action="store_true", help="Log what would be run without executing")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return p.parse_args(argv)

def main():
    args = parse_args(sys.argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cfg = Config.load()
    local_screen = detect_local_screen_name()
    current_role = detect_synergy_role()
    watcher = LogWatcher(cfg.log_path, local_screen)
    watcher.seek_to_end()

    print_startup_banner(cfg, current_role, local_screen)

    if args.dry_run:
        log.info("dry-run mode enabled, no commands will execute")

    last_role_check = 0.0

    while _should_run:
        now = time.monotonic()

        events = watcher.read_new_events()
        for event in events:
            screen_map = cfg.screens or {}
            parts = [f"event: {event.kind}"]
            if event.from_screen:
                parts.append(f"from={get_display_name(event.from_screen, screen_map)}")
            if event.to_screen:
                parts.append(f"to={get_display_name(event.to_screen, screen_map)}")
            log.info(" ".join(parts))
            run_actions(event, cfg, current_role, dry_run=args.dry_run)

        if now - last_role_check >= cfg.role_check_interval:
            last_role_check = now
            new_role = detect_synergy_role()
            if new_role != current_role:
                log.info("role changed: %s -> %s", current_role, new_role)
                old_role = current_role
                current_role = new_role
                event = Event(kind="role_changed", from_screen=old_role, to_screen=new_role)
                run_actions(event, cfg, current_role, dry_run=args.dry_run)

        time.sleep(cfg.poll_interval)

    log.info("goodbye")


if __name__ == "__main__":
    main()
