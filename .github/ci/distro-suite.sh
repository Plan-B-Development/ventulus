#!/bin/bash
# The GUI test suite on one distribution's own Python, Qt and numpy packages,
# with nothing from PyPI (DEC-499). ci.yml's `distro` job runs it inside the
# distribution's container image, as root:
#
#   distro-suite.sh deps   install the distribution's packages, create an
#                          unprivileged user, and install this checkout's
#                          metadata into a venv that sees the system packages
#   distro-suite.sh test   run the suite as that user
#
# The metadata install matters: without an installed `.dist-info` the GUI's
# version is "dev", which switches its version-floor checks off, and their tests
# fail. The venv holds only that metadata (an editable install with --no-deps
# --no-index); every import resolves to the distribution's packages.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
venv=/opt/ventulus-venv
user=ventulus-ci

deps() {
    # shellcheck source=/dev/null
    . /etc/os-release
    case " $ID ${ID_LIKE:-} " in
        *" debian "* | *" ubuntu "*)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -q
            # python3-pyside6.qtopengl/.qtopenglwidgets: pyqtgraph imports
            # QtOpenGL. qt6-svg-plugins: without it the app icon is null.
            apt-get install -y -q --no-install-recommends \
                python3 python3-venv python3-setuptools \
                python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
                python3-pyside6.qtnetwork python3-pyside6.qttest python3-pyside6.qtsvg \
                python3-pyside6.qtopengl python3-pyside6.qtopenglwidgets qt6-svg-plugins \
                python3-pyqtgraph python3-numpy python3-httpx python3-colorama \
                python3-pytest python3-pytestqt python3-pytest-timeout python3-yaml \
                libegl1 libgl1 libxkbcommon0 fonts-dejavu-core fish zsh
            ;;
        *" fedora "*)
            dnf -y -q install --setopt=install_weak_deps=False \
                python3 python3-setuptools python3-pyside6 \
                python3-pyqtgraph python3-numpy python3-httpx python3-colorama \
                python3-pytest python3-pytest-qt python3-pytest-timeout python3-pyyaml \
                mesa-libEGL mesa-libGL libxkbcommon dejavu-sans-fonts fish zsh
            ;;
        *)
            echo "distro-suite.sh: no package list for $ID" >&2
            exit 1
            ;;
    esac

    python3 -m venv --system-site-packages "$venv"
    "$venv/bin/python" -m pip install -q --no-deps --no-index --no-build-isolation -e "$repo"
    id "$user" >/dev/null 2>&1 || useradd -m "$user"
    chown -R "$user:" "$repo"
}

test_suite() {
    # Fail here, not in two scattered version-floor tests, if the metadata is
    # missing or anything was imported from outside the distribution's tree.
    "$venv/bin/python" - "$repo" <<'EOF'
import importlib.metadata
import sys
import tomllib
from pathlib import Path

import numpy
import pyqtgraph
import PySide6
from PySide6 import QtCore

repo = Path(sys.argv[1])
want = tomllib.loads((repo / "pyproject.toml").read_text())["project"]["version"]
have = importlib.metadata.version("ventulus")
assert have == want, f"installed ventulus metadata says {have}, pyproject.toml says {want}"
for mod in (PySide6, pyqtgraph, numpy):
    assert not mod.__file__.startswith(sys.prefix + "/"), f"{mod.__name__} came from the venv"
print(
    f"Python {sys.version.split()[0]}, PySide6 {PySide6.__version__} (Qt {QtCore.qVersion()}), "
    f"pyqtgraph {pyqtgraph.__version__}, numpy {numpy.__version__}, ventulus {have}"
)
EOF
    su -s /bin/bash "$user" -c "cd '$repo' && QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
        '$venv/bin/python' -m pytest tests -q -p no:cacheprovider --tb=short -rfE"
}

case "${1:-}" in
    deps) deps ;;
    test) test_suite ;;
    *)
        echo "usage: $0 deps|test" >&2
        exit 2
        ;;
esac
