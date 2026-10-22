# Sensor Interpretation Guide

This guide defines how the GUI describes a temperature reading: what it *actually
represents* at the hardware level, and how confident that description is. The GUI
never claims more certainty about a sensor's identity than the kernel driver and
board documentation support. The model is implemented in
`src/ventulus/knowledge/sensor_knowledge.py` and drives tooltips, the Dashboard's
series panel and the diagnostic displays.

For what the AMD CPU sensors (Tctl, Tdie, Tccd, SB-TSI) mean in practice, see the
[AMD Sensor Interpretation Deep Dive](22_AMD_Sensor_Interpretation_Deep_Dive.md).

## Classification model

Each sensor reading from the daemon includes three metadata fields used for
classification:

| Field | Source | Example |
|---|---|---|
| `chip_name` | hwmon driver name from sysfs (`name` file) | `k10temp`, `nct6798`, `it8689` |
| `label` | Driver-provided label (`tempN_label` sysfs) | `Tctl`, `SYSTIN`, `temp1` |
| `temp_type` | Thermistor type code (`tempN_type` sysfs), nullable | `3` (diode), `4` (thermistor), `5` (AMD TSI), `6` (PECI) |

The classification function signature:

```python
classify_sensor(chip_name, label, temp_type=None, board_vendor="")
    -> SensorClassification(source_class, display_description, confidence, notes)
```

The `source_class` field is a machine-readable category (e.g. `cpu_die`,
`board_thermistor`, `vendor_labeled`). The `display_description` is the
human-readable string shown in tooltips. The `confidence` field indicates how
certain the classification is.

**Every surface that shows a sensor's class or confidence goes through one
accessor, `AppState.classify_sensor(sensor)`**. It supplies
`board_vendor` from `AppState.board_info` (which a blank rescan never
downgrades) and the user's "Treat as coolant" overrides, so the Overview table,
its summary line, the Sensor Detail dialog and the Dashboard series-panel
tooltip classify a sensor identically.

## Driver-specific rules

### k10temp (AMD CPU internal sensors)

Kernel docs: https://docs.kernel.org/hwmon/k10temp.html

| Label | source_class | Confidence | Notes |
|---|---|---|---|
| `Tdie` | `cpu_die` | high | Measured CPU die temperature. Its tooltip notes that Tctl may sit a fixed offset above it on some CPUs. |
| `Tctl` | `cpu_control` | high | Platform cooling reference. Not a direct physical reading. May differ from Tdie by a designed offset on some SKUs. |
| `Tccd1`, `Tccd2`, ... | `cpu_ccd` | high | Per-CCD (core complex die) temperature. Available on Zen 2+ with multiple CCDs. |
| Other | `cpu_internal` | high | Generic fallback for any other k10temp label. |

**Key quirk:** Tctl is not a physical temperature. It is a control value used by
the platform to drive cooling decisions. The kernel
[`k10temp.html`](https://docs.kernel.org/hwmon/k10temp.html) describes Tctl as
*"a non-physical temperature on an arbitrary scale measured in degrees"* used
to control cooling systems, distinct from Tdie which is *"the real measured
temperature."* The driver's offset table (`tctl_offset_table` in `k10temp.c`,
checked at 7.3-rc4) covers only Family 17h parts: Ryzen 5 1600X and Ryzen 7
1700X / 1800X (20 °C), Ryzen 7 2700X (10 °C), and Threadripper 19xx / 29xx
(27 °C; Zen and Zen+). The driver
publishes Tdie (`temp2`) only for those; Zen 2 and later publish Tctl plus the
per-CCD `Tccd` readings (up to 16 labels from 7.3). The kernel doc gives no
general `Tctl = Tdie + offset` formula. The GUI never presents Tctl as the
"actual" CPU temperature (its tooltip calls it a control value), but **nothing
in the GUI prefers Tdie when it picks a sensor**. The preferred-CPU
recommendation (the ★ in Settings → preferred CPU sensor) is the daemon's
`default_cpu`, which ranks Tctl first, then a package reading, then Tdie
(`hwmon/classify.rs::cpu_class_rank`). On the five offset parts above, the daemon
therefore recommends the offset Tctl. The AIO setup's CPU fallback takes the first CPU
sensor, in the daemon's list order, whose label names a package, Tctl or Tdie
(`profile_service._pick_cpu_sensor_id`).

### sbtsi_temp (AMD SB-TSI board-side interface)

Kernel docs: https://docs.kernel.org/hwmon/sbtsi_temp.html

The hwmon device is named **`sbtsi`**; only the module is `sbtsi_temp`. From
kernel 7.3 the driver depends on ARM / ARM64: it is meant to run on a BMC, not on
the managed host, so x86 desktops stop seeing it at all.

All readings classify as `amd_tsi` at `medium_high` confidence.

SB-TSI (SideBand Temperature Sensor Interface) provides a board/firmware-
accessible CPU temperature feed over SMBus. It is a separate data path from
k10temp and may report different values. The GUI notes that this is "not the
same source as k10temp Tdie."

The SB-TSI address is normally `98h` for socket 0 and `90h` for socket 1
(8-bit I2C addresses; 7-bit equivalents are 0x4C and 0x48), but may vary
with hardware address select pins. On desktop Ryzen boards (single-socket),
98h is standard. SB-TSI readings often surface through Super I/O chip
drivers (nct6683, nct6775) as labels like `AMD TSI Addr 98h` rather than
through a standalone `sbtsi` device.

