#!/bin/bash
# stage.sh <flavour> <wheel> <mandir> <destroot>
#
# Installs every file of the ventulus GUI package for Debian/Ubuntu (deb), Fedora
# (rpm) or the tarball into <destroot>, laid out as on the target system. This
# is the one file list for those three formats (DEC-499); it mirrors
# packaging/PKGBUILD's package(), and tests/test_packaging_linux.py holds the
# two together. Run from the repository root.
#
#   flavour  deb | rpm | tarball
#   wheel    the wheel build.sh built: pure Python, the same bytes in every format
#   mandir   holds ventulus.1, rendered from man/ventulus.1.scd
#
# Where the Python code goes:
#   deb      a private directory, /usr/share/ventulus, with a launcher in /usr/bin
#            (Debian Python Policy), so one .deb serves every Python 3 version
#   rpm      site-packages of the Python running this script (build it on the
#            Fedora release it is for), with the entry point as /usr/bin/ventulus
#   tarball  /usr/local/lib/ventulus, with a launcher in /usr/local/bin
# Each keeps the wheel's .dist-info: the GUI reads its own version there, and
# without it the version is "dev" and its daemon-version checks are off.
set -euo pipefail

flavour=$1 wheel=$2 mandir=$3 dest=$4

case "$flavour" in
    deb)
        # Debian's zsh reads vendor-completions, not site-functions. Debian
        # policy puts the licence in the package's doc directory as `copyright`.
        prefix=/usr
        libdir=/usr/share/ventulus
        assets=/usr/share/ventulus/assets
        zsh_dir=/usr/share/zsh/vendor-completions
        license_dir=/usr/share/doc/ventulus
        license_name=copyright
        installer=dpkg
        ;;
    rpm)
        prefix=/usr
        libdir=$(python3 -c 'import sys; print("/usr/lib/python%d.%d/site-packages" % sys.version_info[:2])')
        assets=/usr/share/ventulus/assets
        zsh_dir=/usr/share/zsh/site-functions
        license_dir=/usr/share/licenses/ventulus
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
        license_dir=/usr/local/share/licenses/ventulus
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

# The wheel holds the package and its .dist-info and nothing else; anything more
# (a .data directory, a second package) would need a place here, so it stops
# the build. RECORD goes: the package manager, or the tarball's MANIFEST, owns
# these files, and pip must not remove them. INSTALLER says who did install them.
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

# The program. Where the modules are private, the launcher puts their directory
# first on the path, so an unrelated `ventulus` elsewhere cannot shadow them.
launcher=$(mktemp)
{
    echo '#!/usr/bin/python3'
    echo 'import sys'
    [ "$flavour" = rpm ] || echo "sys.path.insert(0, \"$libdir\")"
    echo 'from ventulus.main import main'
    echo 'sys.exit(main())'
} > "$launcher"
put 755 "$launcher" "$prefix/bin/ventulus"
rm -f -- "$launcher"

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
for guide in manual/*.md; do
    put 644 "$guide" "$doc/manual/${guide##*/}"
done
for refdoc in docs/19_*.md docs/20_*.md docs/21_*.md docs/22_*.md docs/23_*.md docs/24_*.md; do
    put 644 "$refdoc" "$doc/docs/${refdoc##*/}"
done

# NOTICE.md and the bundled fonts' OFL texts travel with the licence (DEC-208, DEC-260).
put 644 LICENSE "$license_dir/$license_name"
put 644 NOTICE.md "$license_dir/NOTICE.md"
put 644 src/ventulus/ui/fonts/OFL-DMSans.txt "$license_dir/OFL-DMSans.txt"
put 644 src/ventulus/ui/fonts/OFL-SpaceGrotesk.txt "$license_dir/OFL-SpaceGrotesk.txt"
