#!/bin/bash
# package-smoke.sh <deb|rpm|tarball> <dir> <ventulusd>: install the Ventulus
# packages on a clean system of the distribution, as root, and check they work
# (DEC-499, XD-4). ci.yml's `package-smoke` job runs it in each distribution's
# container; it runs unchanged in a VM.
#
#   deb      <dir> holds ventulus_<version>-1_all.deb, ventulus-diag_<version>-1_all.deb
#            and their -2 builds
#   rpm      <dir> holds ventulus-<version>-1.fcN.noarch.rpm, ventulus-diag-<version>-1.fcN.noarch.rpm
#            and their -2 builds for this Fedora release N (builds for other
#            releases may sit beside them)
#   tarball  <dir> holds ventulus-<version>-noarch.tar.gz
#   ventulusd  the daemon binary from ventulusd's latest Release
#
# What it checks: first ventulus-diag alone, as on a machine with no desktop
# (DEC-503): its dependencies install and bring no Qt, and the CLI runs. Then
# the GUI beside it: the distribution provides every dependency each package
# declares (installed without recommends, so nothing else can stand in for a
# missing one); the program, desktop entry, icon, man pages and version
# metadata are where they belong; the GUI starts offscreen with no daemon, and
# again with the released daemon, which it and the CLI connect to; an upgrade
# of both works; removal leaves nothing behind.
#
# The package depends on ventulusd, which no distribution carries. Here the
# daemon is the released binary, run as an unprivileged user with its socket
# and state in a temporary directory, so it can touch no hardware; the GUI
# package is installed with that one dependency skipped. Resolving ventulusd
# from the project's own repositories is pacman-repo's verify.yml (XD-5).
set -uo pipefail

format=${1:?usage: package-smoke.sh deb|rpm|tarball <dir> <ventulusd>}
dir=$(realpath "${2:?usage: package-smoke.sh deb|rpm|tarball <dir> <ventulusd>}")
daemon=$(realpath "${3:?usage: package-smoke.sh deb|rpm|tarball <dir> <ventulusd>}")
repo=$(cd "$(dirname "$0")/../.." && pwd)
version=$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml")
floor=$(sed -n 's/^DAEMON_MINIMUM_VERSION = "\(.*\)"/\1/p' "$repo/src/ventulus/constants.py")
user=ventulus-smoke
work=/tmp/ventulus-smoke
failures=0
steps=0

pass() { steps=$((steps + 1)); echo "PASS  $*"; }
fail() { steps=$((steps + 1)); failures=$((failures + 1)); echo "FAIL  $*"; }
check() {
    local label=$1
    shift
    if "$@"; then pass "$label"; else fail "$label"; fi
}

if [ -z "$version" ] || [ -z "$floor" ]; then
    echo "cannot read the version or the daemon floor" >&2
    exit 2
fi
. /etc/os-release
echo "== ventulus $version package smoke: $format ($PRETTY_NAME)"

case "$format" in
    deb)
        prefix=/usr libdir=/usr/share/ventulus
        # The Ubuntu image's dpkg drops /usr/share/man; a real system keeps it.
        rm -f /etc/dpkg/dpkg.cfg.d/excludes
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -q
        apt-get install -y -q --no-install-recommends desktop-file-utils procps
        ;;
    rpm)
        prefix=/usr libdir=
        # util-linux: su, which the minimal fedora image lacks (as_user).
        dnf -y -q install --setopt=install_weak_deps=False desktop-file-utils procps-ng util-linux
        ;;
    tarball)
        prefix=/usr/local libdir=/usr/local/lib/ventulus
        case " $ID ${ID_LIKE:-} " in
            *" fedora "*) dnf -y -q install --setopt=install_weak_deps=False \
                desktop-file-utils procps-ng util-linux tar gzip ;;
            *)
                export DEBIAN_FRONTEND=noninteractive
                apt-get update -q
                apt-get install -y -q --no-install-recommends desktop-file-utils procps
                ;;
        esac
        ;;
    *)
        echo "unknown format $format" >&2
        exit 2
        ;;
