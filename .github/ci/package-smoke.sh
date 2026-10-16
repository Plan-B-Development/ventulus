#!/bin/bash
# package-smoke.sh <deb|rpm|tarball> <dir> <ventulusd>: install the GUI package
# on a clean system of the distribution, as root, and check it works (DEC-499,
# XD-4). ci.yml's `package-smoke` job runs it in each distribution's container;
# it runs unchanged in a VM.
#
#   deb      <dir> holds ventulus_<version>-1_all.deb and -2_all.deb
#   rpm      <dir> holds ventulus-<version>-1.fcN.noarch.rpm and -2
#   tarball  <dir> holds ventulus-<version>-noarch.tar.gz
#   ventulusd  the daemon binary from ventulusd's latest Release
#
# What it checks: the distribution provides every dependency the package
# declares (installed without recommends, so nothing else can stand in for a
# missing one); the program, desktop entry, icon, man page and version metadata
# are where they belong; the GUI starts offscreen with no daemon, and again
# with the released daemon, which it connects to; an upgrade works; removal
# leaves nothing behind.
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

package_file() {
    case "$format" in
        deb) echo "$dir/ventulus_${version}-${1}_all.deb" ;;
        rpm) ls "$dir"/ventulus-"$version"-"$1".*noarch.rpm ;;
    esac
}

# Once, before the package: apt refuses to install anything while dpkg holds a
# package whose dependency was skipped.
install_dependencies() {
    local pkg
    pkg=$(package_file 1)
    case "$format" in
        deb)
            # shellcheck disable=SC2046
            apt-get install -y -q --no-install-recommends $(dpkg-deb -f "$pkg" Depends | deb_names)
            ;;
        rpm)
            # shellcheck disable=SC2046
            dnf -y -q install --setopt=install_weak_deps=False $(rpm -qp --requires "$pkg" | rpm_names) &&
                rpm_unmet_is_only_ventulusd "$pkg"
            ;;
    esac
}

install_rev() {
    case "$format" in
        deb) dpkg --ignore-depends=ventulusd -i "$(package_file "$1")" ;;
        rpm) rpm -U --nodeps "$(package_file "$1")" ;;
        tarball) "$tardir/install.sh" ;;
    esac
}

# rpm itself, with the dependencies above installed, must miss nothing but the daemon.
rpm_unmet_is_only_ventulusd() {
    local unmet
    unmet=$(rpm -U --test "$1" 2>&1 | grep 'is needed by' | sed 's/ is needed by.*//; s/^[[:space:]]*//')
    [ "$unmet" = "ventulusd >= $floor" ] || { echo "unmet: $unmet"; return 1; }
}

installed_version() {
    case "$format" in
        deb) dpkg-query -W -f '${Version}' ventulus 2> /dev/null ;;
        rpm) rpm -q --qf '%{VERSION}-%{RELEASE}' ventulus 2> /dev/null ;;
        tarball) test -e /usr/local/lib/ventulus/tarball-manifest && echo tarball ;;
    esac
}

revision_is() { [[ "$(installed_version)" == "$version-$1"* ]]; }

declares_daemon_floor() {
    case "$format" in
        deb) dpkg-deb -f "$dir/ventulus_${version}-1_all.deb" Depends | tr ',' '\n' |
            grep -qx " *ventulusd (>= $floor)" ;;
        rpm) rpm -qp --requires "$(ls "$dir"/ventulus-"$version"-1.*noarch.rpm)" |
            grep -qx "ventulusd >= $floor" ;;
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
on_path() {
    local found
    found=$(as_user 'command -v ventulus')
    [ "$(realpath "$found")" = "$prefix/bin/ventulus" ] || { echo "ventulus is $found"; return 1; }
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
gui_runs_until() {
    local pattern=$1 socket=$2 log=$work/gui-$3.log pid _
    as_user "cd $work && QT_QPA_PLATFORM=offscreen exec ventulus --socket $socket" > "$log" 2>&1 &
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
        deb) dpkg -L ventulus | while read -r f; do [ -f "$f" ] && echo "$f"; done ;;
        rpm) rpm -ql ventulus | while read -r f; do [ -f "$f" ] && echo "$f"; done ;;
        tarball) sed 's/^[^ ]* [^ ]* //' /usr/local/lib/ventulus/tarball-manifest ;;
    esac
}

removed_cleanly() {
    local left
    left=$(while read -r f; do [ -e "$f" ] && echo "$f"; done < "$work/files")
    for d in /usr/share/ventulus /usr/local/lib/ventulus /usr/share/doc/ventulus \
        /usr/local/share/doc/ventulus /usr/lib/python3*/site-packages/ventulus; do
        [ -e "$d" ] && left="$left $d"
    done
    [ -z "$left" ] || { echo "left behind: $left"; return 1; }
}

if [ "$format" = tarball ]; then
    tar -C "$work" -xzf "$dir/ventulus-$version-noarch.tar.gz"
    tardir=$work/ventulus-$version-noarch
    check "the tarball refuses to install before its prerequisites" \
        bash -c "! '$tardir/install.sh' && [ ! -e /usr/local/bin/ventulus ]"
    deps=$("$tardir/install.sh" --deps)
    echo "prerequisites: $deps"
    # One package name per word.
    # shellcheck disable=SC2086
    case "$deps" in
        "sudo apt install "*) check "the prerequisites it names install" \
            apt-get install -y -q --no-install-recommends ${deps#sudo apt install } ;;
        "sudo dnf install "*) check "the prerequisites it names install" \
            dnf -y -q install --setopt=install_weak_deps=False ${deps#sudo dnf install } ;;
        *) fail "install.sh --deps names no command for $ID" ;;
    esac
else
    check "declares ventulusd >= $floor" declares_daemon_floor
    check "the distribution provides every other dependency" install_dependencies
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
    kill "$daemon_pid" 2> /dev/null
    wait "$daemon_pid" 2> /dev/null
fi

case "$format" in
    deb | rpm)
        check "upgrade to revision 2" install_rev 2
        check "revision 2 is installed" revision_is 2
        ;;
    tarball) check "install over the existing install (the upgrade path)" install_rev 1 ;;
esac
all_files > "$work/files"
check "the GUI still starts after the upgrade" gui_runs_until "Polling started" "$work/absent.sock" upgraded

case "$format" in
    deb) check "removal" dpkg -r ventulus ;;
    rpm) check "removal" rpm -e ventulus ;;
    tarball) check "removal" /usr/local/lib/ventulus/uninstall ;;
esac
check "removal leaves no file behind" removed_cleanly

echo "== $((steps - failures))/$steps passed"
[ "$failures" = 0 ]
