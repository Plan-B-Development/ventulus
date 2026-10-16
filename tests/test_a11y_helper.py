"""``ui/components/a11y.name_value_control`` — the shared naming rule (273-g).

Every assertion here reads the **announced** name through ``QAccessible``, never
``accessibleName()``. That distinction is the whole point of the helper: on a
non-editable ``QComboBox`` Qt's Unix ``QAccessibleComboBox::text(Name)`` falls
through to the current item and discards the property, so a property assertion
passes on a combo that announces nothing useful. It shipped as one once
(DEC-271), and the first version of this very helper had the same bug — a string
-named combo announced nothing until the buddy fallback was added.
"""

from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ventulus.ui.components.a11y import accessible_proxy, name_value_control
from ventulus.ui.components.toggle_switch import ToggleSwitch


def announced(widget) -> str:
    """What assistive tech would use to say what *widget* is, on every supported Qt.

    A Name distinct from the Value is a real name; otherwise fall back to the
    ``Label`` relation a ``setBuddy`` publishes, which is what AT-SPI exports as
    *labelled-by* and what Orca reads for a combo box.

    Only a relation Qt before 6.11 also reports counts: a label among the
    widget's siblings, or its titled group box. Qt 6.11 reports a buddy label
    wherever it sits, so on 6.11 an unfiltered read passes for a label Debian 13
    (Qt 6.8) and Ubuntu 26.04 (Qt 6.10) never announce.
    """
    iface = QAccessible.queryAccessibleInterface(widget)
    if iface is None:
        return ""
    name = iface.text(QAccessible.Text.Name)
    value = iface.text(QAccessible.Text.Value)
    if name and name != value:
        return name
    parent = widget.parentWidget()
    for target, flags in iface.relations():
        if not flags & QAccessible.RelationFlag.Label:
            continue
        source = target.object()
        if source is parent or (parent is not None and source.parent() is parent):
            return target.text(QAccessible.Text.Name)
    return ""


