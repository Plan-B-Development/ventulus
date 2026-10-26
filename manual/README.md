# Ventulus User Manual

**Ventulus** is a desktop fan control application for Linux. It communicates with the `ventulusd` service to monitor temperatures, manage fan speeds, and apply custom fan curves, all from a graphical interface.

It controls fans on an OpenFAN controller, on motherboard hwmon headers, and on AMD discrete GPUs, and it additionally **monitors** AMD, Intel, and NVIDIA discrete GPU temperatures and fan RPM (Intel Arc and NVIDIA fans are read-only: the GPU firmware owns them).

This manual covers every page, setting, and feature of the application.

> **Before you change anything.** Ventulus changes how your fans and pump run, and that affects how your machine is cooled. Hardware support and firmware behaviour vary from one machine to the next. Review what Ventulus detected, and any warning it shows, before you let it control a fan; check temperatures and fan speeds after every change; and keep a way back: [Safety and Recovery](safety-and-recovery.md) says what happens when something goes wrong and how to undo each change. Neither Ventulus nor this manual can guarantee that your hardware is supported, or prevent damage caused by unsupported hardware, wrong configuration, third-party drivers, firmware behaviour or changes you make to your system. The software and this manual are provided **"as is", without warranty of any kind**, under the MIT License (see the LICENSE file shipped with the package), and you use the hardware-control features **at your own risk**.

## Table of contents

1. [Getting Started](getting-started.md): Installation, first launch, and connecting to the daemon
2. [Setup Checklist](setup-checklist.md): Ordered path from fresh install to verified fan control: sensors → readiness → drivers/BIOS → verify → first profile
   - [Migrating from Another Fan Program](migrating.md): Switching from fancontrol, CoolerControl, fan2go or another tool: what to keep, what to stop, and how to check that Ventulus has taken over
3. [Dashboard](dashboard.md): Real-time overview of fans, sensors, and system health
4. [Controls](controls.md): Profiles, fan roles, curves, and manual override
5. [Settings](settings.md): Application preferences, themes, and backup/restore
   - [Updates](updates.md): The opt-in update check: what it sends, what it trusts, and how it hands each install method its upgrade
6. [System Health](diagnostics.md): The Overview, System State, Hardware and Logs pages, section by section
7. [Fan Tests and Reports](fan-tests.md): Test PWM Control, Characterise, Discover Control Path, OpenFAN calibration, the GPU fan test, the PWM Test Report and the recording sessions
8. [Fan Wizard](fan-wizard.md): Guided fan identification and labelling
9. [Profiles and Curves Reference](profiles-and-curves.md): How profiles, fan roles, and curves work together
10. [Hardware Troubleshooting](hardware-troubleshooting.md): From a symptom to its fix: the daemon unreachable, missing sensors, fans or headers, read-only headers, speeds that will not hold, fans at full speed, GPU fans
11. [Safety and Recovery](safety-and-recovery.md): What happens when the app closes, the daemon stops or crashes, a sensor or device disappears; changes that need care; how to undo each change; and how to ask for help
12. [Driver Setup](driver-setup.md): Beginner walkthrough for the out-of-tree motherboard fan drivers (DKMS), Secure Boot, the AMD GPU kernel parameter, verification, and rollback
13. [Understanding Motherboard Fan Control (hwmon)](understanding-fan-control.md): Plain-English primer: what hwmon, sysfs, Super I/O, and PWM are, why drivers and BIOS settings matter, and what keeps your machine safe
14. [OpenFAN Controller](openfan-controller.md): The OpenFAN USB fan controller: detection, serial access, channels, firmware updates, recovery, and troubleshooting

## Reference docs

For deeper hardware and sensor topics, see:

- [Hardware Compatibility](../docs/19_Hardware_Compatibility.md): chip support matrix, kernel driver requirements, vendor quirks, ACPI conflicts
- [AMD Motherboard Fan Control Guide](../docs/21_AMD_Motherboard_Fan_Control_Guide.md): vendor by vendor (ASUS, MSI, ASRock, Gigabyte): which chip and driver each AMD board needs
- [Sensor Interpretation Guide](../docs/20_Sensor_Interpretation_Guide.md): what each sensor name means and which to trust
- [AMD Sensor Interpretation Deep Dive](../docs/22_AMD_Sensor_Interpretation_Deep_Dive.md): Tctl vs Tdie, edge vs junction, and common AMD-specific traps
- [Intel Motherboard Fan Control Guide](../docs/23_Intel_Motherboard_Fan_Control_Guide.md): the same for Intel LGA1700 and LGA1851 boards
- [Cooling Hardware Readiness Guide](../docs/24_Cooling_Hardware_Readiness_Guide.md): what the Hardware page's readiness checks mean and how to clear them

## Screenshots

All screenshots in this manual are captured automatically from the application running in demo mode, so they always show a reproducible setup. The `screenshots/auto/` directory holds the canonical set referenced from these pages.

The screenshots are not installed with the packaged copy under `/usr/share/doc/ventulus/`, so the pages link each image from the project's GitHub repository instead. A viewer that renders Markdown loads them from there when you are online. They show the current development version, which can differ a little from the version you have installed. The whole manual is also [on GitHub](https://github.com/Plan-B-Development/ventulus/tree/main/manual).
