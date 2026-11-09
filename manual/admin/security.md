# Permissions and Security

What Ventulus trusts, who can do what, and which permissions it needs. To report a
vulnerability, see the [GUI's](https://github.com/Plan-B-Development/ventulus/blob/main/SECURITY.md)
or the [daemon's](https://github.com/Plan-B-Development/ventulusd/blob/main/SECURITY.md)
security policy; the daemon's also lists each boundary in technical detail.

## The trust model

- **The daemon runs as root**, under a systemd unit with a hardening set
  (`ProtectSystem=strict`, `NoNewPrivileges=true`, a system-call filter, a device
  allow-list and more). It writes only fan speeds under `/sys/devices`, its own state
  and runtime directories, and the OpenFAN controller's serial port. It never opens a
  network socket and never runs code a client supplies.
- **Its socket, `/run/ventulus/ventulus.sock`, is open to every local user**
  (mode `0666`) and has **no authentication**. The machine's local users are trusted:
  anyone who can log in can do everything the app can. That includes applying or
  stopping a profile, taking a short manual override, stopping a fan for a few
  seconds to identify it (never a pump), assigning header roles (which can only add
  protection, never remove it), changing the daemon's runtime settings within their
  limits, and starting every hardware test, `ventulus-diag`'s included.
- **What no client can do**, whoever runs it: write a fan speed directly, lower a
  safety floor, turn off the thermal emergency, stop a pump, or make the daemon read
  another user's files (a profile folder must sit in the caller's own home).
- **A local user can slow the daemon's API down.** Holding many connections open,
  or sending large requests, can make the app and the tray wait or stop answering.
  It cannot use up what the daemon's fan writes need: the daemon serves a limited
  number of connections at once, closes idle ones, keeps file handles free for its
  fan writes, bounds the memory a request can take, and is protected from the
  kernel's out-of-memory killer.
- **The app, the tray and `ventulus-diag` run as your own user** and need no group,
  no `sudo` and no special permission. None of them touches hardware: every read and
  write goes through the daemon.

Moving the longer hardware tests out of the app into `ventulus-diag` made them
harder to start by accident; it did not change who can start them. To tell a test
apart from normal fan control afterwards, the daemon logs every request that starts
a test which changes fan speeds, with the user id and process id of the program
that sent it, and again with its answer
([Logs and Bug Reports](logs-and-bug-reports.md#the-daemons-journal)). Those ids
name the caller; they grant nothing.

If your machine has local users you do not trust with its fans, Ventulus is not
built for it: there is no supported way to restrict the socket.

## What not to do

None of these is ever needed, and each one widens what can go wrong:

- **Do not run the app or `ventulus-diag` with `sudo`.** They need no privilege. A
  message that asks you to change a permission is a fault to report, not an
  instruction.
- **Do not `chmod` files under `/sys/class/hwmon` or `/dev`,** and do not add
  yourself to a group to reach a fan. Only the daemon writes fans, and it runs as
  root.
- **Do not loosen the service's sandbox** with a drop-in (`ReadWritePaths=`,
  `ProtectSystem=`, `DeviceAllow=`, `CapabilityBoundingSet=`), except the
  [opt-in features](#opt-in-features) below, each of which grants one narrow thing.
  A drop-in that overrides `ReadWritePaths=` is the usual reason fan writes fail with
  *Read-only file system*
  ([Hardware Troubleshooting](../hardware-troubleshooting.md#a-fans-speed-shows-but-the-fan-cannot-be-controlled)).
  The sandbox also keeps the daemon out of the DKMS build tree, by design: when a
  kernel update leaves the wrong driver loaded, it tells from the loaded module and
  suggests `dkms status`, rather than reading the tree.
- **Do not write to Super-I/O or embedded-controller registers by hand**
  ([Safety and Recovery § What this manual does not recommend](safety-and-recovery.md#what-this-manual-does-not-recommend)).

## Device access

**Motherboard headers and GPU fans** need nothing: the daemon runs as root, and the
unit lets it write the device tree.

**The OpenFAN controller** needs nothing either. The unit lets the daemon open
`/dev/ttyACM*` and `/dev/ttyUSB*` (`DeviceAllow=char-ttyACM rw` and
`DeviceAllow=char-ttyUSB rw`), it runs as root so no serial group is involved, and
it finds the controller among those nodes by itself. A `/dev/serial/by-id/` link to
one of them is the way to pin the port in `daemon.toml`. Two cases need more:

- A controller on another kind of node needs a drop-in that adds its device class:

  ```bash
  sudo systemctl edit ventulusd
  # Add, for example:
  #   [Service]
  #   DeviceAllow=char-ttyS rw
  ```

- A specific group or mode on the device node, for your own tools, needs a udev
  rule. It is never needed for Ventulus. The package installs an example, as
  documentation only, at `/usr/share/doc/ventulusd/99-ventulus.rules.example`;
  copy it to `/etc/udev/rules.d/99-ventulus.rules` and edit the copy (an upgrade
  overwrites the example). Set its group to your distribution's serial group:
  `uucp` on Arch, `dialout` on Debian, Ubuntu and Fedora. The daemon opens only
  `/dev/ttyS*`, `ttyUSB*`, `ttyACM*`, `ttyAMA*` and `/dev/serial/` paths, so a
  custom symlink such as `/dev/ventulus-controller` is refused.

  ```bash
  sudo install -m644 /usr/share/doc/ventulusd/99-ventulus.rules.example /etc/udev/rules.d/99-ventulus.rules
  udevadm info --attribute-walk --name=/dev/ttyACM0 | grep -E "idVendor|idProduct"
  # replace XXXX/YYYY in the copy with those, set GROUP, then:
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=tty
  ```

## Opt-in features

Three features need the daemon to reach something its sandbox otherwise keeps from
it. Each is off by default, and each needs a systemd drop-in that the package ships
as an example only, under `/usr/share/doc/ventulusd/`:

| Feature | What its drop-in grants | Also needs | Steps |
|---|---|---|---|
| Super-I/O port probe: identifies a fan chip no driver has claimed | Raw I/O port access (`/dev/port`, `CAP_SYS_RAWIO`). The probe reads the chip-ID registers and writes only the standard enter and leave sequences | **Super-I/O port probe** on in Settings (`[detection] allow_port_probe`) | [Settings § Daemon Configuration](../settings.md#daemon-configuration) |
| NVIDIA telemetry: GPU temperature and fan duty through the proprietary driver's NVML | Read and write access to the NVIDIA device nodes, which NVML needs even to read; the daemon calls only NVML's read functions | **NVIDIA telemetry** on in Settings (`[detection] enable_nvidia_telemetry`) | [Settings § Daemon Configuration](../settings.md#daemon-configuration) |
| Writing OpenFAN firmware: the daemon writes a firmware update itself instead of you copying the file | Read and write access to USB devices (`DeviceAllow=char-usb_device rw`). It writes only the published releases Ventulus knows, to the controller's own board | Nothing | [OpenFAN Controller § Letting Ventulus write the firmware](../openfan-controller.md#letting-ventulus-write-the-firmware-optional) |

With any of them installed, **every local user** can use that feature, as with the
rest of the socket. To remove one, delete its file from
`/etc/systemd/system/ventulusd.service.d/`, then
`sudo systemctl daemon-reload && sudo systemctl restart ventulusd`.

## Network access

The daemon never uses the network. The app makes no network connection unless you
turn on its update check (Settings ▸ [Updates](../updates.md), off by default), which
fetches one signed file and, when you ask, a release download. The support bundle
is saved to a file or copied, as you choose; nothing is sent anywhere.

---

Back to [Administration](README.md)
