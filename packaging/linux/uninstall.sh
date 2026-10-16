#!/bin/bash
# /usr/local/lib/ventulus/uninstall: remove a Ventulus GUI installed from the
# tarball (DEC-499). Your settings, profiles and themes in your home directory
# are left alone, and so is ventulusd, which is installed separately.
set -euo pipefail

die() {
    echo "uninstall: $*" >&2
    exit 1
}

# --root DIR removes the install under DIR. It exists for the test suite.
root=
if [ "${1:-}" = --root ]; then
    [ -n "${2:-}" ] || die "--root needs a directory"
    root=${2%/}
    shift 2
fi
[ $# = 0 ] || die "usage: $0"
libdir=/usr/local/lib/ventulus
manifest=$libdir/tarball-manifest

[ -r "$root$manifest" ] || die "no tarball install of Ventulus here ($manifest is missing)"
[ -n "$root" ] || [ "$(id -u)" = 0 ] || die "run it as root: sudo $0"

while read -r _sum _mode path; do
    rm -f -- "$root$path"
done < "$root$manifest"
rm -f -- "$root$manifest"

# The bytecode install.sh compiled, then every directory the install left empty.
[ -d "$root$libdir" ] && find "$root$libdir" -name __pycache__ -type d -prune -exec rm -rf -- {} +
for dir in "$libdir" /usr/local/share/doc/ventulus /usr/local/share/licenses/ventulus; do
    [ -d "$root$dir" ] && find "$root$dir" -depth -type d -empty -delete
done

echo "Ventulus is removed. Your settings stay in ~/.config/ventulus."
