#!/bin/bash
# stage.sh <flavour> <part> <wheel> <mandir> <destroot>
#
# Installs every file of one of the two Ventulus packages for Debian/Ubuntu
# (deb), Fedora (rpm) or the tarball into <destroot>, laid out as on the target
# system. This is the one file list for those three formats (DEC-499); it
# mirrors packaging/PKGBUILD's package_ventulus-diag() and package_ventulus(),
# and tests/test_packaging_linux.py holds the two together. Run from the
# repository root.
#
#   flavour  deb | rpm | tarball
#   part     cli  the ventulus-diag package: the whole Python library, its
#                 .dist-info and the ventulus-diag program (DEC-503)
#            gui  the ventulus package: the ventulus program, its desktop entry,
#                 icon, branding and documentation; it depends on ventulus-diag
#                 of the same version and on the Qt stack
#   wheel    the wheel build.sh built: pure Python, the same bytes in every format
#   mandir   holds ventulus.1 and ventulus-diag.1, rendered from man/*.scd
#
# Where the Python code goes (part cli):
#   deb      a private directory, /usr/share/ventulus, with launchers in /usr/bin
#            (Debian Python Policy), so one .deb serves every Python 3 version
#   rpm      site-packages of the Python running this script (build it on the
#            Fedora release it is for), with launchers in /usr/bin
#   tarball  /usr/local/lib/ventulus, with launchers in /usr/local/bin
# The library keeps the wheel's .dist-info: both programs read their version
# there, and without it the version is "dev" and the daemon-version checks are off.
set -euo pipefail

flavour=$1 part=$2 wheel=$3 mandir=$4 dest=$5

case "$part" in
    cli) pkg=ventulus-diag ;;
    gui) pkg=ventulus ;;
    *)
        echo "stage.sh: unknown part '$part' (cli or gui)" >&2
        exit 2
        ;;
esac

case "$flavour" in
    deb)
        # Debian's zsh reads vendor-completions, not site-functions. Debian
        # policy puts the licence in the package's doc directory as `copyright`.
        prefix=/usr
        libdir=/usr/share/ventulus
        assets=/usr/share/ventulus/assets
        zsh_dir=/usr/share/zsh/vendor-completions
        license_dir=/usr/share/doc/$pkg
        license_name=copyright
        installer=dpkg
        ;;
    rpm)
        prefix=/usr
        libdir=$(python3 -c 'import sys; print("/usr/lib/python%d.%d/site-packages" % sys.version_info[:2])')
        assets=/usr/share/ventulus/assets
        zsh_dir=/usr/share/zsh/site-functions
        license_dir=/usr/share/licenses/$pkg
        license_name=LICENSE
        installer=rpm
        ;;
    tarball)
        # paths.assets_dir() finds the branding beside the private module
        # directory, so the tarball needs nothing outside /usr/local.
        prefix=/usr/local
        libdir=/usr/local/lib/ventulus
        assets=/usr/local/lib/ventulus/assets
        zsh_dir=/usr/local/share/zsh/site-functions
        license_dir=/usr/local/share/licenses/$pkg
        license_name=LICENSE
        installer=ventulus-tarball
        ;;
    *)
        echo "stage.sh: unknown flavour '$flavour' (deb, rpm or tarball)" >&2
        exit 2
        ;;
esac

share=$prefix/share
doc=$share/doc/ventulus
put() { install -D -m "$1" -- "$2" "$dest$3"; }

# The program's launcher. Where the modules are private, it puts their directory
# first on the path, so an unrelated `ventulus` elsewhere cannot shadow them.
launcher() { # launcher <program> <module> <function>
    local tmp
    tmp=$(mktemp)
    {
        echo '#!/usr/bin/python3'
        echo 'import sys'
        [ "$flavour" = rpm ] || echo "sys.path.insert(0, \"$libdir\")"
        echo "from $2 import $3"
        echo "sys.exit($3())"
    } > "$tmp"
    put 755 "$tmp" "$prefix/bin/$1"
    rm -f -- "$tmp"
}