@pytest.fixture
def host(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    return w


def test_a_visible_label_becomes_the_announced_name(host):
    combo = QComboBox(host)
    combo.addItem("Default Dark")
    label = QLabel("Theme:", host)

    name_value_control(combo, label)

    # The buddy path announces the LABEL's own visible text, colon and all —
    # rewriting a label the user can see would be a worse trade than a spoken
    # colon, so the helper's strip deliberately reaches only the property.
    assert announced(combo) == "Theme:"
    assert label.buddy() is combo, "the buddy is the half Orca actually reads"


def test_a_string_label_still_announces_without_a_visible_label(host):
    """The regression the app-wide sweep caught while 273-g was being written.

    ``setAccessibleName`` alone is silently discarded on a non-editable combo, so
    a control with no visible label to buddy announced nothing at all. A hidden
    proxy label kept beside the control fixes it — measured to announce
    identically to a visible buddy (``TestProxyPlacementBeforeQt611``).
    """
    combo = QComboBox(host)
    combo.addItem("Default Dark")
    combo.setObjectName("Test_Combo_theme")

    name_value_control(combo, "Theme")

    assert announced(combo) == "Theme", (
        "a combo named only by property announces its current item — the "
        "property is discarded by Qt on Unix"
    )


def test_the_property_alone_would_not_have_been_enough(host):
    """Pins the premise the helper exists for, so it cannot be quietly 'simplified'.

    If this ever passes, Qt's behaviour changed and the buddy half could in
    principle be dropped — but only then, and deliberately.
    """
    combo = QComboBox(host)
    combo.addItem("Default Dark")
    combo.setAccessibleName("Theme")

    assert announced(combo) == "", (
        "setAccessibleName alone now works on a combo — re-evaluate the two-call "
        "rule in components/a11y.py and docs/03 before relying on it"
    )


def test_a_trailing_colon_is_stripped(host):
    spin = QSpinBox(host)
    label = QLabel("Poll interval:", host)

    name_value_control(spin, label)

    assert announced(spin) == "Poll interval", '"Poll interval colon" is not an improvement'


def test_two_string_named_controls_do_not_collide(host):
    """The proxy label needs a unique objectName like every other widget.

    A fixed fallback string collided the moment a second control took this path,
    which is exactly what happened during the sweep.
    """
    first = QLineEdit(host)
    first.setObjectName("Test_Edit_first")
    second = QLineEdit(host)
    second.setObjectName("Test_Edit_second")

    name_value_control(first, "Search sensors")
    name_value_control(second, "Filter messages")

    proxies = {
        lbl.objectName()
        for lbl in host.findChildren(QLabel)
        if lbl.objectName().endswith("_A11yLabel")
    }
    assert len(proxies) == 2, f"proxy objectNames collided: {proxies}"
    assert announced(first) == "Search sensors"
    assert announced(second) == "Filter messages"


def test_a_control_named_before_its_objectname_still_gets_a_distinct_proxy(host):
    """Call order must not matter.

    The helper runs at construction and a caller may set the objectName on the
    next line. Deriving the proxy name from the label text when the control has
    none is what keeps that from producing a generic, collision-prone name — the
    bug this caught on the sensor-series search box.
    """
    edit = QLineEdit(host)  # deliberately no objectName yet

    name_value_control(edit, "Search sensors")
    edit.setObjectName("Test_Edit_late")

    proxy = next(
        lbl for lbl in host.findChildren(QLabel) if lbl.objectName().endswith("_A11yLabel")
    )
    assert proxy.objectName() == "Search_sensors_A11yLabel"
    assert announced(edit) == "Search sensors"


def test_a_toggle_switch_routes_to_its_own_label_setter(host):
    toggle = ToggleSwitch(host)
    label = QLabel("Start minimised:", host)

    name_value_control(toggle, label)

    assert "Start minimised" in announced(toggle)


def test_an_empty_label_is_a_no_op(host):
    combo = QComboBox(host)
    combo.addItem("Default Dark")

    name_value_control(combo, "   ")

    assert not host.findChildren(QLabel), "no proxy should be created for an empty name"
    assert combo.accessibleName() == ""


def test_a_widget_that_is_not_a_value_control_is_left_alone(host):
    """A progress bar shows a value nobody sets, so naming it is not this
    helper's job — and giving it a name Qt would ignore is worse than none."""
    bar = QProgressBar(host)

    name_value_control(bar, "Progress")

    assert bar.accessibleName() == ""
    assert not host.findChildren(QLabel)


def test_naming_the_same_control_twice_does_not_duplicate_the_proxy(host):
    """The docstring promises idempotence; the string path did not deliver it.

    A second call minted another QLabel with an IDENTICAL objectName, breaking
    the unique-objectName rule and any `findChild` on that name. No call site
    does this today — which is precisely why it needed a test rather than trust.
    """
    edit = QLineEdit(host)
    edit.setObjectName("Test_Edit_search")

    name_value_control(edit, "Search sensors")
    name_value_control(edit, "Search sensors")

    proxies = [lbl for lbl in host.findChildren(QLabel) if lbl.objectName().endswith("_A11yLabel")]
    assert len(proxies) == 1, (
        f"a second call duplicated the proxy: {[p.objectName() for p in proxies]}"
    )
    assert announced(edit) == "Search sensors"


def test_renaming_a_control_updates_the_existing_proxy(host):
    """Reuse must re-label, not silently keep the first name."""
    combo = QComboBox(host)
    combo.addItem("Default Dark")
    combo.setObjectName("Test_Combo_x")

    name_value_control(combo, "Theme")
    name_value_control(combo, "Colour scheme")

    assert announced(combo) == "Colour scheme"


class TestProxyPlacementBeforeQt611:
    """The hidden label sits beside its control, wherever the control goes.

    Qt before 6.11 finds a buddy label only among the control's siblings
    (``QAccessibleWidget::relations``), so a proxy parented to the control itself
    announced nothing on Debian 13 (Qt 6.8) and Ubuntu 26.04 (Qt 6.10) while
    passing on 6.11. ``announced`` applies the older rule on every version.
    """

    @staticmethod
    def _combo(parent=None) -> QComboBox:
        combo = QComboBox(parent)
        combo.addItem("Default Dark")
        return combo

    def test_a_combo_named_before_it_joins_a_layout_is_announced(self, host):
        combo = self._combo()
        name_value_control(combo, "Theme")
        QVBoxLayout(host).addWidget(combo)

        assert combo.parentWidget() is host, "precondition: addWidget reparented the combo"
        assert announced(combo) == "Theme"

    def test_the_label_follows_a_control_to_another_parent(self, host, qtbot):
        other = QWidget()
        qtbot.addWidget(other)
        combo = self._combo(host)
        name_value_control(combo, "Theme")

        combo.setParent(other)

        assert announced(combo) == "Theme"
        assert not [lbl for lbl in host.findChildren(QLabel) if lbl.buddy() is combo], (
            "the label was left behind in the old parent"
        )

    def test_a_control_without_a_parent_keeps_its_label_inside(self, qtbot):
        combo = self._combo()
        qtbot.addWidget(combo)

        name_value_control(combo, "Theme")

        proxy = accessible_proxy(combo)
        assert proxy is not None and proxy.parentWidget() is combo, "an orphaned label leaks"

    def test_the_label_is_never_shown(self, host):
        combo = self._combo(host)
        name_value_control(combo, "Theme")
        proxy = accessible_proxy(combo)
        assert proxy is not None and proxy.parentWidget() is host

        host.show()

        assert not proxy.isVisibleTo(host)

    def test_the_label_is_deleted_with_its_control(self, host):
        combo = self._combo(host)
        name_value_control(combo, "Theme")
        proxy = accessible_proxy(combo)
        assert proxy is not None and proxy.parentWidget() is host

        combo.deleteLater()
        # Two passes: the control's deletion posts the label's.
        for _ in range(2):
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        assert not shiboken6.isValid(combo), "precondition: the control is gone"
        assert not shiboken6.isValid(proxy), "the label outlived its control"

    def test_a_label_never_becomes_a_splitter_pane(self, host):
        # QSplitter adopts every child widget as a pane; a hidden one would shift
        # sizes() and the saved splitter state.
        splitter = QSplitter(host)
        edit = QPlainTextEdit(splitter)
        assert splitter.count() == 1, "precondition: the edit is the splitter's one pane"

        name_value_control(edit, "Full message")

        assert splitter.count() == 1
        proxy = accessible_proxy(edit)
        assert proxy is not None and proxy.parentWidget() is edit

    def test_a_focused_control_can_be_deleted(self, host):
        """Deleting a focused control delivers FocusOut to the Python event filter
        while the control is being destroyed; that must not crash."""
        combo = self._combo(host)
        name_value_control(combo, "Theme")
        host.show()
        combo.setFocus()
        proxy = accessible_proxy(combo)
        assert proxy is not None

        combo.deleteLater()
        for _ in range(2):
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        assert not shiboken6.isValid(combo)
        assert not shiboken6.isValid(proxy)


class TestProxyReuseAcrossDifferentText:
    """277-l: idempotence must hold when the TEXT changes, not just the call.

    `name_value_control` looked an existing proxy up by its *derived* name, so a
    second call with different text missed the reuse and minted a rival hidden
    label. The control then carried two `RelationFlag.Label` relations and
    whichever Qt enumerated first won the announcement.

    Both pre-existing idempotence tests set an objectName on the control first,
    which makes `_proxy_name` stable and hides the bug — so the case the string
    fallback exists to serve (a control with no objectName) was the untested one.
    """

    def test_renaming_a_control_does_not_mint_a_second_proxy(self, qtbot):
        from PySide6.QtWidgets import QLabel, QLineEdit

        from ventulus.ui.components.a11y import name_value_control

        edit = QLineEdit()  # deliberately NO objectName — the untested path
        qtbot.addWidget(edit)

        name_value_control(edit, "First name")
        name_value_control(edit, "Second name")

        proxies = [c for c in edit.findChildren(QLabel) if c.objectName().endswith("_A11yLabel")]
        assert len(proxies) == 1, (
            f"a rename must reuse the existing proxy, not add another — found "
            f"{[p.objectName() for p in proxies]}. Two labels means two "
            f"labelled-by relations and a coin-toss announcement."
        )
        assert proxies[0].text() == "Second name"
        assert proxies[0].buddy() is edit

    def test_the_surviving_proxy_is_findable_by_its_derived_name(self, qtbot):
        """The objectName must track the text it was re-derived from.

        Leaving it stale would break `findChild` on the very name the helper
        computes, which is how the reuse lookup itself works.
        """
        from PySide6.QtWidgets import QLabel, QLineEdit

        from ventulus.ui.components.a11y import _proxy_name, name_value_control

        edit = QLineEdit()
        qtbot.addWidget(edit)
        name_value_control(edit, "First name")
        name_value_control(edit, "Second name")

        assert edit.findChild(QLabel, _proxy_name(edit, "Second name")) is not None
