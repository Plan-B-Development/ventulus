# Fan Tests and Reports

Ventulus can check that a fan really responds, map which header drives which fan,
measure how a fan behaves across its range, and record what your cooler does over
time. This page covers every one of those tools and what their results mean. For
the symptom-first view (*my fans do not show up*, *my fans run at full speed*), see
[Hardware Troubleshooting](hardware-troubleshooting.md).

## Where the tests are

| Test | Where | What it answers |
|---|---|---|
| [Test PWM Control](#test-pwm-control) | **Test Control** on each header card on the **Hardware** page; **Test PWM Control** and **Verify All Writable** under **System State ▸ Advanced actions** | Does a write reach the fan at all? |
| [Characterise PWM Response](#characterise-pwm-response) | **Characterise** on each header card, **Characterise Pump** on a cooling-device card; also under **System State ▸ Advanced actions** | How does the fan respond across its range? |
| [Discover Control Path](#discover-control-path) | **Discover Control Path** on each header card | Which fan does this header actually drive? |
| [Calibrate OpenFan Channel](#calibrate-openfan-channel) | **Hardware ▸ Hardware Diagnostics** | Where does an OpenFan fan stop, and where does it start again? |
| [Test GPU Fan Control](#test-gpu-fan-control) | **System State ▸ Advanced actions**, when a writable AMD GPU is present | Does the GPU fan follow a curve? |
| [PWM Test Report](#pwm-test-report) | **Hardware ▸ Hardware Diagnostics** | All of the above for the headers you choose, written down as a report |
| [Recording sessions](#recording-sessions) | **Hardware ▸ Hardware Diagnostics** | What does the cooler do at startup, under load and across changes? |

A test that your hardware or daemon cannot run is disabled, with the reason in its
tooltip. To find which physical fan is which, use the [Fan Wizard](fan-wizard.md)
instead.

## What the daemon guarantees during a test

Every test runs inside the daemon. Ventulus asks for it and shows the result, but
never writes a fan speed itself, so these rules hold whatever the app does:

- **One test at a time.** The daemon runs one hardware test at a time. While a test
  started from a header card is running, every header card's tests are unavailable,
  and while a PWM Test Report runs, every other test on the **Hardware** and
  **System State** pages is unavailable too.
- **Heat stops a test.** No test starts while any temperature sensor reads above the
  daemon's diagnostic limit (85 °C), or while its thermal protection is forcing the
  fans. The motherboard-header tests also refuse when the temperature readings have
  gone stale. The longer tests stop if any of this happens mid-run. Thermal
  protection overrides every test, all the time.
- **Pumps are protected.** No test drives a pump below its floor: 30 %, or 70 % for a
  pump on a header running in DC mode. The daemon clamps every duty, and nothing the
  app sends can lower that floor. The two tests that look for where a fan stops
  (the PWM Test Report's stall probe and Calibrate OpenFan Channel) refuse a
  pump-protected header or channel outright. If a header becomes pump-protected
  while a test runs, because you assign it the pump role or activate a profile that
  names it a pump, the test stops and the header is put back at no less than 30 %.
- **The fan is put back.** When a test ends, the daemon restores the speed the fan
  had before: when it finishes, when you cancel, when a write fails, and when
  something else takes the header. Closing the window, or Ventulus crashing, does
  not leave a fan at a test speed.
- **When it cannot put the fan back,** it leaves it faster rather than slower. While
  thermal protection is forcing the fans, the forced speed stays until it releases.
  If the daemon is stopping, it hands each motherboard header back to the board's
  own control. The result says which happened. A result with a **Restore:** line
  means the daemon could not put the header back: another test took it over, the
  daemon was stopping, or the restoring write failed (the daemon cannot say which).
  The line names the test duty and the duty from before; if the fan stays at the
  test duty, activate your profile again.
- **Curves pause.** While a test runs, curve control is paused and each fan holds its
  last speed.

**Fan mode names.** Wherever Ventulus shows a header's `pwm_enable`, it uses the
kernel's meanings: **0** is *Full speed (no control)*, **1** is *Manual* (what the
daemon sets when it takes a header over), and **2 and above** are *Automatic
(firmware)*. Which automatic mode a number means differs between chips, so the
number stays beside the name.

## Test PWM Control

On many boards it is unclear whether a write reaches the fan at all. The board may
accept the write and then have its embedded controller (EC) or BIOS override it a
moment later: the classic *Linux says 50 %, the fan still runs at 100 %* problem.

**Test PWM Control** writes a clearly different duty to one header, waits about 6
seconds, then reads back what happened. **Verify All Writable** on System State runs
it on every writable header in turn. The result is one of:

| Result | Meaning |
|--------|---------|
| **PWM control is working correctly** | The write took effect and the RPM responded. The header is controllable from Linux |
| **BIOS/EC reverted pwm_enable** | The board's firmware switched the header from manual back to automatic during the wait, so fan control is being overridden. This is the usual failure on Gigabyte / AORUS boards with Smart Fan 6. See the [AMD Motherboard Fan Control Guide § Gigabyte](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) |
| **PWM value was clamped or ignored** | The write was accepted, but the duty the hardware reports back differs from the one written. Often a partial BIOS override |
| **PWM accepted but RPM did not change** | The write took effect, but the fan did not respond. The header has nothing connected, the fan is stalled, or there is no tachometer to confirm |
| **PWM accepted; RPM readback unavailable** | The write looks fine, but the board has no RPM reading for this header to confirm it |
| **PWM readback failed** | Reading the header back after the write returned nothing, and there was no usable RPM reading either. **This is not evidence that the write failed.** It is almost always transient: run the test again. If it repeats, check `dmesg` for the sensor chip's driver; a chip removed or unbound mid-test produces exactly this |
| **The header became pump-protected during the test** | The test stopped before measuring anything and put the header back, never below the 30 % pump floor. Nothing was learned; run it again if you still want the answer |

Under the result, a **Test:** line says what the test did and saw: the duty it set,
how long it waited, the RPM before and after, and whether the header's fan mode
stayed *Manual*. Ending on *Automatic (firmware)* is the BIOS or EC taking the header
back; on a driver that reports a 100 % duty as *full speed*, a passing test says so
rather than calling it a reclaim. A **Next step** tailored to the result and your
board vendor follows where there is one. **Show test evidence** opens the
before/after table behind that line: the fan mode with its raw value (for example
*Automatic (firmware) — mode 5*), the duty read back, and the RPM. A value the daemon
did not report shows a dash, never a zero.

**The daemon keeps each header's latest result**, across restarts and whichever
program or validation session ran the test. *PWM control is working correctly*
records the header as verified. *BIOS/EC reverted pwm_enable*, *PWM value was clamped
or ignored* and *PWM accepted but RPM did not change* record it as failed. The other
results, and any result with a **Restore:** line, leave the previous result in place,
because what the test read may not have been the header's own doing. A completed
**Characterise PWM Response** sweep counts too: verified when every duty held and the
fan followed, failed when a duty was put back or the header left manual mode. The
**Hardware** page's readiness checklist uses these results: *PWM control not yet
verified* counts the writable headers still untested, and *PWM control failed
verification* stays while any header's latest result is a failure. Test that header
again once the cause is fixed.

## Characterise PWM Response

**Test PWM Control** answers one question at one duty. **Characterise PWM Response**
answers the fuller one: *how* does this header respond across its range? It is the
deeper test to reach for when a fan or pump behaves oddly rather than plainly not
working. It tells you nothing new about a header that is clearly reverted.

The window opens on the same **safety preflight** as
[Discover Control Path](#discover-control-path), so you see the daemon's verdict
before anything moves. The sweep then runs the header **down from its top duty and
back up again**, holding each step until it settles. Rows appear as they are
measured, and you can stop at any point. For each step you see the duty asked for
and read back, the RPM, the header's fan **Mode** at that moment, and **Response**
and **Settling** times. A header the daemon did not report a mode for shows a dash,
which is not the same as *Full speed (no control)*.

### Three separate verdicts

| Verdict | Question it answers |
|---------|--------------------|
| **PWM command** | Did the write itself succeed? |
| **PWM readback** | Did the header report the duty back correctly? |
| **RPM response** | Did the fan actually change speed? |

They are separate because a pump can accept a duty, report it back perfectly and
still run at whatever speed it likes: many AIO pumps drive themselves during startup
or when their own thermal protection is active. That combination is reported as a
possible device override, not as a failed write:

> Some pumps temporarily override PWM during startup or internal thermal-protection
> behaviour. If RPM does not follow PWM, allow that behaviour to finish before
> concluding that control is unavailable.

If you have just powered the machine on, give the pump a minute and run it again.

### What else it reports

- A **summary**: the safe tested range, the effective control range (where a change
  of duty changes the speed), the reported RPM range, hysteresis, RPM stability, and
  response and settling time.
- A **response curve** with both directions plotted, flat regions shaded and the
  saturation point marked, plus an expandable block of engineering detail (sample
  interval, measurement resolution, standard deviation, tach dropouts and outliers).
- **Hysteresis**: whether the fan settles at a different speed approaching a duty
  from above than from below. Some hysteresis is normal: a built-in controller, a
  firmware clamp, temperature-dependent behaviour and tach scaling all explain it.
- A **non-monotonic response** (speed that does not rise steadily with duty), a
  **dead zone** (speed flat at the low end) or a **PWM clamp** (the same duty read
  back for several requests). Each is an observation; plenty of healthy fans and
  pumps are non-linear.
- **Interference**: another controller taking the header back mid-test. The run stops
  and says so, because readings taken while something else drives the header mean
  nothing.

**Timings come at the resolution they were measured at.** The daemon reads the
tachometer twice a second, and many motherboard chips update the reading only every
second or two, so a time reads "~2 s (tach updates every 1 s)", never "1,483 ms".
When the update rate could not be established, the resolution reads *unknown* and
times are given in whole seconds. A step still changing when its time ran out shows
**Not settled**: there is no steady reading yet, which is not a fault.

**Reported RPM is what the motherboard says**, not necessarily what the pump is
doing. If a reading falls outside what earlier runs established for the header, you
get a cautious note listing the likely explanations (internal control, a clamp,
startup behaviour, thermal protection, different tach scaling) rather than an error.

### Its own safety rules

Beyond [the shared guarantees](#what-the-daemon-guarantees-during-a-test): the sweep
never drives a header to 0 %, and a run that stops early never leaves the fan slower
than it found it, because the daemon restores the original speed on the way out. The
one exception: if the fan's driver stops answering (a reading does not come back
within 2 seconds), the test stops and the daemon writes nothing more to that fan,
since a write to a driver that has stopped responding could stall control of every
motherboard fan. The fan then stays at the test speed it was on, never below 20 %
(30 % for a pump), until your profile drives it again, and the result says the speed
was not restored.

## Discover Control Path

The other tests assume that `pwm5` drives the fan reported on `fan5_input`. That is a
naming convention, not a measurement, and on real boards it is often wrong: a
splitter puts two fans on one tachometer, a Y-cable puts a fan's tachometer on a
channel with no PWM, and some vendors do not line the numbers up.

**Discover Control Path** measures the relationship instead. It nudges one header up
or down a little, watches **every** fan tachometer on the board, and reports which
ones responded and how confident it is.

### The safety check comes first

The window opens on a **safety preflight**, the list of what the daemon checked
before anything moves:

```text
Safety preflight
Pump role             Confirmed
Safe minimum          30%
Temperature source    CPU Package · fresh
PWM ownership         Available
Original state        Captured
Supporting cooling    Available

Ready to test
```

If something is unsafe, **Start is disabled and the window says why**: the system is
too hot, thermal protection is active, another test is running, the header is
read-only, or the temperature readings have gone stale. The verdict is the daemon's;
Ventulus shows it and cannot talk the daemon into running something it refused.

### What it reports

```text
PWM4 → fan2_input
Relationship confidence: HIGH
Direction: positive
Baseline: 1350 RPM
Perturbed: 1775 RPM
Observed change: +31%

Other tach channels:
fan1: no meaningful response
fan3: no meaningful response
```

The channels that did **not** respond are listed on purpose: "fan1 did not respond"
is evidence, while a channel missing from the list is indistinguishable from one
nobody looked at.

| Result | What it means |
|--------|---------------|
| **Confirmed** | One channel responded in every cycle, clearly more than anything else moved |
| **Probable** | One channel responded every time, but another moved by a comparable amount |
| **Ambiguous** | A channel responded in some cycles and not others, which is not repeatable enough to rely on |
| **Multiple responses** | Several channels responded together. Normal for a splitter, and it means the mapping is not one-to-one |
| **No tach response** | Nothing moved. **This is not a fault.** The header may drive nothing with a tachometer, or drive something under its own control, which is what an AIO pump does during startup |

A successful answer is kept: **Details** on the header card shows the relationship,
its confidence and when it was last checked. The record is discarded if the header
stops existing (a new board, a driver change, or the chip starting to publish
labels), so a mapping is only ever shown for the same hardware.

If the telemetry update rate reads **unknown**, that is a real answer. Many
Super-I/O drivers do not publish how often they refresh a reading, and Ventulus
will not pass its own sampling rate off as the hardware's.

### Why it does not just stop the fan

The classic Linux tool for this, `pwmconfig`, stops each fan in turn and watches for
the tachometer that drops to zero. That works, and it is the most dangerous thing you
can do to a liquid cooler. Discover Control Path does not do it and cannot be made
to:

- The nudge always moves away from whichever limit is nearer, so a pump idling near
  its floor is nudged *up*, never down toward a stall.
- No header is ever driven to 0 %, and a pump never goes below its floor.
- A pump whose tachometer stops reporting mid-test ends the run at once, and the
  header is put back.
- It runs two cycles, not one, so a fan that drifted while the test watched is not
  mistaken for one that responded.

## Calibrate OpenFan Channel

**Calibrate OpenFan Channel…** measures two things about one fan on an OpenFan
Controller: the duty at which it **stops** as its speed is lowered (the *stall
duty*), and the duty at which it **starts again** as its speed is raised (the
*restart duty*). The second is usually higher: a fan that is already turning keeps
turning at a duty that could not start it from a stop.

It walks the channel down from 100 % in 10 % steps to 30 %, then in 2 % steps until
the fan is confirmed stopped, then back up in 2 % steps until it is confirmed
spinning. Each step is held for a few seconds and judged on three fresh RPM readings.
A typical fan takes 1.5 to 2 minutes, about 3 at most. The window plots the way down
and the way back up as two lines, so the gap between them shows, and lists every
step.

### The pump question

The walk takes the fan to 0 %. A channel you have set to **Pump** (Hardware page ▸
*OpenFan Channels*) is listed as *pump, not calibrated* and cannot be started, and a
run under way stops if you set its channel to Pump. For any other channel the daemon
has no way to tell whether it powers a pump, so it will not start until you tick
**"… does not power a pump"** for the channel you picked. The tick clears whenever
you pick another channel and after every run. **Do not calibrate a channel that
powers a pump.**

### What it tells you

- **Stops at** and **Starts again at**: the two duties, and the gap between them.
- **The minimum to use.** When both were found, the window says *"Keep this fan's
  minimum at N% or more to keep it running"*, where N is the **restart** duty. A
  minimum just above the stall duty keeps a spinning fan spinning, but a fan that is
  already stopped (at boot, or after a 0 % point on a curve) starts again only at the
  restart duty.
- **The fan never stopped**: it kept spinning even at 0 %, so any minimum keeps it
  running.
- **The fan did not start again on its own**: it was still stopped at the top of the
  way back up, so no minimum is recommended. The daemon then runs it at 100 % to start
  it; if even that fails, the result says so, and the fan may be stuck or
  disconnected.
- **No fan detected**: the channel read 0 rpm at 100 %.

### Its own safety rules

Beyond [the shared guarantees](#what-the-daemon-guarantees-during-a-test): the
calibration also refuses to start, or stops, when there is no fresh CPU temperature,
and stops if the CPU warms by more than a few degrees while the fan is slowed. **A
fan is never left stopped**: if a run ends early at a point where the fan may be
stopped, the daemon runs it at 100 % until it is seen spinning, then restores its
original speed. If the daemon is shutting down before it could confirm the fan had
restarted, it leaves the channel at 100 %. Closing the window while the walk runs
asks whether to **stop the calibration** or **keep it running**; either way the
daemon restores the channel when the run ends.

## Test GPU Fan Control

AMD GPU fan control fails *silently* more often than motherboard headers do: the
driver accepts a `fan_curve` write and the firmware ignores it (`amdgpu.ppfeaturemask`
is missing bit `0x4000`), or a BIOS overdrive lock blocks it. The GPU rows of
**System State ▸ Safety & GPU Limits** can show a configuration that looks right
while fan control still does not work.

**Test GPU Fan Control** drives the GPU fan to a test speed, always *upward* so it
never reduces cooling on a hot GPU, waits about 6 seconds, reads back the applied
`fan_curve` (or `pwm1` on an RX 6000 or older) and the RPM, then restores the
previous state. It is shown only when a writable AMD GPU is present. The result is
one of:

| Result | Meaning and fix |
|--------|-----------------|
| **GPU fan control is working** | The fan responded. Nothing to do |
| **Zero-RPM idle (normal)** | The curve applied, but the fan stays stopped because the GPU is below its zero-RPM stop temperature. It spins up under load. Shown only when the card reports zero-RPM idle as enabled; otherwise the result is a warning asking you to test again with the GPU under load |
| **No RPM sensor to corroborate** | The write was confirmed by reading the curve back, but this GPU has no RPM reading to measure |
| **The GPU ignored the write** | Accepted but not applied. Add `amdgpu.ppfeaturemask=0xffffffff` to the kernel command line and reboot ([how](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3)); if it is already set, suspect a BIOS overdrive lock and check the GPU advisories on **System State**. The "SMU driver interface version" message some RDNA4 cards log is not itself a fault |
| **Fan did not respond** | The curve applied, but the RPM did not change with zero-RPM idle off. Check the fan is connected. A few cards have per-unit fan faults that no kernel change has been shown to fix (some R9700s, [ROCm #6101](https://github.com/ROCm/ROCm/issues/6101)): watch the fan's RPM under load and consider a warranty claim |
| **GPU fan left manual mode** (RX 6000 and older) | Something other than the test changed the card's fan mode, usually another GPU fan tool (LACT, CoreCtrl, amdgpu-fan): stop it and test again. The `amdgpu` driver also hands the fan back to the card when the GPU re-initialises (resume from suspend, a GPU reset). Motherboard BIOS settings do not drive a graphics card's fan |
| **Write was rejected** | The driver or firmware refused the write. Check that `amdgpu.ppfeaturemask=0xffffffff` is set and that `amdgpu` (not `vfio-pci`) is bound to the GPU |

As with the header test, a **Test:** line says what speed was set, through which
interface, how long it waited and the RPM before and after, and **Show test
evidence** opens the before/after table. The card's minimum fan speed (often around
15 %, higher on some cards) and zero-RPM idle are reported as information, never as
failures. If the button is missing, the GPU has no write path (see
[*GPU fan control says feature_unavailable*](hardware-troubleshooting.md#gpu-fan-control-says-feature_unavailable)).

**Restore GPU Fan to Automatic**, beside it, hands the fan back to the card's own
curve. It is disabled while the active profile drives that GPU. Afterwards the daemon
leaves the fan alone, even if a profile names it, until a profile is next activated
or the daemon restarts.

## PWM Test Report

**Hardware ▸ PWM Test Report…** checks your cooling setup and writes down what it
actually saw. It runs the same daemon tests as the buttons above, one at a time, and
the daemon performs and undoes every one of them.

1. **What to test.** Every channel the daemon reports is listed. For each motherboard
   header you tick the tests to run. The **PWM control test** and **tach pairing**
   start ticked on headers with a fan turning. The **full PWM sweep** (100 % down to
   20 % and back, never below a pump's floor) and the **stall/restart probe** are your
   choice. The probe looks for where a chassis or radiator fan stops below 20 % and
   where it starts again. It is offered only on a header whose **role** is chassis fan
   or radiator fan, never on a pump-protected header or a CPU fan, whatever the
   header's label says. **Set…** in the **Role** column opens the same role picker as
   the Hardware page's header cards, so you can name an unlabelled header here; the
   table refreshes and keeps your ticks, and it also follows a role you set on a
   Hardware card while it is open. A test that cannot run says why in its tooltip.
   OpenFan channels and GPU fans are reported but not tested.
2. **Your setup (optional).** What software cannot see: what is plugged into each
   header, how many fans share it (with a splitter, the RPM is one fan's), the BIOS
   header mode, and your cooler's model and pump switch position. Anything you leave
   blank is recorded as *not supplied*. Your answers are remembered for this machine
   and never included in a settings export.
3. **Review and consent.** The plan in plain words, what keeps it safe, and your
   go-ahead. Each stall probe also needs its own **"I'll stay at the machine"** tick,
   because the fan may stop for a short time.
4. **Run.** Each test with its status, the fan under test live, the thermal state and
   the time remaining. **Cancel run** stops the current test (the daemon puts the
   header back) and lists the rest as not tested. The whole run stops if the daemon's
   thermal protection becomes active. A single test stops if a temperature passes the
   diagnostic limit or readings go stale; the run carries on, but each later test is
   refused while that lasts and is listed as not tested. Closing the window asks
   first; quitting Ventulus saves what was done so far.
5. **Report.** There is **no overall pass or fail**. You get what needs attention,
   observations, whether every header went back to how it was found (with **Re-apply
   profile** if one did not), a section per fan with charts and every reading, what
   was *not* tested and why (including things no report can test, such as suspend and
   resume), and the environment: GUI, daemon, kernel and driver versions, board and
   BIOS. Every finding says what it is based on (measured, worked out, reported by the
   device, or told by you) and the range it covers: a sweep from 20 % proves nothing
   about 10 %, and the report says so, especially when your profile can drive a fan
   lower than any test saw it turning.

On a board with two fan chips, two headers can share a name such as `pwm2`; the
report adds the chip (`pwm2 (it8696)`), or the channel id where the chip cannot tell
them apart.

The report will not start in demo mode, while thermal protection is active, or while
another test or a validation session is running; the message names the page the
other test was started from. A validation session window that was already open stays
open, but its **Start** is refused until the report finishes.

### Your reports

Reports are saved as you go to `~/.local/share/ventulus/reports/` and are never
deleted automatically. The window opens on a list of them, newest first, and also
opens in demo mode for this. Select one to **Open** or **Export** it, two to
**Compare** them, or **Delete…** ones you no longer want. **Open a report file…**
shows a report from elsewhere (another machine, or one someone sent you) without
copying it into your folder. A reopened report shows the machine as it was *then*,
so it does not offer **Re-apply profile**.

**Export** offers:

- **JSON**: the complete record.
- **Markdown**: for a GitHub issue. Attach the file rather than pasting it if it is long.
- **HTML**: one file with charts (each sweep and stall probe, each tested fan's RPM and
  duty over the run, the hottest CPU temperature). It follows your light or dark
  setting, needs no internet connection and runs no scripts.
- **CSV**: up to three spreadsheets in a folder you choose (sweep points, stall-probe
  steps, and the once-a-second trace of every fan and sensor). A reading the daemon
  did not report is left empty, never 0.

**Compare** puts two reports side by side, earlier first. Fans are matched only by
their exact header id; a header whose label changed between runs is listed as
*possibly renamed* and not compared, so a reading is never pinned to the wrong fan.
Differences are grouped into hardware and wiring, environment, configuration,
measured response, and *not comparable* (a test that ran with different settings, ran
in only one report, or started in a different thermal state). Measured differences
are shown beside how much each run's own readings varied; nothing is labelled
significant and there is no overall verdict. A comparison exports as Markdown or HTML.

## Recording sessions

Three recorders watch your cooler over time instead of testing one header. They need
a cooling device, which **Configure AIO…** on the Controls page sets up.

- **Startup / Lifecycle Recording** records how the cooler behaves across startup,
  resume and profile changes.
- **AIO Validation** records what the cooler actually does and finalises into an
  evidence summary you can export as CSV or JSON.
- **Thermal Observation** records how the cooler responds to a workload **you** run.
  Ventulus does not start, stop or control the workload, and nothing in this
  recording drives a fan or pump: start your game, render or stress test, then
  record. While it runs you see elapsed time, control temperature, CPU package power,
  pump and radiator duty and RPM, the temperature trend, and whether the temperature
  has reached a steady state. When you stop it you also get:
  - **Steady state**: whether the temperature settled, with the mean, peak, trend,
    variation, warm-up time and the rule behind the verdict. *Not established* means
    this recording did not settle, not that your cooler cannot; a run stopped early
    looks the same.
  - **Startup behaviour**: if the fans or pump spun up hard and then came down, the
    peak and settled RPM, how long it lasted, and the duty commanded and read back
    meanwhile. A high startup RPM is not a fault when the duty was obeyed; many coolers
    ramp at power-on by design.
  - **Timeline**: temperature and RPM over the recording, with the steady period
    shaded and CPU and GPU power beneath.

  **Isolation templates** step you through the two comparisons cooler reviews use:
  *pump influence* (hold the fans, vary the pump) and *radiator influence* (hold the
  pump, vary the fans). Each stage tells you which duty to set; you set it on the
  Controls page as usual, and Ventulus marks the timeline. The session window stays
  open while you use the rest of the app, so you can do that and come back. It will
  not advance while thermal protection is active or while it cannot read a
  temperature. If CPU package power shows a dash, your machine does not expose it
  (AMD systems on `k10temp` commonly do not); everything else still works.

**A session records until you stop it.** The diagnostics you tick take seconds to a
couple of minutes each, but finishing them does not end the session, and neither does
closing the window. Left alone it records until you press **Stop & Save**, or until
the daemon's sample cap, about two hours in. While one is recording, the footer shows
a **Recording** chip with the sample count; click it to get back to the session.

**"Stop the session automatically when the diagnostics finish"**, on the start form,
ends it as soon as the last diagnostic completes. It starts ticked for **AIO
Validation**, which exists for its diagnostics, and unticked for the two passive
recorders. It is unavailable until you tick at least one diagnostic.

**Stop & Save** and **Stop & Mark Cancelled** both keep everything: each finalises the
session, works out the findings and saves it. The second only records the session as
*cancelled*, so you can tell an abandoned run from a finished one.

All three recorders open the same window: elapsed time, telemetry per member, a row
for each diagnostic as it finishes and, at the end, a findings table in explicit
words: **PASS**, **FAIL**, **OBSERVED**, **NOT OBSERVED**, **NOT TESTED**,
**UNKNOWN**, **UNAVAILABLE**. Nothing untested is ever reported as PASS, and a
capability your hardware does not expose is *unavailable*, never a failure. A finding
about one member names it, so one check can read **PASS** for the pump and **FAIL**
for a radiator fan, and both are right. You can mark an event while recording and
attach external measurements (a meter or logic-analyser reading); those are kept for
your own analysis and never used for any control or safety decision.

---

Previous: [System Health](diagnostics.md) | Next: [Fan Wizard](fan-wizard.md) | Back to [Table of Contents](README.md)
