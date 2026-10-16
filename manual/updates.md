# Updates

Ventulus can tell you when a newer Ventulus or `ventulusd` has been released, and how to install it the way you installed it the first time. The check is **off unless you ask for it**: Ventulus makes no internet connection until you press **Check for updates** or turn the daily check on. It never installs anything itself and never runs a command as root.

If you installed from one of the package repositories (pacman, APT or DNF), your normal system upgrade already brings new versions, and you do not need this page at all. The check is most useful for a [tarball install](getting-started.md#the-tarball), which nothing else keeps up to date.

## Where it is

- **Settings ▸ Updates** holds the check: a **Check for updates** button, the **Check for updates automatically** switch, and what the last check found.
- **About** (at the bottom of the sidebar) shows the Ventulus and `ventulusd` versions you are running, the pair a check compares, and its own **Check for updates** button, which opens Settings ▸ Updates and checks.
- After a check that finds a newer release, a notice across the top of the window names it: *Update available: Ventulus 5.2.0. See Settings ▸ Updates.* **Details** opens the Updates card; **Dismiss** hides the notice until a newer release than that one appears.

## Checking

**Check for updates** checks once, now. The status line then reads *Checked 2026-10-16 09:30 UTC: an update is available*, *… no update available*, or *… no result* followed by the reason.

**Check for updates automatically** is off by default. Turn it on and click **Save Changes** in the page header, and Ventulus checks at most once a day while it is running: it first looks a minute after it starts, then once an hour asks whether a day has passed since the last check. Turn the switch off again (and save) and nothing is sent unless you press the button.

Importing a settings file never turns the daily check on. The switch is a setting of this machine, like the window position, so it is left out of an export and ignored in an import.

## What a check sends, and to whom

One check is one HTTPS request to `plan-b-development.github.io`, the project's GitHub Pages site, for the file `ventulus-updates.json`, plus a second request for its signature `ventulus-updates.json.sig` when the file has changed since the last check. GitHub runs that server, so GitHub sees your IP address and the request, as any web server would.

The request carries nothing about you or your machine. Beyond what the HTTP library always sends, its only headers are `User-Agent: Ventulus/<your version>`, `Accept-Encoding: identity`, and, when Ventulus already has a copy, the `ETag` and date of that copy, so the server can answer "unchanged". No machine id, hardware, profile or setting is sent, and nothing is sent to `ventulusd` or through it: the daemon stays offline.

Ventulus keeps the last file, its signature, the time of the last check and the notice you dismissed in `~/.cache/ventulus/updates/`. Deleting that folder is harmless: the next check fetches everything again.

## What it trusts

The file lists the latest stable version of each component, the SHA-256 and size of every file attached to each release, the oldest `ventulusd` the new Ventulus works with, and the API version the new `ventulusd` speaks. It is signed with the same key that signs the package repositories:

```text
4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA
```

Ventulus ships that key and checks the signature against it, and against that fingerprint, **before it reads anything in the file**. It refuses, and says *Could not verify the update information*, when:

- the signature is missing, bad, or made by another key;
- the file is malformed, in a format this version does not know, or names a pre-release;
- the file is older than one this Ventulus has already accepted. An old file replayed by someone in the middle would otherwise hide a newer release.

A refused or failed check reports a failure, never a result: Ventulus does not say "no update available" when it could not find out.

## What it tells you

For each component the card says how it is installed and how it compares, for example *Ventulus 5.1.0, installed with pacman: 5.2.0 is available.* Ventulus works out how each one was installed by asking the package manager which package owns its files (`pacman -Qqo`, `dpkg-query -S` or `rpm -qf`), then the tarball's install lists. It asks for Ventulus and `ventulusd` separately, so a mixed install is described correctly.

Where an update is available, the card says what to do:

| Installed with | What the card says |
| --- | --- |
| pacman | `sudo pacman -Syu` |
| a `.deb` package | `sudo apt update && sudo apt upgrade` |
| an `.rpm` package | `sudo dnf upgrade --refresh` |
| the tarball | a **Download and verify** button; see [below](#tarball-installs) |
| a source checkout, or a way it could not tell | a link to the release |

If the package's repository is not set up on this machine (you installed a package downloaded from a release), the card first says to add it, as described in the [repository instructions](https://github.com/Plan-B-Development/pacman-repo#readme), and then gives the same command.

Two notes can follow:

- *Update the daemon first*: the new Ventulus needs a newer `ventulusd` than the one running.
- *ventulusd … needs a newer Ventulus*: the new daemon speaks a different API version from this Ventulus, so update both together.

With no daemon connected, the `ventulusd` line says its version is not known. A source checkout's version is never compared.

## Tarball installs

A tarball install has no package manager to hand over to, so the card offers **Download and verify Ventulus 5.2.0** (or `ventulusd`). Ventulus then:

1. downloads the new tarball into your download folder (your desktop's Downloads folder, or your home folder if there is none), as a hidden temporary file;
2. keeps it, under its real name, only if its size and SHA-256 equal what the signed file lists. A download that is cut short, too large or different is deleted, and the card says *Download refused* and why;
3. shows one line that installs it, with a **Copy install commands** button:

```text
cd '/home/you/Downloads' && echo '<sha256>  ventulus-5.2.0-noarch.tar.gz' | sha256sum -c && tar xf ventulus-5.2.0-noarch.tar.gz && sudo ./ventulus-5.2.0-noarch/install.sh
```

Paste it into a terminal. It works as written in bash, zsh and fish. The steps are joined with `&&`, so each runs only if the one before it succeeded: `sha256sum -c` checks the file once more against the signed SHA-256, right before anything runs as root, and stops the line if the file was changed after Ventulus checked it. `install.sh` then checks every file against the tarball's own list before installing, and upgrades the earlier tarball install in place. There is no separate upgrade tool.

If the download folder's path contains a backslash or a control character, which cannot be quoted the same way in all three shells, the card shows no line. Open a terminal in that folder, check the file with `sha256sum` against the value the card shows, unpack it, and run `sudo ./<folder it creates>/install.sh`.

After a `ventulusd` upgrade the installer restarts a running daemon, which gives every fan header back before the new version takes over. After a Ventulus upgrade, restart Ventulus to use the new version.

---

Previous: [Settings](settings.md) | Back to [Table of Contents](README.md)
