"""Terminal I/O, exit codes and interrupt handling for ``ventulus-diag``."""

from __future__ import annotations

import contextlib
import signal
import sys
from dataclasses import dataclass
from typing import TextIO

# ── Exit codes (documented in man/ventulus-diag.1.scd) ────────────────────────
EXIT_OK = 0
#: The test ran and the daemon reported it failed, or something unexpected went
#: wrong in this tool (a report could not be saved).
EXIT_FAILED = 1
#: Command-line usage error (argparse's own code).
EXIT_USAGE = 2
#: The daemon could not be reached.
EXIT_UNAVAILABLE = 3
#: The daemon is too old for this command, or does not offer the test.
EXIT_INCOMPATIBLE = 4
#: Nothing was run: not confirmed, refused by the daemon or its preflight,
#: another test running, thermal protection active, or an invalid target.
EXIT_REFUSED = 5
#: You cancelled the test; the daemon ended it and put the header back.
EXIT_CANCELLED = 6
#: A safety rule ended the test (thermal protection, the diagnostic limit,
#: stale readings, a header that became a pump).
EXIT_ABORTED = 7
#: The daemon stopped answering during the test; it restores the header itself.
EXIT_INTERRUPTED = 8
#: A second interrupt: this tool stopped at once without waiting for the end.
EXIT_STOPPED = 130


class DiagError(Exception):
    """A failure with an exit code and a message for the user."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Console:
    """stdout/stderr/stdin, swappable for tests. Output never raises: a closed
    terminal (SIGHUP) must not turn a cancel into a traceback."""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        interactive: bool | None = None,
    ) -> None:
        self._in = stdin or sys.stdin
        self._out = stdout or sys.stdout
        self._err = stderr or sys.stderr
        self._interactive = interactive

    @property
    def interactive(self) -> bool:
        """Both ends are a terminal: someone is there to answer a prompt."""
        if self._interactive is not None:
            return self._interactive
        try:
            return self._in.isatty() and self._out.isatty()
        except (AttributeError, ValueError, OSError):
            return False

    def out(self, text: str = "") -> None:
        self._write(self._out, text)

    def err(self, text: str) -> None:
        self._write(self._err, text)

    @staticmethod
    def _write(stream: TextIO, text: str) -> None:
        try:
            stream.write(text + "\n")
            stream.flush()
        except (OSError, ValueError):
            pass

    def ask(self, prompt: str) -> str | None:
        """One line from the user, or ``None`` at end of input."""
        try:
            self._out.write(prompt)
            self._out.flush()
            line = self._in.readline()
        except (OSError, ValueError):
            return None
        return line.rstrip("\n") if line else None


@dataclass
class Interrupts:
    """Counts SIGINT, SIGTERM and SIGHUP while a test runs.

    The first asks the running test to stop (the daemon's own cancel); a second
    stops this tool at once. Either way the daemon restores the header itself,
    so neither leaves a fan where the test put it. Installed only around a run:
    before it, Ctrl-C simply exits.
    """

    count: int = 0
    last: int | None = None

    SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

    def __post_init__(self) -> None:
        self._previous: dict[int, object] = {}

    def handle(self, signum: int, _frame: object = None) -> None:
        self.count += 1
        self.last = signum

    def __enter__(self) -> Interrupts:
        for sig in self.SIGNALS:
            # Not the main thread, or not supported here: leave it uncounted.
            with contextlib.suppress(ValueError, OSError):
                self._previous[sig] = signal.signal(sig, self.handle)
        return self

    def __exit__(self, *_exc: object) -> None:
        for sig, previous in self._previous.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, previous)  # type: ignore[arg-type]
        self._previous.clear()

    def name(self) -> str:
        if self.last is None:
            return "an interrupt"
        try:
            return signal.Signals(self.last).name
        except ValueError:
            return f"signal {self.last}"