esac
id "$user" > /dev/null 2>&1 || useradd -m "$user"
rm -rf "$work"
install -d -o "$user" "$work"

# A dependency list's package names, versions and alternatives dropped:
# `a (>= 1), b | c` -> `a b`. dpkg itself then holds each version.
deb_names() { tr ',' '\n' | sed 's/|.*//; s/(.*//; s/^ *//; s/ *$//' | grep -v -e '^$' -e '^ventulusd$'; }
# rpm requirements as names dnf can install; rich ones like
# `(python3.14dist(numpy) < 3~~ with python3.14dist(numpy) >= 2)` by their first name.
rpm_names() {
    sed -E 's/^\(//; s/ .*//' | grep -v -e '^rpmlib(' -e '^ventulusd$' | sort -u
}

# package_file <rev> [ventulus|ventulus-diag]
package_file() {
    local name=${2:-ventulus}
    case "$format" in
        deb) echo "$dir/${name}_${version}-${1}_all.deb" ;;
        # The build for this Fedora release: <dir> holds one per release served.
        rpm) echo "$dir/${name}-${version}-${1}.fc$(rpm -E %fedora).noarch.rpm" ;;
    esac
}

# install_dependencies <package>: what <package> declares, before it is
# installed: apt refuses to install anything while dpkg holds a package whose
# dependency was skipped. ventulus-diag stands for itself: it is installed first.
install_dependencies() {
    local pkg
    pkg=$(package_file 1 "$1")
    case "$format" in
        deb)
            # shellcheck disable=SC2046
            apt-get install -y -q --no-install-recommends \
                $(dpkg-deb -f "$pkg" Depends | deb_names | grep -vx ventulus-diag)
            ;;
        rpm)
            # shellcheck disable=SC2046
            dnf -y -q install --setopt=install_weak_deps=False \
                $(rpm -qp --requires "$pkg" | rpm_names | grep -vx ventulus-diag) &&
                rpm_unmet_is_only_ventulusd "$1"
            ;;
    esac
}

# --nosignature: the package is this run's own unsigned build. rpm 6.1
# (Fedora 45) refuses an unsigned package by default (%_pkgverify_level all);
# dnf, which users install with, warns and installs it.
# install_rev <rev> [cli]: ventulus-diag alone with `cli`, else both packages.
install_rev() {
    local -a files=("$(package_file "$1" ventulus-diag)")
    [ "${2:-}" = cli ] || files+=("$(package_file "$1")")
    case "$format" in
        # --auto-deconfigure: what apt does when the new ventulus-diag's Breaks
        # names the installed, older GUI, which is upgraded in the same run.
        deb) dpkg --ignore-depends=ventulusd --auto-deconfigure -i "${files[@]}" ;;
        rpm) rpm -U --nodeps --nosignature "${files[@]}" ;;
        tarball) "$tardir/install.sh" ${2:+--cli-only} ;;
    esac
}

# rpm itself, with the dependencies above installed, must miss nothing but the
# daemon. The GUI is tested with ventulus-diag, which it needs, beside it.
rpm_unmet_is_only_ventulusd() {
    local unmet
    local -a files=("$(package_file 1 ventulus-diag)")
    [ "$1" = ventulus-diag ] || files+=("$(package_file 1)")
    unmet=$(rpm -U --test --nosignature "${files[@]}" 2>&1 | grep 'is needed by' |
        sed 's/ is needed by.*//; s/^[[:space:]]*//' | sort -u)
    [ "$unmet" = "ventulusd >= $floor" ] || { echo "unmet: $unmet"; return 1; }
}

installed_version() {
    case "$format" in
        deb) dpkg-query -W -f '${Version}' "$1" 2> /dev/null ;;
        rpm) rpm -q --qf '%{VERSION}-%{RELEASE}' "$1" 2> /dev/null ;;
        tarball) test -e /usr/local/lib/ventulus/tarball-manifest && echo tarball ;;
    esac
}