# The wheel holds the package and its .dist-info and nothing else; anything more
# (a .data directory, a second package) would need a place here, so it stops
# the build. RECORD goes: the package manager, or the tarball's MANIFEST, owns
# these files, and pip must not remove them. INSTALLER says who did install them.
stage_library() {
    python3 - "$wheel" "$dest$libdir" "$installer" << 'EOF'
import os
import sys
import zipfile
from pathlib import Path

wheel, target, installer = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
with zipfile.ZipFile(wheel) as zf:
    tops = {name.split("/", 1)[0] for name in zf.namelist()}
    dist_info = [t for t in tops if t.startswith("ventulus-") and t.endswith(".dist-info")]
    if len(dist_info) != 1 or tops != {"ventulus", dist_info[0]}:
        sys.exit(f"stage.sh: unexpected top-level entries in {wheel}: {sorted(tops)}")
    zf.extractall(target)
for root, dirs, files in os.walk(target):
    for d in dirs:
        os.chmod(os.path.join(root, d), 0o755)
    for f in files:
        os.chmod(os.path.join(root, f), 0o644)
meta = target / dist_info[0]
(meta / "RECORD").unlink()
(meta / "INSTALLER").write_text(installer + "\n")
os.chmod(meta / "INSTALLER", 0o644)
EOF
}

if [ "$part" = cli ]; then
    stage_library
    launcher ventulus-diag ventulus.diag.cli main
    put 644 "$mandir/ventulus-diag.1" "$share/man/man1/ventulus-diag.1"
    put 644 completions/ventulus-diag.bash "$share/bash-completion/completions/ventulus-diag"
    put 644 completions/_ventulus-diag "$zsh_dir/_ventulus-diag"
    put 644 completions/ventulus-diag.fish "$share/fish/vendor_completions.d/ventulus-diag.fish"
    # The bundled fonts are in the library, so their OFL texts travel with it (DEC-208).
    put 644 LICENSE "$license_dir/$license_name"
    put 644 src/ventulus/ui/fonts/OFL-DMSans.txt "$license_dir/OFL-DMSans.txt"
    put 644 src/ventulus/ui/fonts/OFL-SpaceGrotesk.txt "$license_dir/OFL-SpaceGrotesk.txt"
    exit 0
fi

launcher ventulus ventulus.main main
put 644 packaging/ventulus.desktop "$share/applications/ventulus.desktop"
put 644 assets/branding/app_icon/app_icon.svg "$share/icons/hicolor/scalable/apps/ventulus.svg"
# Loaded by the About dialog and the sidebar (paths.assets_dir()).
put 644 assets/branding/app_icon/app_icon.svg "$assets/branding/app_icon/app_icon.svg"

put 644 "$mandir/ventulus.1" "$share/man/man1/ventulus.1"

put 644 completions/ventulus.bash "$share/bash-completion/completions/ventulus"
put 644 completions/_ventulus "$zsh_dir/_ventulus"
put 644 completions/ventulus.fish "$share/fish/vendor_completions.d/ventulus.fish"

# The manual links into docs/19–24 by relative path, so they ship beside it.
put 644 README.md "$doc/README.md"
put 644 CHANGELOG.md "$doc/CHANGELOG.md"
# manual/admin/ keeps its folder: its pages link up with ../ (DEC-503).
for guide in manual/*.md manual/admin/*.md; do
    put 644 "$guide" "$doc/$guide"
done
for refdoc in docs/19_*.md docs/20_*.md docs/21_*.md docs/22_*.md docs/23_*.md docs/24_*.md; do
    put 644 "$refdoc" "$doc/docs/${refdoc##*/}"
done

# NOTICE.md records the GUI's dependencies whose licences carry obligations (DEC-260).
put 644 LICENSE "$license_dir/$license_name"
put 644 NOTICE.md "$license_dir/NOTICE.md"
