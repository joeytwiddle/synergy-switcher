# synergy-switcher

Detects when Synergy focus enters or leaves the local device and fires configurable actions.

## How it works

Tails the Synergy 3 log file (`~/.local/state/Synergy/synergy.log`) and parses screen-switch events. When the mouse/focus enters or leaves this device, it runs whatever commands you've configured.

## Install

### Option 1: pipx (recommended) — isolates the package, puts the binary on PATH

```bash
pipx install /path/to/synergy-switcher
synergy-switcher
```

### Option 2: pip in a venv

```bash
cd /path/to/synergy-switcher
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/synergy-switcher
```

### Option 3: run without installing

```bash
cd /path/to/synergy-switcher
python src/synergy_switcher/core.py
```

## Configuration

Place a TOML file at `~/.config/synergy-switcher/config.toml`:

```toml
# Friendly names for synergy screen IDs (optional)
[screens]
"tortillalinux-ffc082e5" = "Linux Desktop"
"silvermacbook-523445cf" = "MacBook"

[actions]

# Single command — just a string
OnEnterExec = "notify-send 'Synergy' 'Focus entered {to_name}'"

# Multiple commands — use an array
OnLeaveExec = [
    "notify-send 'Synergy' 'Focus left to {to_name}'",
    "playerctl pause",
]

# Runs when leaving, but only if this device is currently the Synergy Host
OnLeaveHostExec = "systemctl --user start synergy-autohide"

# Runs when entering, but only if this device is currently a Synergy Remote
OnEnterRemoteExec = "systemctl --user stop synergy-autohide"

# Runs when this device switches between Host and Remote roles
OnRoleChangeExec = "notify-send 'Synergy' 'Role changed to {to}'"
```

### Template variables

| Variable     | Description |
|--------------|-------------|
| `{from}`     | Originating screen ID |
| `{to}`       | Destination screen ID |
| `{from_name}`| Friendly name from `[screens]` |
| `{to_name}`  | Friendly name from `[screens]` |
| `{screen}`   | The "other" screen |
| `{kind}`     | Event kind (`entered` / `left` / `role_changed`) |
| `{timestamp}`| Timestamp from the Synergy log |

### Optional settings

```toml
# Path to synergy log (default: ~/.local/state/Synergy/synergy.log)
log_path = "~/.local/state/Synergy/synergy.log"

# Log poll interval in seconds (default: 0.5)
poll_interval = 0.5

# Role check interval in seconds (default: 5.0)
role_check_interval = 5.0
```

## Usage

```bash
synergy-switcher            # run (stays in foreground)
synergy-switcher --dry-run  # log what would run, don't execute
synergy-switcher --verbose  # debug logging
synergy-switcher --version  # print version
```

## Example: auto-pause music on focus leave

```toml
[actions]
OnLeaveExec = "playerctl pause"
OnEnterExec = "playerctl play"
```

## Example: log focus changes with timestamps and screen names

```toml
[actions]
OnLeaveExec = """
  echo "[{timestamp}] left to {to_name}" >> ~/synergy-events.log
"""
OnEnterExec = """
  echo "[{timestamp}] entered from {from_name}" >> ~/synergy-events.log
"""
```

## Host/remote role detection

The tool checks every 5 seconds whether this machine is running `synergy-core server` (Host) or `synergy-core client` (Remote). When the role changes, it fires `OnRoleChangeExec`. This lets you configure different behaviour for when you switch roles on the fly, without restarting the watcher.

---

The action system uses `register_action_handler()` — adding new action types (http webhooks, dbus, mqtt, etc.) doesn't touch the core loop.

## Requirements

- Python ≥ 3.11 (stdlib `tomllib` added in 3.11)
- Synergy 3 (log at `~/.local/state/Synergy/synergy.log`)
