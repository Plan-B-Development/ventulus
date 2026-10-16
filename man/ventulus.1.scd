ventulus(1)

# NAME

ventulus - desktop fan control interface for ventulusd

# SYNOPSIS

*ventulus* [OPTIONS]

# DESCRIPTION

Ventulus GUI is a PySide6 (Qt6) desktop application for Linux that
communicates with the ventulusd service over its Unix socket HTTP
API. It provides real-time monitoring of temperatures and fan speeds, fan
curve editing, profile management, and manual fan override.

The GUI is a daemon API client only -- all hardware access is performed by
the daemon. Its one other connection is the update check, which is off by
default: only when you press *Check for updates* in Settings, or have turned
on the daily check, does it fetch the signed release information from
https://plan-b-development.github.io/pacman-repo/ventulus-updates.json.
It never installs an update itself.

# OPTIONS

*--socket* <path>
	Path to the daemon Unix socket.
	Default: /run/ventulus/ventulus.sock

*--demo*
	Run in demo mode with simulated hardware data. No daemon connection
	required.

# FILES

_~/.config/ventulus/app_settings.json_
	GUI application preferences.

_~/.config/ventulus/profiles/_
	User-created fan control profiles (JSON).

_~/.config/ventulus/themes/_
	Custom theme files (JSON).

_~/.config/ventulus/backups/_
	Automatic backups of app_settings.json, one taken before every
	settings import.

_~/.local/share/ventulus/reports/_
	Saved PWM Test Reports (JSON).

_~/.cache/ventulus/_
	Generated theme images. Safe to delete; it is recreated.

_~/.cache/ventulus/updates/_
	The update check's last verified release information, the time of the
	last check, and the update notice you dismissed. Safe to delete.

_~/.cache/ventulus/firmware/_
	Checked copies of OpenFAN firmware files, made for a firmware update.
	Safe to delete when no update is running.

_/run/ventulus/ventulus.sock_
	Default daemon Unix socket path.

# ENVIRONMENT

*XDG_CONFIG_HOME*
	Base directory for configuration. The GUI stores its preferences,
	profiles, themes and settings backups under $XDG_CONFIG_HOME/ventulus
	(default: ~/.config/ventulus). The profiles and themes folders can be
	moved in Settings.

*XDG_DATA_HOME*
	Base directory for data the GUI keeps: saved PWM Test Reports go in
	$XDG_DATA_HOME/ventulus/reports (default: ~/.local/share/ventulus).

*XDG_CACHE_HOME*
	Base directory for the cache, $XDG_CACHE_HOME/ventulus (default:
	~/.cache/ventulus).

# SEE ALSO

*ventulusd*(1)

Project: https://github.com/Plan-B-Development/ventulus

# AUTHORS

Plan B Development
