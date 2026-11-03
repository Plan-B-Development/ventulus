# Known Limits

What Ventulus cannot do, or does only partly, and where each is explained. None of
these is a fault to report unless the page it links to says otherwise.

## Hardware it cannot reach

- **Only hardware with a Linux kernel driver.** The daemon never talks to a USB
  device or a chip directly and does not use `liquidctl`, so a cooler with no
  mainline driver (most USB AIOs) is invisible to it. Plugging its pump into a
  motherboard header, where the cooler allows it, is the usual way round
  ([Getting Started § Supported coolers and controllers](../getting-started.md#supported-coolers-and-controllers)).
- **GPU fans.** NVIDIA and Intel Arc fans are monitor-only: no kernel interface
  writes them
  ([NVIDIA](../hardware-troubleshooting.md#nvidia-gpus-are-monitor-only),
  [Intel Arc](../hardware-troubleshooting.md#intel-arc-gpus-are-monitor-only)). An
  AMD RX 6000 or older can be tested and reset but no profile drives it, and an
  RX 7000 or 9000 needs a kernel parameter first
  ([Driver Setup § AMD GPU](../driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3)).
- **Many newer boards need an out-of-tree driver,** maintained outside the kernel
  and rebuilt for every kernel ([Driver Setup](../driver-setup.md)), and some
  headers stay read-only even then
  ([Hardware Troubleshooting](../hardware-troubleshooting.md#all-my-hwmon-headers-show-as-read-only)).
- **The BIOS or the board's embedded controller can take a header back** while
  Ventulus drives it
  ([Hardware Troubleshooting](../hardware-troubleshooting.md#the-bios-keeps-taking-fan-control-back)).
- **On some dual-chip Gigabyte boards a second fan chip can vanish** until the
  machine is powered down at the wall
  ([Hardware Troubleshooting](../hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)).

## Hardware that behaves differently

- **Dell machines with one BIOS fan switch** (`dell_smm`) hand every fan to the BIOS
  or none: a profile should control all of them or none of them.
- **An ARCTIC Fan Controller** has no fan curve of its own, and every write carries
  all ten channels, so a channel your profile does not control runs at full speed.
  Control all ten to keep them quiet
  ([Profiles and Curves](../profiles-and-curves.md)).
- **A pump on an OpenFAN channel, or on a header with a generic name,** cannot be
  recognised as a pump: give it the pump role, or it is treated like a chassis fan
  ([Controls § Fan roles](../controls.md#fan-roles-assign-roles)).
- **A fan speed is what the board reports.** With a splitter, the RPM is one fan's;
  many pumps run their own speed during startup; many boards update a reading only
  every second or two ([Fan Tests](../fan-tests.md)).
- **An OpenFAN controller that lost its 12 V supply** restarts every fan at about
  1000 rpm; the daemon writes each speed again when it reconnects.

## What the service cannot do

- **Pick up a newly loaded fan driver while it runs.** A rescan lists new sensors,
  but new fan headers need `sudo systemctl restart ventulusd`.
- **Guarantee that hardware obeyed a hand-back.** A chip or card that has stopped
  accepting writes cannot be given back, and a kernel panic or a power cut runs no
  hand-back at all; the BIOS takes the fans back at the next boot
  ([Safety and Recovery](safety-and-recovery.md#what-happens-when)).
- **Give back OpenFAN fans after a crash.** systemd's backstop cannot reach the
  controller, so those fans keep their last speed until the daemon is back.
- **Detect every cooling failure with the CPU emergency.** Its limit sits above the
  CPU's own throttling point on purpose; the coolant limit, the pump stall response
  and an advisory cover the gap
  ([Understanding Motherboard Fan Control § What keeps your machine safe](../understanding-fan-control.md#what-keeps-your-machine-safe)).
- **Tell local users apart.** Every local user can control the fans and run every
  test ([Permissions and Security](security.md#the-trust-model)).
- **Run more than one daemon per machine.** A second refuses to start.
- **Give the fans back after a crash without systemd.** That backstop is part of the
  service unit, so a daemon you run by hand and then kill leaves its headers as they
  were until a reboot or `sudo ventulus-restore-auto`. The packages also need a
  supported distribution ([Installing](install.md#distributions-that-are-not-supported)).

---

Back to [Administration](README.md)
