#!/bin/bash
# install.sh: install the Ventulus GUI from this tarball under /usr/local, or
# upgrade an earlier tarball install (DEC-499).
#
#   sudo ./install.sh     install or upgrade
#   ./install.sh --deps   print the command that installs what it needs
#
# The GUI runs on this system's own Python, Qt and numpy, which come from the
# distribution's packages: install.sh checks them first and installs nothing
# when one is missing. It refuses when a package manager owns ventulus; use that
# package manager instead. Files an earlier version installed and this one no
# longer ships are removed. A running Ventulus keeps the old version until it
# is restarted. It needs ventulusd, which is installed separately.
#
# Uninstall with: sudo /usr/local/lib/ventulus/uninstall
set -euo pipefail

die() {
    echo "install.sh: $*" >&2
    exit 1
}

here=$(cd "$(dirname "$0")" && pwd)
libdir=/usr/local/lib/ventulus
manifest=$libdir/tarball-manifest

# What the distribution must provide. debian/control and the Fedora package
# need the same; tests/test_packaging_linux.py holds the Debian list equal to
# debian/control's Depends, and CI installs from both before the smoke test.
deb_deps="python3 python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets
python3-pyside6.qtnetwork python3-pyside6.qtopengl python3-pyside6.qtopenglwidgets
qt6-svg-plugins python3-pyqtgraph python3-numpy python3-httpx python3-colorama gpg
hicolor-icon-theme"
rpm_deps="python3 python3-pyside6 python3-pyqtgraph python3-numpy python3-httpx
python3-colorama gnupg2 hicolor-icon-theme"

deps_command() {
    local id=
    # shellcheck source=/dev/null
    [ -r /etc/os-release ] && id=$(. /etc/os-release && echo " ${ID:-} ${ID_LIKE:-} ")
    # The lists are split into words on purpose: one command line.
    # shellcheck disable=SC2086
    case "$id" in
        *" debian "* | *" ubuntu "*) echo "sudo apt install" $deb_deps ;;
        *" fedora "*) echo "sudo dnf install" $rpm_deps ;;
        *) echo "Install Python 3.12 or newer and, from your distribution, PySide6, pyqtgraph," \
            "numpy, httpx, colorama, Qt's SVG image plugin, gpg and the hicolor icon theme." ;;
    esac
}

# --root DIR installs under DIR and asks neither a package manager nor this
# system's Python anything. It exists for the test suite.
root=
case "${1:-}" in
    --deps)
        [ $# = 1 ] || die "usage: $0 --deps"
        deps_command
        exit 0
        ;;
    --root)
        [ -n "${2:-}" ] || die "--root needs a directory"
        root=${2%/}
        shift 2
        ;;
esac
[ $# = 0 ] || die "usage: $0 [--deps]"

sha() { sha256sum < "$1" | cut -d' ' -f1; }

# Replace $2 with $1 in one rename, so a GUI starting at that moment reads
# either the old file or the new one.
place() {
    local src=$1 dst=$2 mode=$3 tmp
    install -d -m 755 "${dst%/*}"
    tmp="${dst%/*}/.${dst##*/}.ventulus-new"
    install -m "$mode" "$src" "$tmp"
    mv -f -- "$tmp" "$dst"
}

[ -r "$here/MANIFEST" ] || die "no MANIFEST beside $0; is the tarball complete?"
while read -r sum _mode path; do
    [ "$(sha "$here/files$path")" = "$sum" ] || die "$path does not match MANIFEST; download the tarball again"
done < "$here/MANIFEST"

if [ -z "$root" ]; then
    [ "$(id -u)" = 0 ] || die "run it as root: sudo $0"
    for path in /usr/bin/ventulus /usr/share/applications/ventulus.desktop; do
        if command -v dpkg > /dev/null && dpkg -S "$path" > /dev/null 2>&1; then
            die "$path belongs to a Debian package; upgrade it with apt"
        fi
        if command -v rpm > /dev/null && rpm -qf "$path" > /dev/null 2>&1; then
            die "$path belongs to an RPM package; upgrade it with dnf"
        fi
        if command -v pacman > /dev/null && pacman -Qqo "$path" > /dev/null 2>&1; then
            die "$path belongs to a pacman package; upgrade it with pacman"
        fi
    done
    missing=
    if ! command -v python3 > /dev/null; then
        missing="  - python3 is not installed"
    elif ! missing=$(python3 -I -B "$here/prereqs.py" "$here/files$libdir"); then
        [ -n "$missing" ] || die "the prerequisite check failed; nothing was installed"
    fi
    if [ -n "$missing" ]; then
        echo "install.sh: this system cannot run Ventulus yet; nothing was installed:" >&2
        echo "$missing" >&2
        echo "Install the prerequisites, then run install.sh again:" >&2
        echo "  $(deps_command)" >&2
        exit 1
    fi
fi

# What the previous tarball install shipped.
declare -A shipped=()
if [ -r "$root$manifest" ]; then
    while read -r _sum _mode path; do shipped[$path]=1; done < "$root$manifest"
fi
declare -A current=()

while read -r _sum mode path; do
    current[$path]=1
    place "$here/files$path" "$root$path" "$mode"
done < "$here/MANIFEST"

# Files the previous version shipped and this one does not.
for path in "${!shipped[@]}"; do
    [ -n "${current[$path]:-}" ] || rm -f -- "$root$path"
done

# Bytecode for this system's Python, rebuilt whole so none outlives its source.
find "$root$libdir" -name __pycache__ -type d -prune -exec rm -rf -- {} +
if command -v python3 > /dev/null; then
    python3 -I -m compileall -q "$root$libdir/ventulus"
fi

install -m 644 "$here/MANIFEST" "$root$manifest"

if [ -z "$root" ]; then
    cat << 'EOF'
Ventulus is installed. Start it from your application menu, or run: ventulus
  It needs ventulusd running:  sudo systemctl enable --now ventulusd
  Documentation:               /usr/local/share/doc/ventulus/manual/
  Uninstall:                   sudo /usr/local/lib/ventulus/uninstall
EOF
fi
