"""Detached OpenPGP signature check for the update manifest (DEC-499 decision 3).

The manifest is signed by the repository key that also signs the pacman, APT and
DNF repositories. The GUI ships that key's public half in the package
(``ventulus/data/ventulus-repository-key.asc``) and pins its fingerprint here; a
signature counts only when gpg reports a good signature whose primary key is the
pinned one. Nothing else about the result is trusted.

gpg runs in a throwaway home directory, so the user's keyring, its trust settings
and any ``gpg.conf`` play no part, and nothing is left behind. ``gpg --verify`` is
used rather than ``gpgv`` because Fedora ships ``gpgv`` in a separate package.
Qt-free; every failure raises :class:`SignatureError`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: The repository signing key (pacman-repo ``keys/ventulus.gpg``). Rotating the
#: key means shipping a GUI with the new key file and this fingerprint before the
#: old key stops signing.
REPOSITORY_KEY_FINGERPRINT = "4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA"

#: Each gpg call is local work on a few KB; anything slower is a wedged gpg.
GPG_TIMEOUT_S = 20.0

#: Status keywords that refuse the signature outright, whatever else is reported.
_REFUSING_STATUS = frozenset(
    {
        "BADSIG",
        "ERRSIG",
        "EXPSIG",
        "EXPKEYSIG",
        "REVKEYSIG",
        "NO_PUBKEY",
        "NODATA",
        "UNEXPECTED",
        "FAILURE",
        # A detached check never prints the signed text; an inline-signed
        # message would.
        "PLAINTEXT",
    }
)


class SignatureError(Exception):
    """The data is not signed by the pinned key, or the check could not run."""


@dataclass(frozen=True)
class GpgStatus:
    """The ``[GNUPG:]`` status lines of one gpg run, keyword then arguments."""

    lines: tuple[tuple[str, ...], ...]

    @staticmethod
    def parse(text: str) -> GpgStatus:
        lines = []
        for raw in text.splitlines():
            if raw.startswith("[GNUPG:] "):
                parts = raw[len("[GNUPG:] ") :].split()
                if parts:
                    lines.append(tuple(parts))
        return GpgStatus(tuple(lines))

    def named(self, keyword: str) -> list[tuple[str, ...]]:
        return [line for line in self.lines if line[0] == keyword]


def bundled_key_path() -> Path:
    """The repository public key the package ships."""
    return Path(__file__).resolve().parent.parent / "data" / "ventulus-repository-key.asc"


def gpg_available(gpg: str = "gpg") -> bool:
    return shutil.which(gpg) is not None


def verify_detached(
    data: bytes,
    signature: bytes,
    *,
    key_file: Path | None = None,
    fingerprint: str = REPOSITORY_KEY_FINGERPRINT,
    gpg: str = "gpg",
) -> None:
    """Return only if *signature* is a good signature over *data* by *fingerprint*.

    The key file must hold exactly the pinned key: a file carrying any other key
    is refused, so a second key slipped into it cannot sign. *key_file* and
    *fingerprint* exist for the tests; production passes neither.
    """
    if shutil.which(gpg) is None:
        raise SignatureError("gpg is not installed, so the update information cannot be checked")
    key = key_file if key_file is not None else bundled_key_path()
    want = fingerprint.upper()
    with tempfile.TemporaryDirectory(prefix="ventulus-gpg-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(mode=0o700)
        try:
            imported, code = _run(gpg, home, "--import", str(key))
            fingerprints = {
                line[2].upper() for line in imported.named("IMPORT_OK") if len(line) > 2
            }
            if code != 0 or fingerprints != {want}:
                raise SignatureError("the bundled key is not the pinned repository key")
            data_path = Path(tmp) / "data"
            sig_path = Path(tmp) / "data.sig"
            data_path.write_bytes(data)
            sig_path.write_bytes(signature)
            status, code = _run(gpg, home, "--verify", str(sig_path), str(data_path))
            _require_good(status, want)
            if code != 0:
                raise SignatureError(f"gpg refused the signature (exit status {code})")
        finally:
            _stop_daemons(home)


def _require_good(status: GpgStatus, want: str) -> None:
    refused = sorted({line[0] for line in status.lines} & _REFUSING_STATUS)
    if refused:
        raise SignatureError(f"the signature is not valid ({', '.join(refused)})")
    if len(status.named("NEWSIG")) != 1 or len(status.named("GOODSIG")) != 1:
        raise SignatureError("expected exactly one good signature")
    valid = status.named("VALIDSIG")
    # VALIDSIG <sig-key-fpr> <date> <timestamp> <expire> <version> <reserved>
    #          <pubkey-algo> <hash-algo> <sig-class> <primary-key-fpr>
    if len(valid) != 1 or len(valid[0]) < 11:
        raise SignatureError("gpg did not report a valid signature")
    if valid[0][10].upper() != want:
        raise SignatureError("the signature is by a key other than the repository key")


def _run(gpg: str, home: Path, *args: str) -> tuple[GpgStatus, int]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GNUPGHOME": str(home),
        "LC_ALL": "C",
        "LANG": "C",
    }
    argv = [
        gpg,
        "--homedir",
        str(home),
        "--batch",
        "--no-tty",
        "--no-options",
        "--no-auto-key-retrieve",
        "--status-fd",
        "1",
        *args,
    ]
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=GPG_TIMEOUT_S,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SignatureError("gpg did not finish in time") from exc
    except OSError as exc:
        raise SignatureError(f"gpg could not be run: {exc.strerror or exc}") from exc
    return GpgStatus.parse(proc.stdout), proc.returncode


def _stop_daemons(home: Path) -> None:
    """Stop any agent or keyboxd gpg started for *home*, so none outlives it."""
    gpgconf = shutil.which("gpgconf")
    if gpgconf is None:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            [gpgconf, "--homedir", str(home), "--kill", "all"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GPG_TIMEOUT_S,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            check=False,
        )
