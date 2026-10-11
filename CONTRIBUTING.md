# Contributing to Ventulus

## Setup

```bash
git clone https://github.com/Plan-B-Development/ventulus.git
cd ventulus
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Arch and CachyOS refuse a `pip install` outside a virtual environment (their Python
is "externally managed", PEP 668), so the venv is not optional there. The
`ventulus` command then exists only inside it: activate the venv first, or run
`.venv/bin/ventulus`.

A checkout does not include the daemon. Install `ventulusd` from the
[signed repository](manual/getting-started.md#installation) to work against real
hardware, or use demo mode, which needs neither:

```bash
ventulus --demo                         # simulated hardware, no daemon
ventulus                                # the daemon at /run/ventulus/ventulus.sock
ventulus --socket /tmp/ventulus.sock    # a daemon on another socket
```

Python 3.12 is the minimum; development happens on 3.14. Runtime and development
dependencies are declared in `pyproject.toml`, which also explains the two
deliberate bounds: `ruff` has an upper bound because a formatter's output changes
between versions, and `mutmut` needs 3.6 because 3.5.0 fails on Python 3.14.

## Checks

All four must pass before merging:

```bash
ruff format --check src/ tests/
ruff check src/ tests/
python -m compileall -q src/
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

**`QT_QPA_PLATFORM=offscreen` is required in every test command.** Tests build real
Qt widgets. Run the suite bare under a live Wayland or X session and three
`TestKeyboardFocusVisibility` tests fail, because the platform theme overrides the
stylesheet's `:focus` rules. Those failures come from the environment, but they
look exactly like a regression, so always set the variable; CI does. It also fixes
Qt platform-plugin errors on a machine with no display.

The whole set takes well under a minute. There is no faster subset to reach for.
`python -m pytest --collect-only -q` prints the current test count.

To run one file:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_profile_service.py -v
```

CI also enforces a branch-coverage floor of **88 %** (`fail_under` in
`pyproject.toml`). To check it before pushing:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest --cov --cov-branch --cov-report=term-missing
```

Tests use `pytest-qt`. Every test must be deterministic: no real hardware, no real
network calls, no timing that can flake.

## Code style

- **Formatter and linter:** ruff (`ruff format src/ tests/`, `ruff check --fix src/ tests/`).
- **Type hints** on public APIs; use `TYPE_CHECKING` imports to avoid circular imports.
- **Comments** only where the *why* is not obvious.

## Architecture rules

1. **No direct hardware access.** The GUI talks only to the daemon's API
   ([API contract](docs/08_API_Integration_Contract.md)).
2. **Truthful UI.** Never hide an error, and never show stale data as fresh.
3. **The daemon owns safety.** Thermal rules, fan floors and emergency overrides
   belong to the daemon.
4. **Every widget has a unique `objectName`**, so tests can find it.

GPU discovery, writes and naming follow the [GPU support rules](docs/25_GPU_Support_Rules.md).

## Project structure

```
src/ventulus/
├── api/            # Daemon HTTP client and typed models
├── knowledge/      # Static hardware knowledge: sensor descriptions, header labels, chip names (no Qt)
├── services/       # AppState, PollingService, ProfileService (the daemon owns control; there is no GUI control loop)
├── ui/
│   ├── pages/      # Dashboard, Controls, Overview, System State, Hardware, Logs, Settings, Theme
│   └── widgets/    # Reusable components (cards, charts, editors)
└── main.py         # Entry point and argument parsing
```

## Pull requests

- Keep each PR to one feature or fix.
- Include tests for new features, and a regression test for a bug fix.
- Add an entry to `CHANGELOG.md` under `[Unreleased]`.
- Update the relevant `docs/` or `manual/` page when behaviour changes.

## Reporting issues

File issues at https://github.com/Plan-B-Development/ventulus/issues. For a security
problem, follow [SECURITY.md](SECURITY.md) instead.