revision_is() { # revision_is <rev> <package>...
    local rev=$1 name
    shift
    for name in "$@"; do
        [[ "$(installed_version "$name")" == "$version-$rev"* ]] || return 1
    done
}

declares_daemon_floor() {
    local name
    for name in ventulus-diag ventulus; do
        case "$format" in
            deb) dpkg-deb -f "$(package_file 1 "$name")" Depends | tr ',' '\n' |
                grep -qx " *ventulusd (>= $floor)" ;;
            rpm) rpm -qp --requires "$(package_file 1 "$name")" |
                grep -qx "ventulusd >= $floor" ;;
        esac || { echo "$name does not declare ventulusd >= $floor"; return 1; }
    done
}

# The GUI needs the ventulus-diag of its own build.
gui_needs_its_library() {
    case "$format" in
        deb) dpkg-deb -f "$(package_file 1)" Depends | tr ',' '\n' |
            grep -qx " *ventulus-diag (= $version-1)" ;;
        rpm) rpm -qp --requires "$(package_file 1)" |
            grep -qx "ventulus-diag = $version-1.fc$(rpm -E %fedora)" ;;
    esac
}

as_user() { su -s /bin/bash "$user" -c "$1"; }

# The installed code's own answer, from the directory the launcher puts first
# on the path (none for the rpm: its modules are in site-packages).
gui_python() {
    {
        echo 'import sys'
        [ -z "$libdir" ] || echo "sys.path.insert(0, '$libdir')"
        echo "$1"
    } > "$work/check.py"
    chown "$user" "$work/check.py"
    as_user "cd $work && QT_QPA_PLATFORM=offscreen python3 -I check.py"
}

# As the user's shell finds it; /bin is /usr/bin on Fedora.
on_path() { # on_path [program]
    local program=${1:-ventulus} found
    found=$(as_user "command -v $program")
    [ "$(realpath "$found")" = "$prefix/bin/$program" ] || { echo "$program is $found"; return 1; }
}

# ventulus-diag as the user runs it; its status is the second line of output.
cli_reports_version() {
    local got
    got=$(as_user "cd $work && ventulus-diag --version")
    [ "$got" = "ventulus-diag $version" ] || { echo "ventulus-diag --version: $got"; return 1; }
}

# With no daemon: exit 3 (unreachable), and its message names no privilege fix.
cli_without_a_daemon() {
    local out status
    out=$(as_user "cd $work && ventulus-diag --socket $work/absent.sock status" 2>&1)
    status=$?
    echo "$out"
    [ "$status" = 3 ] && ! grep -qiE 'sudo|chmod' <<< "$out"
}

cli_reads_the_daemon() {
    local out
    out=$(as_user "cd $work && ventulus-diag --socket $work/ventulus.sock status") || { echo "$out"; return 1; }
    echo "$out"
    grep -q '^ventulusd ' <<< "$out"
}

# DEC-503: a machine with ventulus-diag alone has no Qt.
no_qt_installed() {
    ! as_user "cd $work && python3 -I -c 'import PySide6'" 2> /dev/null
}

reports_version() {
    local got
    got=$(gui_python 'from ventulus.constants import APP_VERSION; print(APP_VERSION)')
    [ "$got" = "$version" ] || { echo "APP_VERSION is $got"; return 1; }
}

# DEC-499: the update check verifies its manifest with gpg against this key.
# A garbage signature must get past the key import and be refused there: with
# only the declared dependencies installed, the import itself has to succeed.
ships_update_key() {
    gui_python "
import subprocess, tempfile
from ventulus.services.signature import REPOSITORY_KEY_FINGERPRINT, SignatureError, bundled_key_path, verify_detached
with tempfile.TemporaryDirectory() as home:
    out = subprocess.run(['gpg', '--homedir', home, '--batch', '--with-colons', '--show-keys',
                          str(bundled_key_path())], capture_output=True, text=True, check=True).stdout
fprs = [line.split(':')[9] for line in out.splitlines() if line.startswith('fpr:')]
assert fprs and fprs[0] == REPOSITORY_KEY_FINGERPRINT, fprs
try:
    verify_detached(b'probe', b'not a signature')
except SignatureError as exc:
    assert 'bundled key' not in str(exc), exc
else:
    raise AssertionError('a garbage signature was accepted')
"
}

