# AMD Sensor Interpretation Deep Dive

What the temperatures on an AMD desktop actually measure, and how sure the GUI is
about each. This page covers the AMD-specific sources: the CPU's own sensors, SB-TSI,
the ASUS WMI driver of the AM4 era, and the GPU. The classification rules for every
driver, the confidence levels and the general quirks are in the
[Sensor Interpretation Guide](20_Sensor_Interpretation_Guide.md).

## "CPU temperature" means different things

The same idea, "CPU temperature", can mean quite different readings depending on the
kernel driver that produced it:

| Source | What it measures | Common label |
|---|---|---|
| `k10temp` Tctl | A control value the platform firmware uses for cooling decisions; not a physical temperature | "CPU" in many tools |
| `k10temp` Tdie | The measured CPU die temperature | "Tdie" |
| `nct6683` AMD TSI Addr 98h | The board's reading of the CPU through the AMD SB-TSI interface | "AMD TSI Addr 98h" |
| `nct6775` CPUTIN | A board-side CPU temperature input on the Super-I/O; unconnected on some boards | "CPUTIN" |
| `asus_ec_sensors` CPU Package | The CPU package temperature as the ASUS embedded controller reads it | "CPU" or "CPU Package" |

The GUI classifies each reading from **driver name + label + temp_type code + board
vendor**. Only that combination reliably tells you what a reading represents.

## k10temp: the CPU's own sensors

**Kernel docs:** https://docs.kernel.org/hwmon/k10temp.html

The **highest-confidence** source for CPU temperatures on Ryzen. The data comes from
the CPU's internal thermal monitoring, read through PCI configuration space and, on Zen
parts, the SMN (System Management Network) registers, not through MSRs.

### Tctl: the control temperature

The kernel documentation is explicit:

> "Tctl is a non-physical temperature on an arbitrary scale measured in
> degrees. It does not represent an actual physical temperature like die
> or case temperature."

Tctl is the value the platform uses to drive cooling. The driver's offset table
(`tctl_offset_table` in `k10temp.c`, checked at 7.3-rc4) covers only Family 17h parts:
Ryzen 5 1600X and Ryzen 7 1700X / 1800X (Tctl = Tdie + 20 °C), Ryzen 7 2700X (+10 °C)
and Threadripper 19xx / 29xx (+27 °C). Later CPUs publish no offset and no separate
Tdie.

**GUI classification:** `cpu_control` at `high` confidence, with a note that it is not
a direct physical reading.

### Tdie: the die temperature

Where the driver exports it, this is the measured die temperature. It exports it
(`temp2`) **only** for the Family 17h offset parts above. Zen 2 and later CPUs,
including every Ryzen 3000–9000 part, publish Tctl and the Tccd readings but no Tdie.

**GUI classification:** `cpu_die` at `high` confidence.

### Tccd: per-CCD temperatures

Per-CCD (Core Complex Die) temperatures, on Zen 2 and later CPUs with CCDs (Tccd1,
Tccd2, …). The kernel doc still says "up to 8", but the source labels up to Tccd16 from
7.3 (Turin-class parts have 16 CCDs). Not every CPU exposes them.

