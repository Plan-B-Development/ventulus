"""A widget passed to ``qtbot.addWidget`` lives until teardown, then goes.

``tests/conftest.py::_flush_deferred_deletes`` holds every registered widget
from registration until its teardown flush. Without that, pytest-qt's weakref was
the only thing a parentless widget had once the test dropped it, so the cyclic GC
could free it in the middle of Qt's event handling for that same widget. On
Fedora 44's PySide6 packages that freed a ``TimelineChart`` during its own
layout pass and segfaulted (DEC-499).

The fixture is autouse and invisible, so this pins both halves: the hold (a
dropped, collected widget is still alive) and its end (it does not leak into the
next test, the DEC-287 concern with holding widgets).

**The last two tests are order-dependent by construction**, like
``test_widget_leak_reaping_dec287.py``: "destroyed before the next test" cannot
be observed from inside one. pytest keeps definition order within a file and no
ordering plugin is installed. Keep them adjacent and in this order.
"""

from __future__ import annotations

import gc
import weakref

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QFrame

_MARKER = "RegisteredLifetime_Probe"

#: A weakref only: a strong reference here would keep the wrapper alive and the
#: second test could not tell a destroyed widget from a held one.
_probe: list[weakref.ref] = []


def _live_probes() -> list[QFrame]:
    return [w for w in QApplication.topLevelWidgets() if w.objectName() == _MARKER]


@pytest.mark.parametrize("register", ["addWidget", "add_widget"])
def test_a_dropped_registered_widget_survives_the_cyclic_gc(qtbot, register):
    widget = QFrame()
    getattr(qtbot, register)(widget)
    ref = weakref.ref(widget)

    del widget
    gc.collect()

    held = ref()
    assert held is not None, "the widget was freed before its test's teardown"
    assert shiboken6.isValid(held)


def test_a_registered_widget_the_test_destroys_tears_down_cleanly(qtbot):
    """The hold must not hand pytest-qt a dead wrapper: its teardown calls
    ``close()`` on every registered widget it still reaches, which raises
    "already deleted" and fails this test's teardown and the next test's setup."""
    destroyed = QFrame()
    qtbot.addWidget(destroyed)
    qtbot.addWidget(QFrame())

    shiboken6.delete(destroyed)

    assert not shiboken6.isValid(destroyed)


def test_a_registered_widget_is_held_through_its_test(qtbot):
    widget = QFrame()
    widget.setObjectName(_MARKER)
    qtbot.addWidget(widget)
    _probe.append(weakref.ref(widget))

    del widget
    gc.collect()

    assert len(_live_probes()) == 1, "precondition: the probe is alive in its own test"


def test_the_held_widget_is_destroyed_before_the_next_test(qapp):
    assert _probe, "precondition: the previous test ran and registered its probe"
    gc.collect()

    assert _live_probes() == [], "the held widget leaked past its test"
    assert _probe[0]() is None, "the hold outlived the test that registered it"