icon_renders() {
    gui_python "
from PySide6.QtGui import QGuiApplication, QIcon
app = QGuiApplication([])
theme = QIcon('$prefix/share/icons/hicolor/scalable/apps/ventulus.svg')
assert not theme.pixmap(64, 64).isNull(), 'the menu icon does not render'
from ventulus.ui.branding import load_app_icon
icon = load_app_icon()
assert icon is not None and not icon.pixmap(64, 64).isNull(), 'the window icon does not render'
print('icons render')"
}

# Starts the GUI offscreen, waits for <pattern> in its log, then stops it with
# SIGINT (the window closes as from the window manager) and wants exit status 0.
# PYTHONFAULTHANDLER puts the Python stack of a crash into the log it prints.
gui_runs_until() {
    local pattern=$1 socket=$2 log=$work/gui-$3.log pid _
    as_user "cd $work && PYTHONFAULTHANDLER=1 QT_QPA_PLATFORM=offscreen exec ventulus --socket $socket" > "$log" 2>&1 &
    pid=$!
    for _ in $(seq 60); do
        grep -q "$pattern" "$log" && break
        kill -0 "$pid" 2> /dev/null || break
        sleep 1
    done
    if ! grep -q "$pattern" "$log"; then
        echo "no '$pattern' in the log:"
        cat "$log"
        kill "$pid" 2> /dev/null
        return 1
    fi
    sleep 2 # a crash right after the first poll would show here
    pkill -INT -u "$user" -x ventulus
    wait "$pid"
    local status=$?
    if [ "$status" != 0 ] || grep -q -e Traceback -e 'Uncaught exception' "$log"; then
        echo "exit status $status:"
        cat "$log"
        return 1
    fi
}

start_daemon() {
    cat > "$work/daemon.toml" << EOF
[ipc]
socket_path = "$work/ventulus.sock"

[state]
state_dir = "$work/state"
EOF
    install -m 755 -o "$user" "$daemon" "$work/ventulusd"
    chown "$user" "$work/daemon.toml"
    as_user "exec $work/ventulusd --allow-non-root --config $work/daemon.toml" > "$work/daemon.log" 2>&1 &
    daemon_pid=$!
    local _
    for _ in $(seq 30); do
        [ -S "$work/ventulus.sock" ] && return 0
        sleep 1
    done
    cat "$work/daemon.log"
    return 1
}

all_files() {
    case "$format" in
        deb) dpkg -L ventulus ventulus-diag | while read -r f; do [ -f "$f" ] && echo "$f"; done ;;
        rpm) rpm -ql ventulus ventulus-diag | while read -r f; do [ -f "$f" ] && echo "$f"; done ;;
        tarball) sed 's/^[^ ]* [^ ]* //' /usr/local/lib/ventulus/tarball-manifest ;;
    esac
}

removed_cleanly() {
    local left
    left=$(while read -r f; do [ -e "$f" ] && echo "$f"; done < "$work/files")
    for d in /usr/share/ventulus /usr/local/lib/ventulus /usr/share/doc/ventulus \
        /usr/share/doc/ventulus-diag /usr/local/share/doc/ventulus \
        /usr/lib/python3*/site-packages/ventulus; do
        [ -e "$d" ] && left="$left $d"
    done
    [ -z "$left" ] || { echo "left behind: $left"; return 1; }
}

# install_prerequisites [--cli-only]: what `install.sh --deps` names, as a user would.
install_prerequisites() {
    local deps
    deps=$("$tardir/install.sh" --deps "$@")
    echo "prerequisites: $deps"
    # One package name per word.
    # shellcheck disable=SC2086
    case "$deps" in
        "sudo apt install "*) apt-get install -y -q --no-install-recommends ${deps#sudo apt install } ;;
        "sudo dnf install "*) dnf -y -q install --setopt=install_weak_deps=False ${deps#sudo dnf install } ;;
        *) echo "install.sh --deps names no command for $ID"; return 1 ;;
    esac
}

