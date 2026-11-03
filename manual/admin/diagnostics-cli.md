# Diagnostic Command (`ventulus-diag`)

`ventulus-diag` runs the tests that drive fans on purpose: the PWM Test Report
(with its stall/restart probe), PWM characterisation, control-path discovery and
the cooler recording sessions. These take minutes, pause fan curves for every fan
while they run, and one of them may stop a fan, so they belong to a deliberate
session at a terminal rather than a button in the app. Treat it as an advanced
tool: you need it to investigate a fan or cooler, or to gather evidence for a bug
report, not to use Ventulus day to day.

What each test measures and how to read its result is in
[Fan Tests and Reports](../fan-tests.md). This page is how to run them safely.
`man ventulus-diag` lists every command, option and exit status.

## Getting it

It is its own package, `ventulus-diag`, which the app depends on, so a desktop
install has it already. A machine with no desktop can install it beside the daemon
without Qt ([Installing § A machine with no desktop](install.md#a-machine-with-no-desktop)).
It runs as your own user: never with `sudo`, which it does not need.

## Before you run a test

- **Look first.** `ventulus-diag status` shows the daemon, its thermal state and
  whether a test could start now; `ventulus-diag headers` lists every motherboard
  header with the id the other commands take, its role, whether it is
  pump-protected and its floor; `ventulus-diag preflight HEADER TEST` shows the
  daemon's safety verdict for one test on one header. None of these changes
  anything, and neither do `report list|show|export|compare`.
- **Make sure each pump is known.** Pump protection applies only to a header the
  daemon knows is a pump: give an unlabelled pump header its role first (**Set
  role… ▸ Pump** on the app's **Hardware** page). `headers` shows which are
  protected.
- **Idle and cool.** No test starts above the daemon's diagnostic temperature
  limit, and one stops if a temperature passes it. Start from an idle machine.
- **Chassis fans first.** Try a test on a chassis fan before a CPU fan or pump.
- **Stay at the machine** while a test runs, and keep an eye on temperatures.

## How it asks before it changes anything

A command that changes fan speeds first prints what it will do: the header or
cooler by name and id, how long it takes, and what keeps it safe (for a pump, its
floor; for the PWM Test Report, the daemon's temperature limit). Then it asks you
to type `yes`. Run from a script rather than a terminal, it needs
`--yes-change-fan-speeds` instead, and refuses without it, so a script that runs it
by accident changes no fan. A test that may **stop** a fan (the report's
stall/restart probe) also needs an acknowledgement for each header: typing `stop`
for it, or `--allow-fan-stop HEADER`. A recording session with no diagnostics
changes nothing and asks nothing.

The daemon checks everything again when the request arrives. It refuses a test,
whatever the tool or its flags say, when the machine is too hot, thermal
protection is active, temperature readings have gone stale, the header is
read-only, or another test is running. The daemon runs one test at a time; the app
says *another hardware test is running* if you try one there meanwhile.

## Stopping a test

- **Ctrl-C** asks the daemon to cancel the test and waits until the header is put
  back. A second Ctrl-C leaves at once; the daemon still puts the header back.
- **From another terminal,** `ventulus-diag cancel` cancels a running
  characterisation, discovery or stall probe, whoever started it.
  `ventulus-diag validation stop` ends a recording session and saves it.
- **Closing the terminal or killing the tool** does not leave a fan at a test
  speed: the test runs on in the daemon, which restores the fan when it ends.

## If a test was cut short

The daemon, not the tool, undoes every test: when it finishes, when you cancel,
when a write fails, when the tool is killed and when the daemon itself stops. What
it does in each case, and the rare case where it cannot, is in
[Fan Tests § What the daemon guarantees during a test](../fan-tests.md#what-the-daemon-guarantees-during-a-test).
After an interrupted test:

1. `ventulus-diag status` should show that no diagnostic holds the slot. If one
   still does, `ventulus-diag cancel`.
2. A result with a **Restore:** line means the daemon could not put that header
   back. Apply your profile again in the app, or restart the daemon
   (`sudo systemctl restart ventulusd`), which gives every header back as it found
   it.
3. A PWM Test Report cancelled or cut short is still saved, with what it did not
   test listed as not tested.

## Where results go

Reports are saved to `~/.local/share/ventulus/reports/` and recording sessions are
kept by the daemon; both are listed by `report list` and `validation list`. Every
test start is also written to the daemon's journal with the user and process that
asked for it ([Logs and Bug Reports](logs-and-bug-reports.md#the-daemons-journal)).
To share results in a bug report, export them: `report export REPORT --format
markdown -o FILE`, or `validation export SESSION --format json -o FILE`.

---

Back to [Administration](README.md)