**Kernel 7.3-rc1 to rc3 reported false Tccd readings on Zen 5 mobile** (Strix Point,
family 1Ah models 20h–2Fh): a Turin CCD range wrongly included those models, producing
values such as `Tccd4: +148.6°C`. Fixed in 7.3-rc4 by
[`451b1c19dc7c`](https://git.kernel.org/torvalds/c/451b1c19dc7c); stable 7.2.y was
never affected. Because the daemon treats every `k10temp` channel as a CPU temperature,
a Strix Point machine on those release candidates would trip the thermal emergency and
run its fans at 100%.

**GUI classification:** `cpu_ccd` at `high` confidence.

### What to expect

| CPU | Tdie | Tctl | TccdN | Offset |
|---|---|---|---|---|
| Ryzen 5 1600X, Ryzen 7 1700X / 1800X | Yes | Yes (= Tdie + 20 °C) | — | 20 °C |
| Ryzen 7 2700X | Yes | Yes (= Tdie + 10 °C) | — | 10 °C |
| Threadripper 19xx / 29xx | Yes | Yes (= Tdie + 27 °C) | — | 27 °C |
| Other Zen / Zen+ | No | Yes | — | none published |
| Zen 2 and later (Ryzen 3000–9000, Threadripper 3000+) | No | Yes | Yes, varies by SKU | none published |

### Which CPU sensor Ventulus uses

Many tools, and many users, treat Tctl as "the CPU temperature". That is fine for
cooling, but misleading on the offset parts, where it reads hotter than the die. The
GUI labels Tctl a control value and never presents it as the actual die temperature.

Nothing in the GUI prefers Tdie when it picks a sensor, though. The preferred-CPU
recommendation (the ★ in Settings → preferred CPU sensor) is the daemon's
`default_cpu`, which ranks Tctl first, then a package reading, then Tdie
(`hwmon/classify.rs::cpu_class_rank`). So on the five offset parts it recommends the
offset Tctl. The AIO setup's CPU fallback takes the first CPU sensor, in the daemon's
list order, whose label names a package, Tctl or Tdie. The thermal safety rules use
the hottest CPU sensor whatever you pick.

## SB-TSI: the board's view of the CPU

**Kernel docs:** https://docs.kernel.org/hwmon/sbtsi_temp.html

SB-TSI (SideBand Temperature Sensor Interface) is an SMBus-compatible interface on AMD
SoCs. It gives the board and its firmware a CPU temperature feed separate from the
CPU-internal `k10temp` path.

On a desktop it usually arrives through the Super-I/O driver, as a label such as
`AMD TSI Addr 98h`, rather than as a standalone device. Through `nct6683` it carries
temp_type code 5. The standalone driver's hwmon device is named **`sbtsi`** (only the
module is `sbtsi_temp`), and from kernel 7.3 it depends on ARM / ARM64: it is meant
for the BMC, not the managed host, so x86 desktops stop seeing it.

The kernel documentation says: "The SB-TSI address is normally 98h for socket 0 and
90h for socket 1, but it could vary based on hardware address select pins." Those are
8-bit I2C addresses; the 7-bit equivalents are 0x4C and 0x48. A single-socket desktop
Ryzen board almost always shows 98h; 90h matters on dual-socket server and workstation
boards.

An SB-TSI reading is **not** `k10temp` Tdie (a different data path that may report a
different value), a random motherboard thermistor, or a VRM or chipset sensor.

**GUI classification:** `amd_tsi` at `medium_high` confidence.

## Nuvoton chips on AMD boards