# ── ventulus-diag alone, as on a machine with no desktop ──
if [ "$format" = tarball ]; then
    tar -C "$work" -xzf "$dir/ventulus-$version-noarch.tar.gz"
    tardir=$work/ventulus-$version-noarch
    check "the tarball refuses to install before its prerequisites" \
        bash -c "! '$tardir/install.sh' --cli-only && [ ! -e /usr/local/bin/ventulus-diag ]"
    check "the prerequisites it names for ventulus-diag install" install_prerequisites --cli-only
else
    check "both packages declare ventulusd >= $floor" declares_daemon_floor
    check "the GUI needs the ventulus-diag of its own build" gui_needs_its_library
    check "the distribution provides ventulus-diag's other dependencies" \
        install_dependencies ventulus-diag
fi
check "install ventulus-diag alone" install_rev 1 cli
check "ventulus-diag is on the PATH" on_path ventulus-diag
check "ventulus-diag reports version $version" cli_reports_version
check "ventulus-diag answers 3 with no daemon, and suggests no privilege change" cli_without_a_daemon
check "the ventulus-diag man page is installed" \
    test -s "$prefix/share/man/man1/ventulus-diag.1.gz" -o -s "$prefix/share/man/man1/ventulus-diag.1"
check "ventulus-diag alone brings no Qt" no_qt_installed

# ── the GUI beside it ──
# apt (and dnf) install nothing while a package whose dependency was skipped is
# installed, so ventulus-diag goes before the GUI's dependencies, and both
# packages are installed together after them. The tarball is installed over.
case "$format" in
    deb) check "remove ventulus-diag again" dpkg -r ventulus-diag ;;
    rpm) check "remove ventulus-diag again" rpm -e ventulus-diag ;;
esac
if [ "$format" = tarball ]; then
    check "the full install refuses before the GUI's prerequisites" \
        bash -c "! '$tardir/install.sh' && [ ! -e /usr/local/bin/ventulus ]"
    check "the prerequisites it names install" install_prerequisites
else
    check "the distribution provides every other dependency of the GUI" install_dependencies ventulus
fi

check "install revision 1" install_rev 1
check "the program is on the PATH" on_path
check "reports version $version (its .dist-info is installed)" reports_version
check "ships the update-check key, and gpg can import it and check a signature" ships_update_key
check "the desktop entry is valid" desktop-file-validate "$prefix/share/applications/ventulus.desktop"
check "the menu and window icons render" icon_renders
check "the man page is installed" test -s "$prefix/share/man/man1/ventulus.1.gz" -o -s "$prefix/share/man/man1/ventulus.1"
check "starts offscreen with no daemon" gui_runs_until "Polling started" "$work/absent.sock" nodaemon

if check "the released ventulusd ($("$daemon" --version 2>&1)) serves a socket" start_daemon; then
    check "connects to the released daemon" gui_runs_until "Daemon connection established" "$work/ventulus.sock" daemon
    check "ventulus-diag reads the released daemon" cli_reads_the_daemon
    kill "$daemon_pid" 2> /dev/null
    wait "$daemon_pid" 2> /dev/null
fi

case "$format" in
    deb | rpm)
        check "upgrade both to revision 2" install_rev 2
        check "revision 2 of both is installed" revision_is 2 ventulus ventulus-diag
        ;;
    tarball) check "install over the existing install (the upgrade path)" install_rev 1 ;;
esac
all_files > "$work/files"
check "the GUI still starts after the upgrade" gui_runs_until "Polling started" "$work/absent.sock" upgraded

case "$format" in
    deb) check "removal" dpkg -r ventulus ventulus-diag ;;
    rpm) check "removal" rpm -e ventulus ventulus-diag ;;
    tarball) check "removal" /usr/local/lib/ventulus/uninstall ;;
esac
check "removal leaves no file behind" removed_cleanly

echo "== $((steps - failures))/$steps passed"
[ "$failures" = 0 ]
