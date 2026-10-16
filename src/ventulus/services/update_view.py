"""What the update check's surfaces say (DEC-499): Settings ▸ Updates, the window
notice and the About dialog. Qt-free; the widgets only place these strings."""

from __future__ import annotations

import datetime

from ventulus.services.install_ownership import InstallMethod
from ventulus.services.update_check import (
    ComponentStatus,
    Outcome,
    UpdateReport,
    VersionState,
)

_NAMES = {"ventulus": "Ventulus", "ventulusd": "ventulusd"}

_METHOD = {
    InstallMethod.PACMAN: "installed with pacman",
    InstallMethod.DEB: "installed from a .deb package",
    InstallMethod.RPM: "installed from an .rpm package",
    InstallMethod.TARBALL: "installed from the tarball",
    InstallMethod.SOURCE: "built from source",
    InstallMethod.UNKNOWN: "installed in a way that could not be determined",
}

#: Shown before any check this session.
NEVER_CHECKED = "Not checked yet. Nothing is sent until you check."
CHECKING = "Checking for updates…"


def display_name(project: str) -> str:
    return _NAMES.get(project, project)


def format_when(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def status_line(report: UpdateReport | None, *, checking: bool = False) -> str:
    """One line for the top of the Updates card."""
    if checking:
        return CHECKING
    if report is None:
        return NEVER_CHECKED
    when = format_when(report.checked_at)
    if report.outcome is not Outcome.CHECKED:
        return f"Checked {when}: no result. {report.error}"
    if report.update_available:
        return f"Checked {when}: an update is available."
    return f"Checked {when}: no update available."


def published_line(report: UpdateReport | None) -> str:
    if report is None or report.published_at is None:
        return ""
    return f"Release information published {format_when(report.published_at)}."


def component_line(status: ComponentStatus) -> str:
    """'Ventulus 5.1.0, installed with pacman: 5.2.0 is available.'"""
    name = display_name(status.project)
    have = f"{name} {status.installed}" if status.installed else name
    how = _METHOD[status.method]
    if status.state is VersionState.UPDATE_AVAILABLE:
        verdict = f"{status.latest} is available."
    elif status.state is VersionState.UP_TO_DATE:
        verdict = "up to date."
    elif status.state is VersionState.AHEAD:
        verdict = f"ahead of the latest release ({status.latest})."
    else:
        verdict = f"the latest release is {status.latest}."
    return f"{have}, {how}: {verdict}"


def detail_lines(report: UpdateReport | None) -> list[str]:
    """Everything under the status line: per component, then compatibility."""
    if report is None or report.outcome is not Outcome.CHECKED:
        return []
    lines: list[str] = []
    for status in report.components:
        lines.append(component_line(status))
        lines.extend(f"    {note}" for note in status.notes)
        lines.extend(f"    {step}" for step in status.handoff)
    lines.extend(report.compatibility)
    published = published_line(report)
    if published:
        lines.append(published)
    return lines


def notice_text(report: UpdateReport) -> str:
    """The dismissible window notice; empty when there is nothing to offer."""
    offered = [
        f"{display_name(c.project)} {c.latest}"
        for c in report.components
        if c.state is VersionState.UPDATE_AVAILABLE
    ]
    if report.outcome is not Outcome.CHECKED or not offered:
        return ""
    return f"Update available: {' and '.join(offered)}. See Settings ▸ Updates."


def download_button_text(status: ComponentStatus) -> str:
    return f"Download and verify {display_name(status.project)} {status.latest}"


def about_versions(gui_version: str, daemon_version: str | None) -> list[str]:
    daemon = daemon_version or "not connected"
    return [f"Ventulus {gui_version}", f"ventulusd {daemon}"]
