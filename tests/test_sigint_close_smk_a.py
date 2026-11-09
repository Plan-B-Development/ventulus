"""SMK-a: Ctrl-C (SIGINT) closes the window from the event loop, never mid-paint.

Python runs a signal handler at whatever bytecode the main thread reaches next.
With the GUI drawing, that is often inside a Python ``paint()`` that Qt's C++
paint code called (a pyqtgraph axis while the timeline chart repaints). The old
handler called ``window.close()`` right there, so the chart's teardown cleared
the scene ``QGraphicsView::paintEvent`` was still walking, and the installed GUI
segfaulted on Ctrl-C (CI package smoke, "connects to the released daemon").
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from ventulus.main import install_sigint_close

_SRC = Path(__file__).resolve().parents[1] / "src"


class _ClosingWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.close_events = 0

    def closeEvent(self, event) -> None:
        self.close_events += 1
        super().closeEvent(event)


@pytest.fixture
def restore_sigint():
    saved = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, saved)


def test_sigint_defers_the_close_to_the_event_loop(qtbot, restore_sigint):
    """The handler schedules the close; the close event (DEC-257's saves) still
    arrives once control is back in the event loop."""
    window = _ClosingWindow()
    qtbot.addWidget(window)
    window.show()
    install_sigint_close(window)
    # Without a handler of ours, the default one would raise KeyboardInterrupt
    # and end the whole pytest session instead of failing this test.
    assert signal.getsignal(signal.SIGINT) is not signal.default_int_handler

    signal.raise_signal(signal.SIGINT)  # the Python handler runs before this returns

    assert window.close_events == 0, "SIGINT closed the window from inside the handler"
    qtbot.waitUntil(lambda: window.close_events == 1, timeout=2000)


# Runs in a child process: with the defect present, this crashes the interpreter.
_IN_PAINT_SCRIPT = textwrap.dedent(
    """
    import signal
    import faulthandler
    faulthandler.enable()

    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication

    app = QApplication([])

    from ventulus.main import install_sigint_close
    from ventulus.services.history_store import HistoryStore
    from ventulus.ui.widgets.timeline_chart import TimelineChart

    chart = TimelineChart(HistoryStore())
    chart.resize(600, 300)
    chart.show()
    app.processEvents()
    install_sigint_close(chart)

    fired = []
    original_paint = pg.AxisItem.paint

    def paint(self, *args):
        if not fired:
            fired.append(True)
            signal.raise_signal(signal.SIGINT)  # Ctrl-C lands mid-paint
        return original_paint(self, *args)

    pg.AxisItem.paint = paint
    chart._plot_widget.repaint()
    for _ in range(20):
        app.processEvents()
    print(f"fired={bool(fired)} cleaned_up={getattr(chart, '_cleaned_up', False)}")
    """
)


def test_sigint_during_a_chart_paint_closes_cleanly(tmp_path):
    """The field crash, in miniature: SIGINT arrives while a pyqtgraph item of
    the timeline chart is painting. The process must survive and the chart's
    teardown must still run (it runs from ``TimelineChart.closeEvent``)."""
    script = tmp_path / "in_paint.py"
    script.write_text(_IN_PAINT_SCRIPT)
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        PYTHONPATH=os.pathsep.join(filter(None, [str(_SRC), os.environ.get("PYTHONPATH")])),
    )
    proc = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"exit {proc.returncode} (negative = killed by that signal)\n{proc.stderr[-3000:]}"
    )
    assert "fired=True" in proc.stdout, "SIGINT was never raised inside a paint"
    assert "cleaned_up=True" in proc.stdout, "the deferred close never ran"
    # A raising close path keeps the process alive but is what the package smoke
    # fails on ("Traceback" / "Uncaught exception" in the log).
    assert "Traceback" not in proc.stderr, proc.stderr[-3000:]
