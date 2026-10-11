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

## Wire models and shared fixtures

The GUI parses every daemon response into typed models in `src/ventulus/api/models.py`. The
[API contract](docs/08_API_Integration_Contract.md) describes the wire they mirror.

- **One wire struct gets one model class.** Where the daemon reuses a struct across
  endpoints, the GUI aliases it rather than mirroring it: `pwm_controls[]` on
  `GET /inventory/hwmon` is `Vec<PwmHeaderEntry>`, literally the `GET /hwmon/headers`
  element, so `InventoryPwmControl` *is* `HwmonHeader`, not a copy of it. Where the daemon
  flattens one struct into another (`#[serde(flatten)]`), the GUI subclasses:
  `InventoryTempSensor` extends `SensorReading`. A second class that claims to mirror the
  first drifts; that is how eight cooling-device fields, an enforced duty floor among them,
  once went missing while a docstring asserted a field-for-field match.
- **One declaration pins the surface on both sides.** `tests/fixtures/wire_fields.json`
  declares, per daemon `Serialize` struct, the keys it emits and the model that must carry
  them. The daemon's `wire_field_surface_is_pinned` test (`daemon/src/api/responses.rs`)
  reads that file and checks the daemon's serialised keys against it.
  `tests/test_wire_field_coverage.py` checks that each declared key has a model slot and a
  real read site outside `api/models.py`.
- **The read check is exhaustive.** Every declared field must be classified, and a new one
  fails the GUI suite until it is:
  - `must_be_read`: a production read site must exist.
  - `inert`: nothing reads it, with the reason. This is checked the other way round as well,
    so a field that gains a consumer must be reclassified instead of keeping a stale
    exemption.
  - `not_assertable`: the name is too common for a name-based check to prove anything
    (`id`, `label`, `source`).
  - `unmodelled`: the GUI has no slot for it, with the reason.
  - `via_capability_registry`, for `ControlCapability` only: read through `daemon_supports`
    by a feature id that `DAEMON_FEATURE_CAPABILITY_FLAGS` maps to the flag. The test requires
    a gate on that id (a `daemon_supports` argument, a `feature_id=` keyword or an
    `_apply_live_key_support` argument), and requires an `inert` registry flag to have none.

  A read is an attribute access, a keyword, a binding, or a string in **argument** position
  (`getattr(o, "f", d)`, `d.get("f")`, `d["f"]`). A string used as a dict-literal key declares
  a table entry and is not a read.
- **Adding a field to a pinned struct** means updating the fixture, in both repositories, and
  the API contract. Adding a *struct* also needs an arm in the Rust test. The fixture and the
  arms are checked to cover the same set in both directions, so forgetting either half fails.
  The fixture's `structs` table lists what is covered: the structs behind `/sensors`, `/fans`,
  `/poll` (its status half included), `/hwmon/headers`, `/inventory/hwmon`,
  `/inventory/cooling-devices`, `/capabilities` (`Limits`, `FeatureFlags`,
  `ControlCapability`) and `/diagnostics/hardware` (`VoltageEntry`, `ThermalSafetyInfo`),
  the diagnostic surfaces (preflight, control-path discovery, PWM characterisation, steady
  state, the startup fingerprint) and the OpenFAN maintenance surfaces. `ControlCapability`
  also pins capability flag names across the repositories: every flag in
  `DAEMON_FEATURE_CAPABILITY_FLAGS` must be one of its fields. Coverage is partial by design:
  a struct the fixture does not list is unchecked rather than failing.
- **`daemon_config_keys.json`** applies the same one-declaration rule to the keys of
  `GET /config` ([API contract § Config management](docs/08_API_Integration_Contract.md#config-management)).

Seven fixtures in `tests/fixtures/` have a byte-identical copy in the daemon repository:
`parity_vectors.json`, `role_classification.json`, `header_role_classification.json`,
`wire_fields.json`, `daemon_config_keys.json`, `chip_name_canonical.json` and
`memory_sensor_ids.json`. Tests compare the copies when both repositories are checked out
side by side, and `.github/workflows/parity.yml` compares them in CI. Change both copies in
the same window.

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
