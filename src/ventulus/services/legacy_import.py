"""One-time import of a Control-OFC 4.x user's files (the Ventulus rename, DEC-493).

Control-OFC kept settings, profiles and themes in ``$XDG_CONFIG_HOME/control-ofc``
and saved PWM Test Reports in ``$XDG_DATA_HOME/control-ofc``; Ventulus uses
``ventulus`` for both. At the first start after the upgrade each old directory is
copied to its new home, with the old directory names inside its JSON files
pointed at the new ones (directory overrides, a saved socket path).

The copy is all-or-nothing: it is built in a hidden staging directory beside the
target and renamed into place, so the new directory either holds the whole
import or does not exist. A new directory that already holds any file is the
user's own and is never imported into; the old directories are never changed.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from ventulus.paths import MAX_IMPORT_BYTES, config_dir, data_dir

log = logging.getLogger(__name__)

LEGACY_APP = "control-ofc"

# Fixed system paths the rename moved; the per-user directories are added per
# import because XDG variables decide where they are.
_SYSTEM_REWRITES = (
    ("/run/control-ofc/control-ofc.sock", "/run/ventulus/ventulus.sock"),
    ("/etc/control-ofc/", "/etc/ventulus/"),
)


def import_legacy_user_dirs() -> list[Path]:
    """Import both old directories; return the new directories that were filled.

    Must run before anything creates the new directories' files
    (``ensure_dirs`` creates only empty directories, which do not count).
    """
    imported = []
    for new in (config_dir(), data_dir()):
        old = new.with_name(LEGACY_APP)
        try:
            if import_dir(old, new):
                imported.append(new)
                log.info("Imported Control-OFC files from %s into %s", old, new)
        except OSError as e:
            log.warning("Could not import Control-OFC files from %s: %s", old, e)
    return imported


def import_dir(old: Path, new: Path) -> bool:
    """Copy *old* to *new* once; True if this call did it. See the module docs."""
    if not old.is_dir() or _holds_files(new):
        return False
    rewrites = ((str(old) + "/", str(new) + "/"), *_SYSTEM_REWRITES)
    new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{new.name}.import-", dir=new.parent))
    try:
        shutil.copytree(old, staging, symlinks=True, dirs_exist_ok=True)
        for json_file in staging.rglob("*.json"):
            _rewrite(json_file, rewrites)
        os.chmod(staging, 0o700)
        _remove_empty_tree(new)
        os.replace(staging, new)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return True


def _holds_files(directory: Path) -> bool:
    if not directory.exists():
        return False
    return any(not p.is_dir() for p in directory.rglob("*"))


def _remove_empty_tree(directory: Path) -> None:
    """Remove a tree of empty directories; ``rmdir`` refuses anything else."""
    if not directory.exists():
        return
    for sub in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        sub.rmdir()
    directory.rmdir()


def _rewrite(path: Path, rewrites: tuple[tuple[str, str], ...]) -> None:
    if path.is_symlink() or path.stat().st_size > MAX_IMPORT_BYTES:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    new_text = text
    for old, new in rewrites:
        new_text = new_text.replace(old, new)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