The Nuvoton rules are the same on every platform; the
[Sensor Interpretation Guide](20_Sensor_Interpretation_Guide.md#nct6683--nct6686--nct6687-nuvoton-newer-family)
has them. Three points matter most on AMD boards:

- **The `nct6683` kernel documentation lists AMD boards as reported working:** ASRock
  X570, ASRock X670E, ASRock B650 Steel Legend WiFi, MSI B550, MSI X670-P and MSI
  X870E. Its `AMD TSI Addr 9xh` channels are the board's SB-TSI feed (`medium_high`);
  its `Thermistor N` channels are real but cannot be placed without board
  documentation (`medium`).
- **`PECI DIMM` is memory, not the CPU.** It carries the PECI type code 6, like the
  CPU's own PECI channels, so the GUI checks for `DIMM` before the type code and the
  daemon keeps these channels out of the CPU input to the safety rules.
- **On ASUS boards, `CPUTIN` is often unconnected.** On any nct6775-family chip with an
  ASUS board vendor, the GUI marks `CPUTIN` bogus and the daemon keeps it out of the
  safety rules, because a floating pin can read a plausible constant such as 115 °C.
  The [ASUS CPUTIN quirk](20_Sensor_Interpretation_Guide.md#asus-cputin-bogus-on-the-nct6775-family)
  explains both rules.

## ASUS WMI sensors (AM4 and X399 boards)

**Kernel docs:** https://docs.kernel.org/hwmon/asus_wmi_sensors.html

`asus_wmi_sensors` uses the same label vocabulary as `asus_ec_sensors` (VRM, T_Sensor,
Water In/Out and so on), read through WMI (Windows Management Instrumentation) ACPI
methods. It is AMD-only: it binds on 16 older ASUS boards, matched by exact name:
PRIME X399-A, PRIME X470-PRO, ROG CROSSHAIR VI EXTREME, CROSSHAIR VI HERO, ROG
CROSSHAIR VI HERO (WI-FI AC), ROG CROSSHAIR VII HERO, ROG CROSSHAIR VII HERO (WI-FI),
ROG STRIX B450-E GAMING, ROG STRIX B450-F GAMING, ROG STRIX B450-F GAMING II, ROG STRIX
B450-I GAMING, ROG STRIX X399-E GAMING, ROG STRIX X470-F GAMING, ROG STRIX X470-I
GAMING, ROG ZENITH EXTREME and ROG ZENITH EXTREME ALPHA (the driver's table; the kernel
doc lists 15, omitting the B450-F GAMING II). No X570 board is on the list. It
supplies sensors only; on the boards checked, the fans are on an ITE IT8665E.

**Its classification sits one level lower** than `asus_ec_sensors` (`medium_high`
instead of `high`), because the WMI interface has documented reliability problems. A
label containing `CPU` is the board's reading of the CPU (`cpu_board_side`), not a die
sensor, and a label that matches no rule is `medium`. Water labels are classified as
coolant first, by the rule that applies to every driver.

**Polling can make the firmware misbehave.** The kernel documentation names three
failure modes: fans stop, fans stick at maximum speed, or readings freeze. The PRIME
X470-PRO is "particularly bad", and the risk rises with polling frequency. The kernel
names no safe polling rate, so neither does this guide. The driver reads each WMI
sensor group from the BIOS at most about once a second however many programs read its
files, so extra readers add no WMI calls. What to do:

- Update to a BIOS whose WMI method version is 2 or later; the driver refuses older
  versions, and the kernel says a newer one should fix the misbehaviour.
- Run an extended soak test while polling before you leave the machine unattended.

Every `asus_wmi_sensors` classification carries a standing note about this.

## amdgpu: GPU sensors

GPU sensors are high confidence because the `amdgpu` driver defines exact label
semantics:

| Label | Meaning | Notes |
|---|---|---|
| `edge` | GPU edge temperature | General die temperature |
| `junction` | GPU hotspot / junction temperature | Hottest point on the die; the primary thermal limit |
| `mem` | GPU HBM / VRAM temperature | Memory temperature |

GPU sensors report `source: "amd_gpu"` (not `"hwmon"`) and use the PCI BDF address for
an identity that survives reboots. The GPU's fan is outside the daemon's thermal
safety rules: its firmware protects itself.

## Confidence by board vendor

| Vendor | Driver | Typical confidence | Notes |
|---|---|---|---|
| ASUS | `asus_ec_sensors` | high | The best semantic labels |
| ASUS | `asus_wmi_sensors` | medium_high | Same labels, WMI polling risk |
| ASUS | `nct6775` with labels | medium | Source configured by firmware |
| ASUS | `nct6775`-family `CPUTIN` | low (bogus) | Kernel-documented |
| ASRock | `nct6683` with AMD TSI labels | medium_high | Source class is reliable |
| ASRock | `nct6683` with thermistor labels | medium | Physical location unknown |
| MSI | `nct6683`/`nct6687` with labels | medium | Source class reliable, location often unknown |
| MSI | Generic `tempN` | low | No semantic information |
| Gigabyte | `gigabyte_wmi` | low | No labels |
| Gigabyte | `it87` with labels | medium | Only when labels are present |
| Gigabyte | `it87` `tempN` | low | No semantic information |
| Any | `k10temp` | high | CPU-internal |

## Sources

**Linux kernel documentation:**
[k10temp](https://docs.kernel.org/hwmon/k10temp.html) ·
[sbtsi_temp](https://docs.kernel.org/hwmon/sbtsi_temp.html) ·
[nct6683](https://docs.kernel.org/hwmon/nct6683.html) ·
[asus_wmi_sensors](https://docs.kernel.org/hwmon/asus_wmi_sensors.html) ·
[hwmon sysfs interface](https://docs.kernel.org/hwmon/sysfs-interface.html)

**Linux kernel source:**
[nct6683.c](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6683.c)
