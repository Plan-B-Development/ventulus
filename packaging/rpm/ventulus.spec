# Packs the wheel packaging/linux/build.sh built (DEC-499); nothing is compiled
# here but the bytecode. build.sh defines the version, the release, the two
# staged trees (packaging/linux/stage.sh) and the file lists generated from them.
#
# Two packages (DEC-503): ventulus-diag carries the whole Python library and its
# .dist-info, ventulus the GUI. rpm generates the library's Python requirements
# from that metadata, that is from pyproject.toml's dependencies, with
# python(abi) for the interpreter its site-packages belongs to. The ones only
# the GUI imports are excluded there and named on ventulus below, with the
# floors and ceilings pyproject.toml gives them (tests/test_packaging_linux.py
# holds them equal). No macro may be named in these comments: rpm expands them.

%global __requires_exclude ^\\(?python3(\\.[0-9]+)?dist\\((pyside6|pyqtgraph|numpy|colorama)\\)

Name:           ventulus
Version:        %{ventulus_version}
Release:        %{ventulus_release}%{?dist}
Summary:        Desktop GUI for the Ventulus fan control daemon
License:        MIT
URL:            https://github.com/Plan-B-Development/ventulus
BuildArch:      noarch
BuildRequires:  python3-devel
Requires:       ventulus-diag = %{version}-%{release}
# The floor is constants.DAEMON_MINIMUM_VERSION. gnupg2 verifies the signed
# update manifest.
Requires:       ventulusd >= 3.0.0
Requires:       (python3dist(pyside6) >= 6.6 with python3dist(pyside6) < 7)
Requires:       (python3dist(pyqtgraph) >= 0.13.7 with python3dist(pyqtgraph) < 1)
Requires:       (python3dist(numpy) >= 2.0 with python3dist(numpy) < 3)
Requires:       (python3dist(colorama) >= 0.4 with python3dist(colorama) < 1)
Requires:       gnupg2
Requires:       hicolor-icon-theme

%description
Ventulus shows the fans and temperatures ventulusd reads and edits the fan
profiles it runs: curves, roles, overrides and fan tests. It talks only to the
daemon, over its local socket; the daemon alone drives the hardware and keeps
the fans under control when the GUI is closed.

%package -n ventulus-diag
Summary:        Diagnostics for the Ventulus fan control daemon
License:        MIT AND OFL-1.1
Requires:       ventulusd >= 3.0.0
# Up to 5.5.x these files were the ventulus package's. Any older ventulus
# requires its own ventulus-diag, so cannot run beside this one either.
Conflicts:      ventulus < %{version}-%{release}

%description -n ventulus-diag
ventulus-diag runs the tests that deliberately drive fans for investigation:
the PWM Test Report, PWM characterisation, control-path discovery and
validation sessions. Each is a ventulusd diagnostic, which the daemon checks,
performs and undoes; the tool asks for confirmation before anything changes a
fan speed. It needs no desktop.

%prep

%build

%install
cp -a %{ventulus_stage_cli}/. %{buildroot}/
cp -a %{ventulus_stage_gui}/. %{buildroot}/

%files -f %{ventulus_filelist_gui}

%files -n ventulus-diag -f %{ventulus_filelist_cli}
