"""Run a one-shot dialog or menu, then dispose of it.

A dialog or menu built with a parent and run with ``exec()`` belongs to that
parent, and Qt deletes it only when the parent goes. A page lives for the whole
session, so every open left another hidden copy behind (GUI audit 2026-10-14,
batch F). A copy still connected to a long-lived signal kept working after it
closed: each leaked Alert Centre rebuilt its cards on every ``warnings_changed``.

Every ``exec()`` under ``ui/`` goes through these two helpers, which
``tests/test_lifecycle_sweep_batch_f.py`` enforces.

``deleteLater``, not ``WA_DeleteOnClose``: callers read the outcome (the chosen
role, the clicked button, a checkbox) after ``exec()`` returns. Qt runs a
deferred delete only when control returns to the event loop it was posted from,
and a later nested modal does not run it, so the object stays valid for the
rest of the calling function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QDialog, QMenu


def exec_dialog(dialog: QDialog) -> int:
    """Run *dialog* modally and schedule its deletion; return ``exec()``'s result."""
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()


def exec_menu(menu: QMenu, pos: QPoint) -> QAction | None:
    """Pop *menu* at *pos* and schedule its deletion; return the chosen action.

    An action's ``triggered`` slots run inside ``exec()``, before the delete.
    """
    try:
        return menu.exec(pos)
    finally:
        menu.deleteLater()
