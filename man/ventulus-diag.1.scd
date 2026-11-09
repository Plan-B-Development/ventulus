ventulus-diag(1)

# NAME

ventulus-diag - diagnostics for ventulusd: hardware tests, reports and validation sessions

# SYNOPSIS

*ventulus-diag* [*--socket* _path_] _command_ [_options_]

# DESCRIPTION

*ventulus-diag* is the administrator's tool for the tests that deliberately
drive fans for investigation: the PWM Test Report (with its stall/restart
probe), PWM characterisation, control-path discovery and validation sessions.
It also lists, prints, exports and compares saved reports. The Ventulus GUI
keeps the everyday checks (Test Control, the GPU fan test, the Fan Wizard).

It writes nothing to hardware itself. Every test is a ventulusd diagnostic:
the daemon checks it is safe to start, performs it, and puts each header back
exactly as it found it when the test ends. It does that even if this tool is
killed, the terminal is closed or the connection is lost. Thermal protection
always overrides a test, a pump-protected header is never driven below its
floor, and only one test runs at a time.

Read-only commands need nothing. A command that changes fan speeds first
prints what it will touch and needs confirmation: type *yes* on a terminal, or
pass *--yes-change-fan-speeds* when not on one. Without either it starts
nothing. The stall/restart probe can stop a fan, so each header it runs on also
needs its own acknowledgement: type *stop* for it, or pass *--allow-fan-stop*
_header_.

Stay at the machine while a test runs. The first Ctrl-C (or SIGTERM, or SIGHUP)
asks the daemon to cancel the running test; the tool then waits for the
daemon to put the header back and prints the result. A second one leaves at
once, making sure a cancel was sent; the daemon still ends the test and
restores the header. *ventulus-diag cancel* stops a test left running.

The tool runs as your user. The daemon's socket is open to every local user
by design, so no sudo, group or permission change is needed, and none should
be made.

# OPTIONS

*--socket* _path_
	The daemon's socket. Default: /run/ventulus/ventulus.sock

*--version*
	Print the version and exit.

# READ-ONLY COMMANDS

*status*
	The daemon's version, thermal state, whether a test holds the daemon's
	diagnostic slot, and whether a test could start now.

*headers*
	Every motherboard header: stable id, name, role, pump protection, RPM, and
	the tests it offers. Use these ids with the commands below.

*preflight* _header_ _test_
	The daemon's safety verdict for one test (*verify*, *pairing*, *sweep* or
	*probe*) on one header. Reserves nothing.

*report list*++
*report show* _report_++
*report export* _report_ *--format* _markdown|html|json|csv_ *-o* _path_++
*report compare* _first_ _second_ [*--format* _markdown|html_] [*-o* _path_]
	Saved PWM Test Reports. _report_ is an id, a unique id prefix, or a path.
	CSV writes up to three files into the folder _path_. These need no daemon.

*validation devices | status | list | show* _session_ *| export* _session_
	Cooling devices and validation sessions. *export* takes *--format json|csv*
	and *-o* _path_.

# COMMANDS THAT CHANGE FAN SPEEDS

*report run* [*--header* _id_]... [*--test* _verify|pairing|sweep_]... [*--stall-probe* _id_]... [*--allow-fan-stop* _id_]... [*--notes* _file_] [*--snapshot-only*] [*--dry-run*] [*--yes-change-fan-speeds*]
	Run a PWM Test Report. Without *--header* it tests every writable header
	with a fan turning; without *--test* it runs the PWM control test and tach
	pairing. The full sweep and the stall/restart probe are opt-in. The
	report is saved after every step, and kept when a run is cancelled or
	cut short. *--snapshot-only* records the machine's state and writes
	nothing; *--dry-run* prints the plan. *--notes* reads your setup facts
	from a JSON file (*{"cooler": {...}, "headers": {"<id>": {...}}}*);
	without it, the answers an earlier GUI version saved are used.
	The exit status follows the steps as well as the run: *1* if any step
	failed, *5* if every step was refused or skipped.

*characterise* _header_ [*--yes-change-fan-speeds*]
	Walk one header across the daemon's duty points and record its RPM
	response. Curve control for every fan is paused while it runs.

*discover* _header_ [*--yes-change-fan-speeds*]
	Nudge one header and watch every tach to find which fan follows it.
	The result is kept by the daemon and shown on the GUI's header card.

*validation start* *--device* _id_ [*--kind* _validation|lifecycle|thermal_] [*--diagnostic* _verify|characterization|behaviour|control-path_]... [*--sweep-member* _id_]... [*--meta* _key=value_]... [*--auto-stop*] [*--detach*] [*--yes-change-fan-speeds*]
	Start a session on a cooling device and follow it. A session with no
	*--diagnostic* only records and needs no confirmation. Without
	*--sweep-member* the daemon sweeps the device's pump, which is never
	driven below its floor. Ctrl-C cancels an active session and the test it
	is running, or stops a passive one.

*cancel*
	Cancel a running characterisation, control-path discovery or
	stall/restart probe, whichever program started it. Needs no
	confirmation: a cancel only ends a test, and the daemon puts the header
	back. The PWM control test ends by itself within seconds.

*validation stop | cancel*++
*validation marker* [_text_] [*--member* _id_]++
*validation measure* _kind_ _value_ [*--unit* _u_] [*--member* _id_] [*--note* _text_]
	End the session (both save it), or add a marker or an external reading.
	A reading is evidence only: nothing acts on it.

# EXIT STATUS

*0*	Done.++
*1*	The daemon reported a test failed, *cancel* could not check or cancel a
	test, or a report could not be saved.++
*2*	Usage error.++
*3*	The daemon could not be reached.++
*4*	The daemon is too old for the command, or does not offer the test.++
*5*	Nothing was run: not confirmed, refused, another test running, thermal
	protection active, or an invalid target.++
*6*	You cancelled the test; the daemon put the header back.++
*7*	A safety rule ended the test.++
*8*	The daemon stopped answering, or restarted during the test; it restores
	the header itself.++
*130*	Stopped at once by a second interrupt.

# FILES

_$XDG_DATA_HOME/ventulus/reports/_ (default _~/.local/share/ventulus/reports/_)
	Saved PWM Test Reports, shared with earlier GUI versions. Never deleted
	automatically.

_$XDG_CONFIG_HOME/ventulus/app_settings.json_
	Read, never written: fan names, and the report's setup answers an
	earlier GUI version saved.

# SEE ALSO

*ventulus*(1), *ventulusd*(1), *journalctl*(1): the daemon logs every test
request with the caller's user and process id (*journalctl -u ventulusd |
grep 'hardware diagnostic'*).
