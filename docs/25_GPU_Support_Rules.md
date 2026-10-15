# GPU Support Rules

**For contributors.** These are the rules the GUI and daemon code follow for AMD GPU
fan control. Read this file before changing GPU discovery, GPU fan writes, PMFW
handling or GPU display naming. `DEC-` numbers refer to the project's decision log.
For what users see, read the
[Hardware Compatibility Guide](19_Hardware_Compatibility.md#amd-gpu-fan-control).

Rules marked *(Safety-critical)* are the ones whose violation would let a GPU fan be
misreported as controlled, or driven when it should not be.

## Discovery and identity

- AMD dGPU sensors report `source: "amd_gpu"` (not `"hwmon"`), which is used for display grouping.
- GPU identity uses the PCI BDF address (stable across reboots), not the hwmon index.
- Exactly one fan entity per GPU: the kernel exposes only `fan1_input` (an aggregate
  RPM for all physical fans).
- Navi 48 (RX 9070 XT / 9070 / 9070 GRE) has PCI device ID `0x7550`, distinguished by
  revision (`0xC0` = XT, `0xC3` = non-XT, `0xC2` = GRE). Device `0x7551` is the
  workstation Navi 48: Radeon AI PRO R9700 (`0xC0`), R9700S (`0xC1`) and R9600D (`0xC8`)
  (libdrm `amdgpu.ids`; R9700S is listed on libdrm's main branch, after the 2.4.134
  release). A rule keyed on `0x7551` alone therefore covers all three.
- Daemon hwmon discovery excludes `chip_name == "amdgpu"` (and `nouveau`) from the
  hwmon headers (DEC-102, `is_gpu_owned_hwmon_chip`): GPU fans are reached only through
  the `amd_gpu:` / `nvidia_gpu:` ids and the GPU endpoints, never as a motherboard
  header. *(Safety-critical.)* `xe` and `i915` are not on that list yet, because no
  mainline kernel gives them a `pwm` attribute; Intel's pending fan-control series for
  `xe` would, and a kernel carrying it makes the Arc fan look like a header. Adding both
  to the list is pending.

## Write path

- **RDNA3+ GPUs (RX 7000/9000 series) do NOT support `pwm1_enable=1` manual mode**.
  Fan control MUST use the PMFW `fan_curve` sysfs interface. *(Safety-critical.)*
- Pre-RDNA3 GPUs (RX 6000 and older) expose traditional `pwm1_enable=1` + `pwm1`
  control, and the daemon writes it **only** from the GPU fan verify and reset. No
  engine has ever driven it, so no profile controls these fans: `/capabilities`
  reports `fan_control_method: "hwmon_pwm"` with `fan_write_supported: false`, the
  GUI labels the fan "verify only", its picker will not assign it, and a control
  bound to it is listed as `backend_unavailable` (DEC-445). An engine path for them
  is deferred.
- **GPU fans are outside the thermal force, and keep following the profile through it.**
  Neither the 100 % emergency nor the 40 % no-sensor floor is ever written to a GPU fan
  (the GPU firmware owns its own thermal protection). On a forced tick the daemon still
  writes each GPU member its own command (its curve, a manual override, or an identify)
  after the forced writes, so a GPU fan does not freeze at the duty it had when the
  force began. During a force a GPU curve runs without its step-rate limit, like every
  other member's. The write is skipped while a hardware verify holds the write pause and
  once the daemon is shutting down.

  **The two generations reach that outcome by different mechanisms, and the
  difference is safety-relevant** (kernel source re-read 2026-08-26, and again at
  torvalds master on 2026-09-26 for DEC-430: `hwmon_attributes_visible()` only
  masks the read/write bits of `pwm1_enable` when the SMU lacks the mode
  callbacks, and an attribute whose mode ends at 0 is never created):

  - **RDNA4 (RX 9000, `smu_v14_0_2_ppt.c`, SMU 14.0.2 / 14.0.3)** registers only the
    two fan getters, `.get_fan_speed_pwm` and `.get_fan_speed_rpm`. It registers no
    `.set_fan_speed_pwm` and no `.get/.set_fan_control_mode` (re-read at 7.3-rc4). `hwmon_attributes_visible()`
    therefore strips the permissions outright: `pwm1` is read-only and `pwm1_enable`
    is not exposed at all. The rule is **structurally enforced by the driver**.
  - **RDNA3 (RX 7000, `smu_v13_0_0_ppt.c` / `smu_v13_0_7_ppt.c`)** *does* register all
    three callbacks, so **`pwm1` and `pwm1_enable` exist at mode 0644 and are
    writable**. The write lands in `smu_v13_0_auto_fan_control()`, which opens:

    ```c
    if (!smu_cmn_feature_is_supported(smu, SMU_FEATURE_FAN_CONTROL_BIT))
    	return 0;   /* silent success — no-op */
    ```

    So on RX 7000 a `pwm1_enable=1` write **can return success and do nothing**
    (the widely-reported "write 1, read back 2" symptom). **Never treat a successful
    write as proof of control on RDNA3**: any capability probe that does will
    falsely report an RX 7000 fan as writable, which is exactly the class of lie
    the truthfulness rule below forbids. Confirm by reading the value back,
    or use the `fan_curve` path, which is the supported interface either way.
  - **So the daemon fails closed on the device id (DEC-430).** File presence
    cannot tell an RX 7000 from an RX 6000 (both have `pwm1` and `pwm1_enable`),
    so `AmdGpuInfo::can_write_legacy_pwm` refuses every id in
    `is_rdna3_or_rdna4` (every RDNA3/RDNA4 id libdrm 2.4.134 lists), whatever
    files exist. An RDNA3/RDNA4 card's only write path is PMFW `fan_curve`; an id
    missing from that list would be judged by file presence again, so keep the list
    current with libdrm.
- GPU fan writes use an imperative model (`set_static_speed` via a flat PMFW curve);
  no lease is required. The curve's lowest allowed duty is the card's own `OD_RANGE`
  minimum, read from `fan_curve`. It is board-specific (often around 15%; one R9700 reports
  about 30%). The **kernel rejects** a point outside the range with `-EINVAL`
  (`"Fan curve pwm setting(%ld) must be within [%d, %d]!"`); it does not clamp. The
  clamp is the daemon's own, which reads the range before writing.
- **The SMU driver-interface version message is not a fault.** RDNA4 cards log a
  driver `0x2E` vs firmware `0x32`/`0x33` interface mismatch on every Navi 48 part,
  the RX 9070 XT included; the firmware is designed to be backward compatible, and
  kernel 7.0 dropped the message ("It just leads to user confusion", `e471627d5627`).
  Do not key a fault diagnosis on it. The daemon's `smu_mismatch_navi48_r9700`
  advisory did, and DEC-422 retired it.
- The `amdgpu.ppfeaturemask` kernel parameter is required for PMFW `fan_curve` access.
- ppfeaturemask bit 14 (`0x4000`) is required for PMFW. Diagnostics must explain this
  when it is missing.
- **The recommended value is `amdgpu.ppfeaturemask=0xfff7ffff`** (DEC-497): the kernel's
  default `0xfff7bfff` with bit 14 added, the value AMD's engineers give. Any mask with
  bit 14 set is accepted; never tell a user whose mask already has bit 14 to change it.
  `0xffffffff` also sets bit 19 (GFX DCS), which the kernel leaves off by default; the
  SMU 13.0.0/13.0.7/14.0.2 code never reads it.
- **Enabling OverDrive taints the kernel from 6.13** (`b472b8d829c1`,
  `TAINT_CPU_OUT_OF_SPEC`, logged at critical level as "Overdrive is enabled, please
  disable it before reporting any bugs unrelated to overdrive."). Wherever the parameter
  is taught, say that the message is expected.
- **A missing `fan_curve` is no longer proof that `ppfeaturemask` is wrong.** Since
  kernel 7.0 (`470891606` for smu v13, `ab4905d46` for smu v14) the driver
  **disables the `OD_FAN_CURVE` entries entirely** when the firmware reports an
  invalid temperature or PWM range. So a correctly-configured system can legitimately
  have no `fan_curve` file, and diagnostics must not tell that user to fix a kernel
  parameter that is already right.
- Since kernel 7.1 (`4f2c86c62a00`), smu v14.0.x parses OD-table upload failures into
  named dmesg messages (`OD_FAN_CURVE_PWM_ERROR`, `OD_FAN_CURVE_TEMP_ERROR`, `OD_FAN_MIN_PWM_ERROR`,
  `OD_FAN_ZERO_RPM_STOP_TEMP_ERROR`, …): cheap, high-value diagnostic output to
  surface when a curve write is rejected.
- Kernel docs warn: **do not** drive `pwm1` and `fan[1-*]_target` at the same time.
- GPU PMFW fan writes use a **5% threshold** (not 1%) to avoid SMU firmware churn
  during gaming (DEC-070).
- The daemon disables `fan_zero_rpm_enable` before writing a PMFW curve, so the fan
  spins at the commanded speed, and re-enables it on reset (DEC-053), **except** for a
  profile member marked `fan_zero_rpm: true` (the **Allow zero-RPM idle** checkbox,
  and what **Dedicate GPU Fan** sets), where the card's own zero-RPM setting is left as
  it is and the firmware stops the fan at idle. A manual write (a hardware verify or
  test) always disables it.
- **On RDNA4 the firmware can stop the fan under a curve anyway.** On at least one
  RX 9070 XT (PMFW 104.80.0) the fan stops below about 50 °C hotspot with a curve
  active and `fan_zero_rpm_enable=0`, even on a flat 100 % curve, and follows the curve
  above it ([drm/amd #5905](https://gitlab.freedesktop.org/drm/amd/-/issues/5905)). The
  threshold appears to be the OD table's zero-RPM stop temperature (setting it with
  AMD's test patch moved the stop point), which SMU 14.0.2 does not expose before
  AMD's `fan_zero_rpm_stop_temperature` patch (`9e3854634bfa`, expected in 7.4). So
  never read 0 RPM on an idle RDNA4 card under a curve as a failed write or a dead fan;
  RDNA4 `fan1_input` can also read 0 while the fan spins
  ([drm/amd #5514](https://gitlab.freedesktop.org/drm/amd/-/issues/5514)).
- **RDNA4 fan curves want kernel 6.18.32, 7.0.9, 7.1 or later.** `504f0098ebd0`
  ("fix incorrect FeatureCtrlMask setting on smu v14.0.x", Cc stable) fixes the
  fan-curve edit, fan-curve restore and `fan_minimum_pwm` paths; its message says the
  bug "leads to disabled thermal monitoring and temperature boundary validation".
  Whether it bit the daemon's write sequence is unproven.
- **RDNA2 and older: resume from suspend leaves a manual fan manual.**
  `smu_restore_dpm_user_profile` (resume only) re-applies a saved manual mode and then,
  through an inverted check (`ret != -EOPNOTSUPP`), logs "Failed to set manual fan
  control mode", marks the saved mode automatic and skips restoring the duty. On an SMU11
  card (RX 5000 / RX 6000) the hardware stays in manual mode without its duty (kernel
  source reading; powerplay generations not checked). A GPU reset does not run this
  path.
- `fan_zero_rpm_enable` sysfs returns multi-line formatted output: parse header+value,
  do not just `trim()`.
- **The daemon must reset the GPU fan curves it drove to automatic on shutdown, and only
  those (DEC-435).** A card whose PMFW curve the daemon wrote (a profile's curve or a hardware
  verify) is named in a write-ahead record before the first write and reset on every stop path,
  including SIGKILL via `ExecStopPost`; a card it never wrote, or handed back itself with
  `POST /gpu/{id}/fan/reset`, is not touched, so LACT or CoreCtrl can own it.
  *(Safety-critical.)*
- **A GPU the active profile stops naming is handed back at once, not at the next stop
  (DEC-448).** On the tick after a deactivate, or a switch to a profile
  that drops the card, the engine resets it to firmware auto (the same reset
  `POST /gpu/{id}/fan/reset` makes, under the same GPU write lock) and takes it off the
  hand-back list. A card a skipped or overridden control still names is kept; a verify
  holding the write pause defers it; a reset that fails leaves the card listed (so the
  stop still resets it) and is retried after a minute. The member set it judges by is its
  own type, never the thermal force's reach: the GPU stays outside the force (DEC-130).

## Truthfulness

- **Do not claim GPU fan write support unless PMFW `fan_curve` or hwmon `pwm1` is
  actually available.** The control method must be truthful: `"read_only"` when no
  write path exists, meaning no PMFW and either no `pwm1_enable` or an RDNA3/RDNA4 device
  id (DEC-430). *(Safety-critical.)*
- The read-only hint says why: while overdrive is off it names
  `amdgpu.ppfeaturemask`; with it on, it says the kernel did not expose the curve
  (the kernel 7.0+ case above) instead of repeating advice the user already took.
- In fan-role member selection a GPU fan no profile can drive is listed but disabled,
  with a `(read-only)` or, for a pre-RDNA3 card, `(verify only)` suffix and a tooltip
  saying why (DEC-445).

## Display and UX

- GPU model name: libdrm's `amdgpu.ids`, matched on PCI device id **and
  revision** (one id is often several cards: 0x744C is the RX 7900 XTX, XT, GRE
  and 7900M) for every RDNA2/3/4 card it lists (DEC-430). An unlisted
  (device, revision) has no model name rather than a guessed one.
- GPU display label: the model name with an `"RX "` name compacted
  (e.g. "9070XT") and any other kept as written ("Pro W7900"), otherwise
  "AMD D-GPU".
- GPU fan display name: `"{model} Fan"` from capabilities, falling back to
  `"D-GPU Fan"` (DEC-050).
- GPU fans are **always** displayable on the dashboard: zero-RPM idle is normal, not
  a disconnected header (DEC-047).
- GPU fans participate in fan roles, curves, profiles, the dashboard fan table, and
  diagnostics.
- The GUI shows a one-time zero-RPM info popup when a GPU fan is added to a role
  (setting: `show_gpu_zero_rpm_warning`).
- The fan wizard's stop/restore must handle all source types: `openfan`, `amd_gpu`,
  `hwmon`.

## Dependencies and platform

- Do **not** adopt the `amdgpu-sysfs` crate. Its LGPL-3.0 licence causes friction, and our
  focused code suffices (DEC-043).
- The daemon socket must be `chmod 0666` after bind to allow non-root GUI connections
  (DEC-049).

## Related

- GPU-only controls and the 0-RPM idle feature: DEC-221 (`fan_zero_rpm` is the lever;
  a 0% floor is not the same thing as 0 RPM).
- GPU floor behaviour: DEC-119.
- Role-aware floors and `member_label` (the CPU/pump 30% rule): DEC-095, DEC-162. A pump
  on a motherboard header in DC mode gets 70% instead (DEC-443); neither floor applies to a
  GPU fan.
