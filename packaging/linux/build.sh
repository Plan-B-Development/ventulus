#!/bin/bash
# build.sh: the Debian/Ubuntu, Fedora and tarball packages of the Ventulus GUI
# (DEC-499). Run from the repository root.
#
#   build.sh wheel <work>                         the wheel and the man page into
#                                                 <work>/{wheel,man} (Debian 13)
#   build.sh deb <work> <version> <rev> <out>     Debian 13: ventulus_<version>-<rev>_all.deb
#   build.sh tarball <work> <version> <out>       ventulus-<version>-noarch.tar.gz
#   build.sh rpm <work> <version> <rev> <out>     on Fedora N: ventulus-<version>-<rev>.fcN.noarch.rpm
#
# One wheel serves all three formats, laid out by packaging/linux/stage.sh. The
# .rpm carries the Fedora release in its name because its modules sit in that
# release's site-packages (python3.14 on Fedora 44, python3.15 on 45), so each
# Fedora release served gets its own build; the .deb and the tarball
# keep theirs in a private directory and suit any Python 3 from 3.12.
set -euo pipefail

die() {
    echo "build.sh: $*" >&2
    exit 1
}

# The commit's time, so a rebuild of the same commit stamps the same dates.
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || date +%s)}

wheel() {
    local work=$1
    install -d "$work/wheel" "$work/man"
    python3 -m build --wheel --no-isolation --outdir "$work/wheel" .
    scdoc < man/ventulus.1.scd > "$work/man/ventulus.1"
}

# The wheel for <version>: a version that disagrees with pyproject.toml has none.
wheel_of() {
    local f=$1/wheel/ventulus-$2-py3-none-any.whl
    [ -f "$f" ] || die "no $f; is $2 the version in pyproject.toml?"
    realpath "$f"
}

deb() {
    local work=$1 version=$2 rev=$3 out=$4 tmp whl
    whl=$(wheel_of "$work" "$version")
    work=$(realpath "$work")
    tmp=$(mktemp -d)
    mkdir -p "$tmp/src"
    cp -r packaging/debian "$tmp/src/debian"
    cat > "$tmp/src/debian/changelog" <<EOF
ventulus ($version-$rev) unstable; urgency=medium

  * Ventulus $version; see /usr/share/doc/ventulus/CHANGELOG.md.

 -- Plan-B-Development <https://github.com/Plan-B-Development>  $(date -R -u -d "@$SOURCE_DATE_EPOCH")
EOF
    (cd "$tmp/src" && VENTULUS_REPO=$OLDPWD VENTULUS_WHEEL=$whl VENTULUS_MAN=$work/man \
        dpkg-buildpackage -b -us -uc)
    install -d "$out"
    cp "$tmp/ventulus_${version}-${rev}_all.deb" "$out/"
    rm -rf "$tmp"
}

tarball() {
    local work=$1 version=$2 out=$3 tmp name whl
    whl=$(wheel_of "$work" "$version")
    name=ventulus-$version-noarch
    tmp=$(mktemp -d)
    packaging/linux/stage.sh tarball "$whl" "$work/man" "$tmp/$name/files"
    install -D -m 755 packaging/linux/uninstall.sh "$tmp/$name/files/usr/local/lib/ventulus/uninstall"
    install -m 755 packaging/linux/install.sh "$tmp/$name/install.sh"
    install -m 644 packaging/linux/prereqs.py "$tmp/$name/prereqs.py"
    # install.sh reads this: each file's sha256, mode and path. It tells a
    # damaged extraction from a whole one, and lists what to remove.
    (cd "$tmp/$name/files" && find . -type f -printf '%P\n' | LC_ALL=C sort |
        while read -r f; do
            printf '%s %s /%s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$(stat -c %a "$f")" "$f"
        done) > "$tmp/$name/MANIFEST"
    install -d "$out"
    tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$SOURCE_DATE_EPOCH" \
        -C "$tmp" -czf "$out/$name.tar.gz" "$name"
    rm -rf "$tmp"
}

rpm_pkg() {
    local work=$1 version=$2 rev=$3 out=$4 tmp stage list whl sitelib built
    whl=$(wheel_of "$work" "$version")
    tmp=$(mktemp -d)
    stage=$tmp/stage
    packaging/linux/stage.sh rpm "$whl" "$work/man" "$stage"
    sitelib=$(python3 -c 'import sys; print("/usr/lib/python%d.%d/site-packages" % sys.version_info[:2])')
    # The %files list, generated from the staged tree so it cannot drift from
    # it. The module and .dist-info directories are listed whole, so the
    # bytecode rpmbuild compiles into them is packaged too; the licences are
    # %license, man pages carry a glob for rpm's compression, and the other
    # directories that belong to this package alone are owned.
    list=$tmp/files.list
    (cd "$stage" && find ".$sitelib" -mindepth 1 -maxdepth 1 -printf "$sitelib/%P\n" | LC_ALL=C sort
    find . -type f -not -path ".$sitelib/*" -printf '/%P\n' | LC_ALL=C sort | while read -r f; do
        case "$f" in
            /usr/share/licenses/*) echo "%license $f" ;;
            /usr/share/man/*) echo "$f*" ;;
            *) echo "$f" ;;
        esac
    done
    find . -mindepth 1 -type d -not -path ".$sitelib*" -printf '/%P\n' | LC_ALL=C sort |
        grep -E '/ventulus(/|$)' | sed 's/^/%dir /') > "$list"
    rpmbuild -bb \
        --define "_topdir $tmp/rpmbuild" \
        --define "ventulus_version $version" \
        --define "ventulus_release $rev" \
        --define "ventulus_stage $stage" \
        --define "ventulus_filelist $list" \
        packaging/rpm/ventulus.spec
    built=("$tmp"/rpmbuild/RPMS/noarch/ventulus-"$version"-"$rev".*noarch.rpm)
    if [ "${#built[@]}" != 1 ] || [ ! -f "${built[0]}" ]; then
        die "rpmbuild made ${built[*]}"
    fi
    install -d "$out"
    cp "${built[0]}" "$out/"
    rm -rf "$tmp"
}

[ -f packaging/linux/stage.sh ] || die "run from the repository root"
cmd=${1:-}
shift || true
case "$cmd" in
    wheel) [ $# = 1 ] || die "usage: build.sh wheel <work>"; wheel "$@" ;;
    deb) [ $# = 4 ] || die "usage: build.sh deb <work> <version> <rev> <out>"; deb "$@" ;;
    tarball) [ $# = 3 ] || die "usage: build.sh tarball <work> <version> <out>"; tarball "$@" ;;
    rpm) [ $# = 4 ] || die "usage: build.sh rpm <work> <version> <rev> <out>"; rpm_pkg "$@" ;;
    *) die "usage: build.sh wheel|deb|tarball|rpm ..." ;;
esac
