# Packs the wheel packaging/linux/build.sh built (DEC-499); nothing is compiled
# here but the bytecode. build.sh defines the version, the release, the staged
# tree (packaging/linux/stage.sh) and the %files list generated from it.
#
# The Python requirements are generated from the wheel's metadata, that is
# from pyproject.toml's dependencies (python3.14dist(pyqtgraph) >= 0.13.7 and so
# on), with python(abi) for the interpreter its site-packages belongs to. Only
# what that metadata cannot say is named below. No macro may be named in these
# comments: rpm expands them.

Name:           ventulus
Version:        %{ventulus_version}
Release:        %{ventulus_release}%{?dist}
Summary:        Desktop GUI for the Ventulus fan control daemon
License:        MIT AND OFL-1.1
URL:            https://github.com/Plan-B-Development/ventulus
BuildArch:      noarch
BuildRequires:  python3-devel
# The floor is constants.DAEMON_MINIMUM_VERSION. gnupg2 verifies the signed
# update manifest.
Requires:       ventulusd >= 3.0.0
Requires:       gnupg2
Requires:       hicolor-icon-theme

%description
Ventulus shows the fans and temperatures ventulusd reads and edits the fan
profiles it runs: curves, roles, overrides and fan tests. It talks only to the
daemon, over its local socket; the daemon alone drives the hardware and keeps
the fans under control when the GUI is closed.

%prep

%build

%install
cp -a %{ventulus_stage}/. %{buildroot}/

%files -f %{ventulus_filelist}
