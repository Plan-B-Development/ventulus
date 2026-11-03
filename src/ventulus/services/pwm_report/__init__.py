"""The PWM Test Report (DEC-404): an assessment over the daemon's own
diagnostics, run by ``ventulus-diag report`` since DEC-503.

Everything in this package is Qt-free, so the rules that decide what a report
may claim are testable without a widget, and the CLI (``diag/report.py``) is a
thin shell over these modules.

Kept deliberately import-free: ``app_settings_service`` imports
:mod:`.setup_facts`, and a package ``__init__`` that pulled in the runner or the
models would drag them into the settings layer.
"""