### nct6775 family (Nuvoton Super I/O)

Kernel docs: https://docs.kernel.org/hwmon/nct6775.html

Covers: nct6775, nct6776, nct6779, nct6791, nct6792, nct6793, nct6795, nct6796,
nct6797, nct6798, nct6799.

| Label pattern | source_class | Confidence | Notes |
|---|---|---|---|
| `PCH_DIM0_TEMP`…`PCH_DIM3_TEMP` (nct6776–6792), `Agent0 Dimm0`… (nct6793+) | `memory_dimm` | medium | Memory channels, checked first; see [Memory temperatures](#memory-temperatures-spd5118-jc42-and-board-dimm-channels) |
| Contains `AMD TSI` or `TSI` | `amd_tsi` | medium_high | Board-side CPU temp via AMD TSI |
| Contains `PECI` | `cpu_peci` | medium_high | CPU temp via Intel PECI |
| `SYSTIN` | `board_system` | medium | System temperature input, exact placement is vendor-specific |
| `AUXTIN` / `AUXTINn` | `board_auxiliary` | medium | Auxiliary input, exact placement is vendor-specific |
| `CPUTIN` | `cpu_board_side` | medium | Board-side CPU temperature (see ASUS quirk below) |
| Named labels (mixed case or `_`) | `super_io_channel` | medium | Source configured by board firmware |
| Generic `tempN` | `super_io_channel` | low | No semantic information available |

These chips have configurable temperature source multiplexers. The actual physical
sensor connected to each channel is determined by the board firmware, not the
chip. The kernel driver exposes whatever label the firmware provides, which may
or may not be accurate.

### nct6683 / nct6686 / nct6687 (Nuvoton newer family)

Kernel docs: https://docs.kernel.org/hwmon/nct6683.html

AMD boards confirmed working in kernel documentation: ASRock X570, ASRock X670E,
ASRock B650 Steel Legend WiFi, MSI B550, MSI X670-P, MSI X870E.

These chips support `temp_type` codes that provide additional classification
signal beyond the label alone.

| temp_type | source_class | Confidence |
|---|---|---|
| 5 | `amd_tsi` | medium_high |
| 4 | `board_thermistor` | medium |
| 3 | `thermal_diode` | medium |
| 6 | `cpu_peci` | medium_high |

**A `DIMM` label is checked before any type code**. The kernel reads
memory temperatures over PECI too: `PECI DIMM 0`–`3` carry `temp_type` 6, the
same code as the CPU's own `PECI 0.0`–`3.1`, so the type-code rule alone would
call a DIMM the CPU. Both the GUI (`memory_dimm`) and the daemon (`kind: mb_temp`)
exclude them; the daemon's exclusion is what keeps a memory reading out of the
thermal ladder's CPU input.

Label-based rules (a `DIMM` label first; the rest apply when temp_type is absent
or unknown):

| Label pattern | source_class | Confidence |
|---|---|---|
| Contains `DIMM` (any type code) | `memory_dimm` | medium |
| Contains `SMBus` | `smbus_device` | medium |
| Contains `Virtual` | `virtual` | low |
| `Local` | `chip_local` | medium |

Full temperature source label enumeration from the kernel source
(`nct6683_mon_label[]` in `nct6683.c`): `Local`, `Diode 0-2 (curr)`,
`Diode 0-2 (volt)`, `Thermistor 0-16`, `PECI 0.0-3.1`, `PECI DIMM 0-3`,
`PCH CPU`, `PCH CHIP`, `PCH CHIP CPU MAX`, `PCH MCH`, `PCH DIMM 0-3`,
`SMBus 0-5`, `DIMM 0-3`, `AMD TSI Addr 90h`-`9dh`, `Virtual 0-7`.
The GUI's `DIMM` rule catches `PCH DIMM 0-3` (`memory_dimm`); it has no rule for the
other `PCH` labels, so they fall to `super_io_channel`.
The daemon promotes `PCH CPU` and `PCH CHIP CPU MAX` to `cpu` because the label
names the CPU. That is deliberate: each reads at least the CPU's own
temperature, so neither can hide a hot CPU from the ladder.

The temp_type codes are mapped from source ranges in the kernel:
0x02-0x07 -> type 3 (diode), 0x08-0x18 -> type 4 (thermistor),
0x42-0x49 -> type 5 (AMD TSI), 0x20-0x2b -> type 6 (Intel PECI; this range
includes `PECI DIMM 0-3` at 0x28-0x2b). Every other source (`Local`, `PCH *`,
`SMBus`, `DIMM`, `Virtual`) returns 0, so no `tempN_type` is published.
Reference: `drivers/hwmon/nct6683.c`, `get_temp_type()` function.

The labels give the **source class** but usually **not** the physical location on the
board:

| Label | What you know | What you do not know |
|---|---|---|
| `AMD TSI Addr 98h` | Board-side CPU temperature via SB-TSI | Nothing: the identity is clear |
| `Thermistor 7` | A thermistor is connected to channel 7 | Which board component it monitors |
| `Diode 1` | A thermal diode on channel 1 | Its placement on the PCB |
| `Virtual 3` | A derived or computed value | What it is derived from |
| `SMBus 2` | A device on SMBus channel 2 | What device or component |

**`force=1` and customer IDs.** The in-kernel `nct6683` instantiates only for EC
customer IDs it knows (Intel, Mitac, several MSI IDs from 5.11 on, AMD for the BC-250
from 6.15, and a growing set of ASRock IDs in 6.7, 6.14, 7.0, 7.1 and 7.2) unless
`force=1` is given. With `force=1` it reads an unknown board too, but **the PWM files
stay read-only**: the driver makes them writable only on Mitac OEM systems, and has no
`pwmN_enable`. So `force=1` buys monitoring, never control. Do not confuse it with the
out-of-tree `nct6687` driver's `force=1`, which attaches to any Nuvoton ID in
0xD000–0xDFFF and can mis-claim an NCT679x chip (see the
[chip-ID collision](19_Hardware_Compatibility.md#the-nct679x-chip-id-collision)).

### it87 family (ITE Super I/O)

Kernel docs: https://docs.kernel.org/hwmon/it87.html
Out-of-tree fork: https://github.com/frankcrawford/it87 (newer chip support)

Covers `it8xxx` variants. The mainline kernel `it87` driver supports a fixed
list of chips. The kernel's `enum chips` has 22 types at 7.2 and 7.3-rc4: IT8603E,
IT8620E, IT8622E, IT8628E, IT8689E (fan control from 7.1), IT8705F, IT8712F,
IT8716F, IT8718F, IT8720F, IT8721F, IT8728F, IT8732F, IT8771E, IT8772E, IT8781F,
IT8782F, IT8783E/F, IT8786E, IT8790E, IT8792E/IT8795E and IT87952E (6.3+). IT8613E
is queued for 7.4. **Newer Gigabyte-era chips
(IT8625E, IT8686E, IT8688E, IT8696E, IT8698E) and the IT8665E on ASUS AM4
300/400-series boards are NOT in mainline** and require the out-of-tree
[frankcrawford/it87](https://github.com/frankcrawford/it87) driver. The
kernel.org doc URL above covers behaviour for the in-tree chips; the
out-of-tree driver inherits the same sysfs schema but with an expanded chip
ID table (see its `README` for the full supported list).

The it87 driver provides minimal labeling. Most sensors appear as generic
`tempN` channels with no semantic information. Classification is conservative:

| Label pattern | source_class | Confidence |
|---|---|---|
| `tempN` (numeric) | `super_io_channel` | low |
| Named label with a capital letter (as the out-of-tree driver or a `sensors.d` file names it) | `super_io_channel` | medium |
| Named label, all lower case | `super_io_channel` | low |

The driver does not expose which physical sensor type is connected to each
channel. A board-specific override can name such a channel in the Sensor Detail
dialog, but it does not change the classification or its confidence (see
[Board-specific override database](#board-specific-override-database)).

**Board-catalogue names (DEC-500).** On a Gigabyte board whose out-of-tree driver
publishes the SIV, the daemon names an unlabelled `tempN` from its board catalogue
(`/diagnostics/hardware .board_layout`): `System 1`, `PCH`, `VRM MOS`, `PCIEX16`,
`EC_TEMP1`. The GUI shows that name wherever the sensor appears, while the
driver's own label is still the synthesised `tempN`. It is a **display name
only**: classification reads the driver's label, so the table above applies
unchanged and the channel stays a low-confidence `super_io_channel`. A channel
the catalogue calls `CPU` is the board's socket thermistor as the config names it,
not the CPU's own sensor; it never becomes a CPU sensor and never feeds the CPU
thermal emergency, which reads `k10temp`/`coretemp`. An `EC_TEMP` channel is a
header for an optional thermistor probe: with no probe fitted its reading means
nothing, and the GUI says so in the row's tooltip.

### asus_ec_sensors (ASUS embedded controller)

Kernel docs: https://docs.kernel.org/hwmon/asus_ec_sensors.html

The hwmon device is named **`asusec`**; `asus_ec_sensors` is the module.

High-confidence vendor-labeled sensors read directly from the ASUS embedded
controller. The kernel driver exposes semantic labels that map to specific
board features.

| Label pattern | source_class | Confidence |
|---|---|---|
| Contains `T_Sensor` | `external_probe` | high |
| Contains `VRM` | `vrm` | high |
| `Water_In` | `coolant_in` | high |
| `Water_Out` | `coolant_out` | high |
| `Water_Block_In` | `coolant_in` (described as the water block inlet) | high |
| `Water_Block_Out` | `coolant_out` (described as the water block outlet) | high |
| Contains `Chipset` | `chipset` | high |
| Contains `CPU` + `Package` | `cpu_package` | high |
| Contains `Motherboard` | `board_ambient` | high |
| Other | `vendor_labeled` | high |

The water rows are the labels `asus-ec-sensors.c` publishes, with underscores.
The classifier folds underscores to spaces, so the spaced `Water In` / `Water Out`
that `asus_wmi_sensors` passes through from the BIOS match the same rows. Water
labels are matched on any chip, ahead of the driver branches. The driver also
publishes fan, current and voltage channels (for example the CPU_Opt fan header and a
water-flow meter); this guide covers temperatures. It coordinates with the firmware
through an ACPI mutex, and its `mutex_path` parameter (with a `:GLOBAL_LOCK` mode)
exists because ASUS may move that mutex in a BIOS update.

Beyond the ASUS EC, dedicated **hwmon liquid coolers** are classified by chip name + label:
NZXT Kraken (`x53`/`z53`/`kraken2023`/`kraken2023elite`/`kraken2024elite`/`kraken2`) and Aquacomputer
(`d5next`/`highflownext`/`leakshield`) coolant channels map to `coolant` (high confidence), and any
`coolant`/`water`/`liquid` label maps to `coolant` on any chip (medium). The Kraken 2024 Elite
(`kraken2024elite`) needs kernel 7.3 or later. The daemon reports these as the
`coolant_temp` sensor kind.

**Coolant is a safety input.** The hottest fresh coolant reading at or above the
coolant limit (Settings ▸ Daemon Configuration, 40–70 °C, default 60) forces every fan
and pump to 100 % until the coolant is 5 °C cooler. Only a sensor **the daemon**
classifies as `coolant_temp` triggers it, by the rules above, so the GUI's "Treat as
coolant" override below does **not** make a sensor a safety input. A coolant sensor
never drives the CPU's no-sensor floor. Cool the loop in normal running with a curve
bound to the coolant sensor; the emergency is the backstop.

**"Treat as coolant" (user override).** Right-click a sensor on the Overview page's
sensor table and choose **Treat as coolant** to classify it as coolant when the rules
above miss it; on a sensor already overridden the same menu offers **Reset
classification to auto**, and Settings → Sensors & Chart Series → **Clear overrides**
removes them all. The override is the GUI's alone: the daemon's `kind` for the sensor
does not change, and it has no effect on thermal safety. That includes the coolant
emergency, which keys on the daemon's `kind`. What it drives is the GUI's
own coolant view: the sensor's class everywhere it is shown, the coolant marking in
the curve sensor picker, which sensor the AIO setup takes as the coolant sensor, and so
which calibration (coolant or CPU) **Configure AIO** seeds the radiator-fan curve with.

This driver only loads on explicitly supported ASUS boards (the kernel driver
has a board allowlist). All readings are high confidence because the EC provides
the identity mapping.

### asus_wmi_sensors (ASUS WMI interface)

Kernel docs: https://docs.kernel.org/hwmon/asus_wmi_sensors.html

Accessed via WMI (Windows Management Instrumentation) ACPI methods, with labels
the BIOS supplies. Classification is close to `asus_ec_sensors`' but not the same,
and one step lower, because the WMI interface has known polling reliability issues on
some boards:

| Label pattern | source_class | Confidence |
|---|---|---|
| `Water In` / `Water Out` and any other coolant/water/liquid label | `coolant_in` / `coolant_out` / `coolant` (the cross-driver rule, ahead of this table) | high for in/out, medium otherwise |
| Contains `CPU` | `cpu_board_side` (the board's reading of the CPU, not a die sensor) | medium_high |
| Contains `VRM` | `vrm` | medium_high |
| Contains `Chipset` | `chipset` | medium_high |
| Contains `T_Sensor` | `external_probe` | medium_high |
| Contains `Motherboard` | `board_ambient` | medium_high |
| Other | `vendor_labeled` | medium |

The kernel doc explicitly calls out the firmware bug: *"The WMI implementation
in some of Asus' BIOSes is buggy. This can result in fans stopping, fans getting
stuck at max speed, or temperature readouts getting stuck. This is not an issue
with the driver, but the BIOS. The Prime X470 Pro seems particularly bad for
this. The more frequently the WMI interface is polled the greater the potential
for this to happen. Until you have subjected your computer to an extended soak
test while polling the sensors frequently, don't leave you computer unattended.
Upgrading to new BIOS version with method version greater than or equal to two
should rectify the issue."* That last sentence cannot help anyone running the
driver: it refuses to bind when the BIOS reports a method version below two, so
every system it loads on already meets it. The kernel doc queued for 7.4 replaces
it with *"Upgrading to a more recent BIOS version might help"*
([hwmon patch, 2026-10-16](https://patch.msgid.link/20261016163509.249020-1-heyheyco@gmail.com)).
When users report stuck-fan or artificially-low fan behaviour on a supported ASUS
WMI board, no fix is known: a newer BIOS may help, and the soak test is the
kernel's advice.

All classifications carry a standing note about potential WMI polling issues
and the soak test.

### gigabyte_wmi (Gigabyte WMI interface)

The `gigabyte-wmi` driver (mainline since Linux 5.13) reports temperatures from
Gigabyte boards over WMI. It provides no fan control, no voltages and no labels: it
defines only `HWMON_T_INPUT` for up to six channels, with no `HWMON_T_LABEL` and no
`read_string`, so you see `temp1_input` to `temp6_input` and nothing else. A B550M
DS3H AC owner reported exactly that
([gigabyte-wmi-driver #19](https://github.com/t-8ch/linux-gigabyte-wmi-driver/issues/19)).

All readings classify as `vendor_wmi_unlabeled` at `low` confidence. The physical
mapping may differ by board model and BIOS version. Gigabyte's Windows software
(System Information Viewer) shows names such as "VRM MOS", but those cannot be
reliably mapped to the Linux sysfs channels.

### amdgpu (AMD GPU driver)

| Label | source_class | Confidence |
|---|---|---|
| `edge` | `gpu_edge` | high |
| `junction` | `gpu_junction` | high |
| `mem` | `gpu_memory` | high |
| Other | `gpu_other` | high |

GPU sensors are high confidence because the amdgpu kernel driver defines
exact label semantics. Junction is the hottest point on the die.

### xe / i915 (Intel discrete GPU driver)

Read-only temperatures from Intel **discrete** GPUs (Arc). Surfaced as
sensor source `intel_gpu`, kind `gpu_temp`.

`xe` (Arc B-series "Battlemage" and later Xe2) **labels** its temperatures through
`tempN_label`, so the label is what arrives (since Linux 6.15, when `xe` gained
temperatures; the labels are set in
[`xe_hwmon.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/xe/xe_hwmon.c)).
Its channels start at `temp2` (there is no `temp1`):

| Index | Label | Meaning | Since |
|---|---|---|---|
| `temp2` | `pkg` | GPU package | 6.15 |
| `temp3` | `vram` | VRAM | 6.15 |
| `temp4` | `mctrl` | Memory controller (average) | 7.0 |
| `temp5` | `pcie` | GPU PCIe | 7.0 |
| `temp6`–`temp21` | `vram_ch_0`… | Per-VRAM-channel | 7.0 |

`i915` (Arc A-series "Alchemist") has no `tempN_label`, so its one channel arrives as
`temp1` (from Linux 6.13):

| Index | Meaning |
|---|---|
| `temp1` | Package temperature |

All Intel GPU temperatures are read-only. Fan control is firmware-managed
and has no kernel write path; see
[Intel discrete GPU monitoring](19_Hardware_Compatibility.md#intel-discrete-gpu-arc-monitoring).

References:
- https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-xe-hwmon
- https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-i915-hwmon

### nouveau / nvml (NVIDIA discrete GPU driver)

Read-only temperatures from NVIDIA **discrete** GPUs. Surfaced as
sensor source `nvidia_gpu`, kind `gpu_temp`, and classified `gpu_package` at
`high` confidence. Two `chip_name`s appear, one per driver world:

| `chip_name` | Origin | Channels |
|---|---|---|
| `nouveau` | sysfs hwmon `name` file (open `nouveau` DRM driver) | `temp1` (GPU package); some cards also expose fan RPM. Cards older than Turing only: on Turing and newer `nouveau` registers no hwmon device |
| `nvml` | a **daemon-synthetic** identifier for the proprietary NVML polling path (no sysfs hwmon node) | one temperature, plus the driver's fan **duty %** (`duty_pct`; NVIDIA's *intended* speed, not a measurement) |

All NVIDIA GPU temperatures are read-only. Fan control is unavailable through
the daemon: `nouveau`'s writable `pwm1` is deliberately excluded and the NVML
backend is telemetry-only. See
[NVIDIA discrete GPU monitoring](19_Hardware_Compatibility.md#nvidia-discrete-gpu-monitoring).

### nvme (NVMe drive controller)

All readings classify as `disk_composite` at `high` confidence. NVMe drives
report a composite temperature per the NVMe specification. The label from the
kernel is included in the description.

### coretemp (Intel CPU internal sensors)

All readings classify as `cpu_die` at `high` confidence. The coretemp driver
reads per-core DTS (Digital Thermal Sensor) values from Intel CPUs.

### Memory temperatures (spd5118, jc42 and board DIMM channels)

Kernel docs: https://docs.kernel.org/hwmon/spd5118.html ·
https://docs.kernel.org/hwmon/jc42.html ·
https://docs.kernel.org/hwmon/dell-smm-hwmon.html

Two kinds of source report a memory temperature:

| Source | Chip / label | source_class | Confidence |
|---|---|---|---|
| DDR5 module, its SPD hub on the board's SMBus | chip `spd5118` | `memory_dimm` | high |
| DDR4/DDR3 module with a JEDEC JC-42.4 sensor | chip `jc42` | `memory_dimm` | medium (the driver also binds standalone thermometers) |
| Board chip, memory channel | nct6683 `DIMM n` / `PECI DIMM n` / `PCH DIMM n`, nct6775-family `PCH_DIMn_TEMP` / `AgentN DimmN`, Dell `dell_smm` `SODIMM` | `memory_dimm` | medium |

The daemon reports the same split as `classification: memory_temp`. Every one of
these stays `kind: mb_temp` on the wire, so it still counts as board evidence in the
daemon's CPU plausibility check and never reaches the thermal ladder.

**Ids.** A module is an i2c client, and the kernel numbers i2c buses in
registration order, so a GPU swap or a driver-load reorder renumbers them. The
daemon therefore names a module by what does not move: its SMBus controller (normally
a PCI address), the adapter's port (`p<N>`, piix4) or mux channel (`ch<K>`), and the
SPD address, for example `hwmon:spd5118:0000:00:14.0-p0-0051:temp1`. Where it cannot name the
topology unambiguously (two adapters that look alike, an ACPI-named client) it keeps the
older bus-numbered form, `hwmon:spd5118:21-0051:temp1`. Saved ids cross between the
two forms by one rule, applied by the daemon's engine and by the GUI on the first
sensor poll. Every other sensor with the same chip, address and label counts as a
candidate, whether live or quarantined (listed under unavailable sensors), and in either
form. The saved id moves only when there is exactly one candidate, it is live, and it is
of the other form. So a second module at that address, even one that is unreadable right
now or still bus-numbered, blocks the move; and a stable id never moves to another stable
id. The GUI re-keys chart colours, hidden chart series, the coolant override,
Overview-hidden sensors and profile curves. A profile with unsaved edits open in Controls,
or an unpublished draft, is re-keyed in memory only, never saved behind your back. The
preferred CPU/motherboard sensor and cooling-device sensors are daemon-side advisory
settings and are re-picked by hand. **If you downgrade the daemon** to a release from
before these stable ids (one that matches ids exactly), re-activate the active profile
once: the GUI re-keys it back to the old form and saves it, but the daemon does not
reload an active profile on save.

**Naming.** Module sensors have no label: each publishes `temp1`, so two modules would
look identical. The GUI names them from the SPD address in their id (**DIMM 0x51**),
on every surface that names a sensor (`sensor_display_name`), in both id forms. No slot
is claimed: the kernel registers modules without knowing which slot an address belongs
to. Where two modules share an address on different SMBus segments, the segment is
added: **DIMM 0x51 (p2)**, **(ch1)**, or **(bus 21)** in the older form. Board
channels keep their own label.

**Grouping.** The Dashboard's sensor list files memory under its own **Memory** group,
after Motherboard. The default chart never uses a memory module as its motherboard
line. The Overview summary counts memory separately (`2 memory`), and the curve
sensor picker labels it `(memory)`.

**Quirks and how they are handled.**

| Quirk | Handling |
|---|---|
| DDR5 needs kernel 6.11 or later (the `spd5118` driver and automatic registration). The kernel registers modules from the firmware's memory table: it gives up on mixed memory types, tries at most 8 addresses per bus, and current kernels skip DDR5 under Intel "SPD Write Disable". | Troubleshooting guide |
| DDR4 needs `ee1004` + `jc42`, and only modules that carry a sensor have one; most consumer DDR4 does not. Some DDR5 hubs have no working sensor either. | Troubleshooting guide: no reading is normal there |
| `spd5118` with `temp1_enable = 0` keeps returning its last value with no error. | The daemon treats the sensor as unreadable: listed under unavailable sensors, a curve on it is not controlled. It reads the driver's enable state (its cached copy), so a change made over raw SMBus, bypassing the driver, is not seen |
| Suspend/resume: the driver switches the sensor off on suspend, and the SMBus controller can fail on resume. | Read failures quarantine the sensor and it recovers by itself |
| A limit read over SMBus can be garbage without an error, and the daemon reads limits once. | A module `crit` at or below 0 °C, or below its own `max`, is ignored for the alarm, and the detail dialog says so |
| The hub sits on the module's circuit board; the memory chips run a few °C hotter. Its default 55 °C `max` and 85 °C `crit` are module settings. | Tooltip notes; `max_alarm` is never shown as a warning |
| The daemon never writes these chips. A write can be refused (Intel "SPD Write Disable") and has been reported to corrupt hub state. | Nothing to do: monitoring is read-only |

## Where the rich classification surfaces

These surfaces consume this knowledge base:

1. **Cell tooltips** on every Overview-page sensor-table cell (`format_sensor_tooltip`).
   The note list is capped at 3 entries for readability.
2. **Sensor Detail dialog** (`Diagnostics_SensorDetail_Dialog`): opens by
   double-clicking a row, pressing Enter on it, or right-click → **Open detail…**.
   A live strip at the top follows the poll (value, age, freshness, trend, session
   range, headroom to crit). The report below it shows the full classification
   description **and every classification note** (not truncated), the matching board
   override if one exists, board context, the Thresholds section, and a clickable
   kernel.org driver doc link. On a daemon that
   publishes its own classification it adds a **Daemon classification** section, whose
   confidence is the daemon's own scale and is not comparable one-for-one with the
   GUI's levels below. This is the canonical surface when a user wants the full story
   behind a sensor.
3. **The sensor table's summary line** (in its section header) and **inline `⚠`/`?`
   prefixes** on the Overview page's sensor table: the `bogus` and `low`-confidence
   rows have a visible prefix on the Label cell so they're discoverable without
   hovering.
4. The Dashboard's sensor list and chart, which use the same classification (and the
   same "Treat as coolant" overrides) for grouping.

## Confidence levels

| Level | Meaning | When to use |
|---|---|---|
| `high` | Identity is certain from kernel documentation or hardware specification | k10temp labels, amdgpu labels, asus_ec_sensors, nvme, coretemp |
| `medium_high` | Identity is very likely correct but depends on board firmware or an indirect interface | PECI/TSI-typed channels, sbtsi_temp, asus_wmi_sensors |
| `medium` | Identity is plausible based on label conventions but cannot be confirmed without board docs | Named nct6775 channels (SYSTIN, CPUTIN), nct6683 thermistor/diode type, named ITE labels |
| `low` | Identity is unknown or unreliable | Generic `tempN` labels, gigabyte_wmi channels, virtual sensors |

## Documented quirks

### Tctl is not a physical temperature

AMD's Tctl (Control Temperature) is a derived value used by the platform cooling
algorithm. On some SKUs it equals Tdie; on others it has a designed positive
offset. Displaying Tctl as the "CPU temperature" can mislead users into thinking
their CPU is hotter than it actually is. The GUI annotates Tctl with a note
explaining its nature. It does not choose Tdie over Tctl anywhere it picks a
sensor: the preferred-CPU recommendation is the daemon's Tctl-first
`default_cpu` (see the k10temp section above).

Reference: https://docs.kernel.org/hwmon/k10temp.html

### ASUS CPUTIN bogus on the nct6775 family

The kernel documentation states: "On various ASUS boards with NCT6776F, it appears
that CPUTIN is not really connected to anything and floats, or that it is connected to
some non-standard temperature measurement device. As a result, the temperature
reported on CPUTIN will not reflect a usable value. It often reports unreasonably high
temperatures…"

When `chip_name` is any of the nct6775 family (`nct6775`, `nct6776`, `nct6779`,
`nct6791`, `nct6792`, `nct6793`, `nct6795`, `nct6796`, `nct6797`, `nct6798`,
`nct6799`) and `board_vendor` contains "ASUS", the CPUTIN
channel is classified as `bogus` with `low` confidence and notes explaining the
issue. This is a well-documented kernel driver quirk, not a GUI assumption. The
vendor comes from the board's DMI data; where the daemon cannot read it, neither side
can tell an ASUS board from any other, and `CPUTIN` keeps its normal classification.
The rule fails open.

**The daemon acts on the same triple.** Its thermal ladder takes the **hottest** CPU
sensor, so a floating pin reporting a plausible-looking constant 115 °C would outrank
every healthy CPU sensor, latch the thermal emergency and never release it (release
needs ≤ 80 °C), holding every fan at 100 % on a cold machine. The daemon therefore
classifies the same chip+vendor+label as `mb`, and the channel never reaches the
ladder.

The daemon also promotes the sources the kernel docs tell you to prefer. On every chip
in `NUVOTON_PECI_TSI_CHIPS` (`hwmon/discovery.rs`), a label containing `AMD TSI`,
`TSI`, `PECI` or `CPU` classifies as `cpu` (`classify_chip`), **unless it also contains
`DIMM`**: nct6683's `PECI DIMM 0`–`3` are memory temperatures, and as `cpu` they would
enter the ladder's hottest-CPU reduce and, on a board with no k10temp/coretemp, stand
in for a missing CPU and keep the no-sensor floor off. That list is the eleven
nct6775-family chips plus `nct6683`, `nct6686` and `nct6687`, so an ASUS board whose
`CPUTIN` is demoted still gives the ladder a CPU input from `PECI`/`TSI`.

**Those are two different chip lists, and they are different on purpose. Do not
unify them.** The bogus-CPUTIN gate above requires all three: one of the eleven
chips, an ASUS board vendor, and an exact `cputin` label
(`is_known_bogus_cpu_sensor`). The `PECI`/`TSI` promotion
covers fourteen chips and is not vendor-gated at all. `PECI`/`TSI` is a CPU source
on any board that wires it; only the claim that `CPUTIN` is disconnected is
ASUS-specific. `classify_chip` runs the bogus gate before its chip dispatch, so on
an ASUS board `CPUTIN` is demoted before the promotion arm is reached. Widening the
vendor-gated rule to every board would demote a real CPU sensor on every non-ASUS
board carrying the same chip. That is the opposite fault, and the worse one. The
daemon pins one relationship between the lists: every chip that can have
`CPUTIN` demoted must be able to promote `PECI`/`TSI`
(`every_chip_that_can_demote_cputin_can_promote_peci_and_tsi`).

The daemon's wire `kind` and the GUI's own interpretation layer
(`knowledge/sensor_knowledge.py`) agree on these channels. The GUI routes the
eleven nct6775-family chips to `_classify_nct6775`, and `nct6683`/`nct6686`/`nct6687`
to `_classify_nct6683`, and both promote `TSI`/`PECI` to a CPU source (`amd_tsi` /
`cpu_peci`, `medium_high`). That covers the `PECI Agent N Calibration` channels on
`nct6792` and later, which the kernel accepts as a CPU temperature source. Like any
Super-I/O CPU proxy, they can read low. The daemon's plausibility filter rejects a
CPU reading that is **both** below 10 °C **and** more than 15 °C colder than the
hottest motherboard sensor. So a cold-room boot, where the board is cold too, never
trips it, and with no motherboard reading it rejects nothing. A rejected channel is
treated as unreadable: it is quarantined, logged once, listed among the Overview
page's unavailable sensors with the reason, left out of the thermal ladder, and
restored by itself when it reads sanely again. The daemon also logs once when a
proxy is the only CPU sensor.

Reference: https://docs.kernel.org/hwmon/nct6775.html

### ASUS WMI polling bugs

Some ASUS BIOS implementations respond badly to high-frequency WMI temperature
polling. Symptoms include fan stops, fan max, or stuck sensor readings. The GUI
carries a standing note on all `asus_wmi_sensors` classifications and the vendor
quirk system can raise a high-severity alert for affected boards.

Reference: https://docs.kernel.org/hwmon/asus_wmi_sensors.html

### Gigabyte WMI unlabeled channels

The `gigabyte_wmi` Linux driver does not provide semantic labels for temperature
channels. The Gigabyte System Information Viewer (Windows) may show names like
"CPU", "System", etc., but there is no reliable mapping between those Windows
labels and the Linux sysfs channel numbers. All channels are classified at `low`
confidence.

### sensors-detect lag

`sensors-detect` is **not** needed to load the Super I/O drivers: the daemon
package ships `/etc/modules-load.d/ventulus.conf` to load the common ones, and
the Hardware page's readiness checklist and Super-I/O section identify the chip
without probing hardware. Treat `sensors-detect` as a last resort, and never run it
after boot on a Gigabyte board, because it writes the Super-I/O unlock key and can latch the
bridge in front of a second chip.

`sensors-detect` maintains its own chip ID database, updated independently
of the kernel. New chips may be supported by the kernel driver before
`sensors-detect` recognises them. For example, lm-sensors issue #521 reports
`sensors-detect` showing "unknown chip with ID 0xd592" on an MSI PRO Z790-P
WIFI DDR4, while manually loading `nct6683` works correctly.

The daemon trusts the hwmon devices actually loaded, not `sensors-detect` output.

References:
- https://github.com/lm-sensors/lm-sensors/issues/521
- https://github.com/lm-sensors/lm-sensors/issues/499
- https://github.com/lm-sensors/lm-sensors/issues/454

### Thermistor channels are real but cannot be placed

On nct6683 (named `Thermistor N` channels) and on nct6775 and it87 (generic `tempN` or
board-named channels), the driver knows a sensor is connected but not where it sits on
the board. Only vendor documentation, BIOS labels or controlled load testing can map it
to a component such as the VRM heatsink or the chipset.

The GUI never invents a location. An nct6683 thermistor (type code 4, or a
`Thermistor N` label) is described as a "board thermistor channel" at `medium`. The
nct6775 and it87 families give no such hint: their unnamed `tempN` channels read as a
generic Super-I/O channel at `low`, as does an it87 label that is all lower case; a
capitalised it87 label is `medium`. A validated board-specific override is shown in its
own section of the Sensor Detail dialog; it is display-only and changes the channel's
classification and confidence nowhere else.

## Board-specific override database

### Structure

The override database is defined in `sensor_knowledge.py` as a list of
`BoardSensorOverride` entries:

```python
@dataclass(frozen=True)
class BoardSensorOverride:
    vendor_pattern: str     # Case-insensitive substring match on board vendor
    model_pattern: str      # Case-insensitive substring match on board model
    label_pattern: str      # Case-insensitive substring match on sensor label
    source_class: str       # Override classification
    display_description: str
    confidence: str = "high"
    notes: list[str] = field(default_factory=list)
```

**Board overrides are display-only**. `lookup_board_override(board_vendor,
board_model, label)` has one caller, the Sensor Detail dialog, which shows a
matching entry in its own "Board override" section. It does not replace the
driver-based classification: the Overview table, its summary, tooltips and the
dialog's own header line all show the driver classification and its confidence
(or the user's "Treat as coolant", which does apply everywhere). So on an ASRock X670E, `AMD TSI Addr 98h` is `medium_high` there while the
override beside it says `high`.

### Current entries

| Vendor | Model | Label | Classification | Confidence |
|---|---|---|---|---|
| ASUS | Crosshair VIII | T_Sensor | external_probe | high |
| ASUS | STRIX X670E | VRM | vrm | high |
| ASRock | X670E | AMD TSI Addr 98h | amd_tsi | high |
| Gigabyte | B550 | temp1 | vendor_wmi_unlabeled | low |

> This table is a representative subset. The authoritative list is
> `BOARD_SENSOR_OVERRIDES` in `src/ventulus/knowledge/sensor_knowledge.py`,
> which also carries the Intel/LGA1700 ASUS EC anchors (Z690/Z790).

### How to add new entries

1. Verify the sensor identity from at least one of:
   - Linux kernel hwmon driver documentation
   - Board vendor manual or BIOS sensor labels
   - Controlled load testing showing clear temperature correlation
2. Add a `BoardSensorOverride` entry to `BOARD_SENSOR_OVERRIDES` in
   `src/ventulus/knowledge/sensor_knowledge.py`
3. Set confidence to `high` only when source documentation is definitive
4. Include a note citing the verification source
5. Add a test in the test suite confirming the override is returned

## Safe vs unsafe claims

### The GUI should assert (safe)

- Sensor driver name (directly from sysfs `name` file via daemon)
- Label text (directly from sysfs `tempN_label` via daemon)
- Type code meaning (defined in kernel documentation)
- That Tctl is not a physical die temperature (kernel-documented)
- That a sensor is "from" a particular driver (factual)
- Confidence level (transparent about classification certainty)

### The GUI should not assert (unsafe)

- Exact physical location of a board thermistor without board-specific documentation
- That a generic `tempN` channel measures any specific component
- That CPUTIN always means "CPU temperature" (board-dependent)
- That Gigabyte WMI channels map to specific components
- That sensor readings from different drivers are directly comparable
- That any Super I/O channel is "connected" without verification

## References

- k10temp: https://docs.kernel.org/hwmon/k10temp.html
- coretemp: https://docs.kernel.org/hwmon/coretemp.html
- sbtsi_temp: https://docs.kernel.org/hwmon/sbtsi_temp.html
- nct6775: https://docs.kernel.org/hwmon/nct6775.html
- nct6683: https://docs.kernel.org/hwmon/nct6683.html
- it87: https://docs.kernel.org/hwmon/it87.html
- asus_ec_sensors: https://docs.kernel.org/hwmon/asus_ec_sensors.html
- asus_wmi_sensors: https://docs.kernel.org/hwmon/asus_wmi_sensors.html
- amdgpu: https://docs.kernel.org/gpu/amdgpu/thermal.html
- spd5118: https://docs.kernel.org/hwmon/spd5118.html
- jc42: https://docs.kernel.org/hwmon/jc42.html
- dell-smm-hwmon: https://docs.kernel.org/hwmon/dell-smm-hwmon.html
- intel-xe-hwmon: https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-xe-hwmon
- intel-i915-hwmon: https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-i915-hwmon
- NVMe specification: https://nvmexpress.org/specifications/
- hwmon sysfs interface: https://docs.kernel.org/hwmon/sysfs-interface.html
