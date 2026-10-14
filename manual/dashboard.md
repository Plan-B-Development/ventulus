# Dashboard

The Dashboard is the landing page. It answers the most important questions at a glance:

- What profile is active, and what mode is the system in?
- What are the fans doing?
- What are the sensors reading?
- Is the system healthy?

![Dashboard](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/01_dashboard.png)

The page leads with the **telemetry chart** (the one view nothing else duplicates),
with a compact **card per fan control** beneath it and the **Thermal Sensors** panel
alongside. Drag the splitter handles to trade space between them.

Status lives on the app-wide bars, so it follows you to every page: connection, uptime and alerts on the **top ribbon**;
operation mode, poll freshness, thermal safety and cooling readiness on the **footer**.
If the daemon stops answering, the thermal readings on both bars disappear rather
than freeze on the last one (with no connection there is no current state to show),
and they come back with the first successful poll.

## Page header

The title row carries a **profile selector + Apply** (see
[Profile selector](#profile-selector)) so you can switch profiles without leaving the
page. The sidebar has one too, and either works.

Below it, five banners appear only when they apply:

- **Motherboard fan headers** are missing or all read-only
- **API version mismatch**: the connected daemon's API version differs from the one
  this GUI was built against, a sign the `ventulusd` and `ventulus`
  packages were upgraded out of lockstep. Align the two; some features may otherwise
  misbehave
- **Thermal protection active**: the daemon is applying a minimum fan speed under your
  profile, which still applies wherever it asks for more. The banner says when your
  profile resumes fully: once whatever tripped the emergency cools (the CPU, or the
  coolant on a machine with a coolant sensor), or once a current CPU temperature reading
  returns when there was none. It reports the daemon's state; on a
  machine with no fan the daemon can drive, the state can be active while no fan was
  written
- **Fan control engine**: how the daemon's control loop itself is doing. It is the
  only thing writing fan speeds, and it owns the thermal emergency, so this is the
  banner worth reading first. *Running slowly* means it is late but still driving
  your fans, and needs no action unless it persists. A thermal emergency legitimately
  slows a tick down, because the daemon writes to every fan in turn. *Stopped* means
  nothing is controlling your fans and the emergency protection is not running:
  restart `ventulusd`.
- **Daemon running on fallback settings**: the daemon could not read its own
  `runtime.toml`, the file that holds the settings you made through the app, so it is
  running on built-in defaults rather than refusing to start. Those defaults carry **no
  header roles**: a `pump` role you assigned by hand may not be in effect, and with it
  that header's 30% floor, its stop exemption and its pump-safe identify. That matters
  most on a board whose chip publishes no header labels, where your assignment is the
  only evidence a header drives a pump. The banner says what the failure cost and what
  to do; the daemon's
  [User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#when-runtimetoml-cannot-be-read) has the recovery steps for each
  case. The daemon's full error goes to the GUI log.

## Fan cards

Fans are shown as one card per **fan control** (the group a profile assigns a curve
to) rather than one card per individual fan. That mirrors how control actually works:
the daemon pins speeds per control, so a card always tells you **how many fans it
covers**.

Each card shows:

| Field | Meaning |
|-------|---------|
| **State chip** | Auto (the curve is driving it), Override active, Driver alarm, Low RPM, Stale, Stall, or Offline. It sits beside the fan count. **Driver alarm** means the fan chip itself flags a fan (usually one running below the low-speed limit your BIOS set); hover the chip to see which fan and that limit. It is not an alert, because what raises it depends on the chip. A **Stall** stays on for up to five seconds if the daemon briefly stops reporting on that fan, so one missed reading does not clear it and raise it again |
| **RPM** | Hardware-measured speed, averaged across the control's fans |
| **SPEED** | Last commanded speed. For a read-only GPU that reports no commanded value, the column is headed **DUTY** instead and shows the firmware's *measured* duty, so a measurement is never read as a speed the daemon commanded |
| **TEMP** | The temperature driving this control's curve |
| **Curve preview** | A sketch of the control's own curve, as a band along the bottom of the card |
| **Edit** | Beside the card's name; opens the **Controls** page focused on this control |

A dash (`—`) means the value is genuinely unknown. It is never shown as a real `0`.

**This area shows the fans your profile is actually driving.** A control appears here
while at least one of its fans is reporting. A fan that no control owns does not get a
card. The **Controls** page is where you assign one, and its **Unassigned Fans (N)**
button tells you how many are waiting. If nothing is being driven, the area is simply
empty.

One special card fills in the gap:

- **Read-only fans**: devices with no fan-control write path (typically an NVIDIA or
  read-only GPU fan) get a card each, so you can still read their speed. They have no
  Edit button, because they cannot be assigned to a control.

> **The cards are read-only.** Changing a speed happens on the **Controls** page,
> which owns manual override; the Dashboard shows you what is happening and takes you
> there.

## Telemetry chart

The timeline chart is **dual-axis**: temperatures plot against the left axis (°C) and
fan RPM against the right axis, so you can watch a temperature rise and the fans
respond on one graph.

To keep it readable, the chart **does not show every series at once**. On first run it
shows a curated default: CPU temp, GPU temp, and one case/motherboard temp. From there
you control what's shown:

- **Chart modes**: a selector switches between **Combined** (the curated default),
  **Thermals**, **Fans**, and **Diagnostics**, with a **Reset** to return to defaults.
- **Series selection**: toggle individual sensors and fans on or off from the
  **Sensors** panel's checkboxes (see [Sensors panel](#sensors-panel)).
- **Event annotations**: vertical markers flag transitions the GUI detects between
  polls: a profile change, a reconnect, a thermal transition, an override starting or
  ending, and the onset of a stale sensor or a stalled fan.

The **Range** dropdown selects the time window:

| Range | Use Case |
|-------|----------|
| 30s, 2m | Watching real-time response to load changes |
| 5m, 10m, 15m, 20m, 30m | Observing curve behaviour during a gaming session |
| 1h, 2h | Reviewing longer-term patterns |

The default time range (15m) is configurable in Settings. Each visible series carries a
coloured **latest-value marker** at its newest reading, and **hovering** the chart shows a
crosshair and a themed tooltip listing each visible series' reading at that moment, named
as in the Sensors panel. A series with no reading there (before it started, or in a gap)
is left out rather than reporting a neighbouring one. The tooltip-plate and crosshair
colours are themeable on the **Theme** page. Each series keeps the same palette colour from
one launch to the next unless you pick its colour from the swatch in the Sensors panel, or
with **Change colour…** in a row's right-click menu (the <kbd>Menu</kbd> key or
<kbd>Shift</kbd>+<kbd>F10</kbd> opens it for the selected row); the swatches follow a theme
switch and **Reset colours** in Settings at once.

Readings are placed at the time the daemon took them. A sensor the daemon stops
refreshing adds no new points, so its line ends where its data ends; a line also breaks
across a gap of more than about seven seconds (a disconnect, or a fan that stopped
reporting RPM). The time axis keeps counting while the computer sleeps, so after a resume
the readings from before it sit where they belong, or have aged out of the window.

## Sensors panel

The right-hand **Sensors panel** is always present. Drag the splitter handle between
it and the fan cards to give the chart more width when you need it. It is a grouped,
searchable tree of every **sensor and fan**, grouped
into CPU, GPU, **AIO / Liquid** (liquid-cooler coolant temperatures), Motherboard, Memory (memory-module temperatures), Disk,
and Fans (by source: D-GPU, hwmon, OpenFan). Liquid-cooler pump and radiator fans are
tagged **(AIO)**. Type in the "Search sensors…" box to filter; click a row's checkbox to
show/hide its line on the chart; toggle a whole group to declutter. A reading the daemon
has not refreshed for more than about seven seconds (where its chart line breaks) is
marked **· stale** (hover the value to see how old it is), and a group's **max** counts
only current readings (**max —** when none are). Hidden series persist
across sessions, including for a fan that is currently stopped or a device that is
switched off, which come back hidden rather than reappearing on the chart. Nothing is
forgotten automatically; **Settings → "Settings for missing hardware"** is what clears
the leftovers once hardware is gone for good.

### Naming your fans

OpenFAN channels arrive with no name of their own, so they start out as
**OpenFan CH0**, **OpenFan CH1** and so on. To give one a name that means
something ("Front Intake", "Radiator Push"), **double-click it** in the Sensors
panel (or select it and press **F2**, or right-click it and choose
**Rename fan…**). A fan card that drives a single fan offers the same **Rename fan…**
when you right-click it. The name applies everywhere at once: fan cards, the Overview
table, curve and fan-role pickers.

To go back to the default name, clear the text and press Enter, or right-click and
choose **Reset to default name**. Pressing Enter without changing anything does
nothing at all: it will not quietly turn the displayed name into a custom one.

Two things worth knowing:

- The **(AIO)** tag is not part of the name. You do not need to type it and you
  cannot remove it by renaming. It marks a fan the daemon reports as belonging to
  a liquid cooler.
- Naming a fan also keeps it on screen when **Auto-hide unused fan headers** (Settings) is on, so
  a header that is idle right now stays visible once you have named it. Clearing
  the name lets it drop out of the list again.

If you already named your fans while setting them up in a profile, those names are
picked up automatically, once, the first time Ventulus sees your fans. You do not
need to retype anything. From then on the name lives with the fan, so renaming it here
updates the Controls page too.

To work out which physical fan is which before naming them, use the
**Fan Configuration Wizard** on the [Controls page](controls.md). It stops one
fan at a time so you can see which one slows down.

> In demo mode you can rename fans to try the feature out, but the names are not
> saved. Demo hardware is not real, and your actual fan names are left untouched.
> The same goes for everything tied to hardware (fan zones, chart colours and
> hidden series, Controls card sizes) and for profiles, which demo never writes
> to your profile folder. Ordinary preferences such as the theme, window position
> and chart mode do save. See [Settings](settings.md) for the full list.

> Both the **event log** and the **alerts** live on the [Logs page](diagnostics.md):
> the log table is history, and the alert bar above it is what is wrong right now, with
> the full detail behind **View alerts**. Use the profile selector in the page header to
> switch profiles.

## Profile selector

The profile selector in the page header lists all available profiles (the sidebar
carries the same selector). It reads **No active profile** when none is running: before
you apply one, or after **Stop** in the sidebar. If the daemon is running a profile this
app does not have (one the daemon was started with from its own profile folder), it reads
**Running: <name> (not in this GUI)**. Pick one and click **Apply** to activate it. Activating hands the profile to the daemon, whose
profile engine then evaluates its curves every second and drives the fans, so your
fans stay controlled whether the GUI is open or closed. See
[The Daemon Drives the Fans](profiles-and-curves.md#the-daemon-drives-the-fans).

If the profile cannot be activated (the daemon refuses it, or cannot be reached), a banner
across the top of the window says why: *Could not activate "<profile>": <reason>*, or, for a
profile that controls only some of a Dell machine's fans, which fans to add. The previous
profile keeps running. The banner goes away on your next successful **Apply**.

## Thermal safety states

The daemon has two thermal safety states, and it drives both itself:

- **Emergency**: the hottest CPU sensor reached the emergency limit, or a coolant sensor reached the **coolant limit** set under **Settings**; the chip's
  detail says which. Every OpenFAN fan and
  every writable fan header runs at full speed, including fans no profile controls. The
  daemon holds it until a *current* reading is back down (the CPU at or below 80 °C, the
  coolant 5 °C below its limit), then hands control straight back to your profile. A sensor
  that stops updating or disappears keeps it at full speed.
- **No CPU sensor**: no current CPU temperature for five seconds, with no emergency in
  force. The fans your active profile controls get at least 40 %. Fans no profile controls
  are not touched, and with no profile active nothing is forced.

Both are minimums, not replacements: a fan your profile is already running faster keeps its
speed. GPU fans are never forced (the GPU protects itself) and keep following their
curves. The state shows in the footer's **thermal state** chip (click it for the detail),
as a banner across the top of the Dashboard, and as a marker on the chart. It is also an
**alert**: an emergency is an error alert naming what tripped it (the CPU, the coolant or
both), and the no-CPU-sensor state is a warning. Both count in the footer's health summary
and appear in the Logs page's alert bar and event log. Acknowledging one quietens the alert
badge, but the footer keeps counting it until the daemon reports a normal state. If the
daemon stays unreachable for five seconds, nothing current is known about its thermal
state, so the alert clears and the connection problem is reported instead; a single missed
reading does not clear it. The rules in full are in
[What keeps your machine safe](understanding-fan-control.md#what-keeps-your-machine-safe);
if your fans stay at full speed, see
["Fans run at full speed regardless of profile"](hardware-troubleshooting.md#fans-run-at-full-speed-regardless-of-profile).

Two cooling checks sit beside these states and are alerts too. A **pump stall** (a pump in your profile reading 0 RPM while it should run, which the
daemon answers by running it at full speed) is an error alert naming the pump. The
**cooling advisory** (the CPU held at its ceiling for a minute with every fan and pump running
slowly) is a warning that forces nothing. Both appear in the Logs page's alert bar.

## Disconnected / no hardware states

If the daemon is not reachable, the Dashboard shows a disconnected overlay with a
reconnection message. If the reason is that the `ventulusd` service is installed
but not enabled, the overlay says so and shows the command that enables and starts it,
with a **Copy command** button; run it in a terminal, then re-open the GUI. If the daemon is connected but no controllable hardware is
detected, it shows a "No hardware" message with a button that opens the **Hardware**
page's readiness report, which names the driver or package your board needs.

---

Previous: [Setup Checklist](setup-checklist.md) | Next: [Controls](controls.md)
