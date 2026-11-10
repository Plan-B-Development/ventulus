"""Detached OpenPGP signature check for the update manifest (DEC-499 decision 3).

The manifest is signed by the repository key that also signs the pacman, APT and
DNF repositories. The GUI ships that key's public half in the package
(``ventulus/data/ventulus-repository-key.asc``) and pins its fingerprint here. The
manifest counts when at least one of its signatures is good and made by a pinned
primary key; nothing else about the result is trusted.

The pin is a set so the key can be rotated (UPD-a): a GUI release ships the
successor's public key in the key file and its fingerprint in
:data:`REPOSITORY_KEY_FINGERPRINTS` beside the old key's, well before the old key
expires, and only then does the manifest change signer. A file may carry several
signatures; one by a key this GUI does not hold (a successor it predates), or by
an expired or revoked key, does not count and does not refuse. Extending the old
key's expiry does not reach installed GUIs: their key file keeps the
self-signature they shipped with. The whole checklist is the KEY ROTATION
CHECKLIST in pacman-repo's ``.github/workflows/verify.yml``.

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
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: The repository signing keys (pacman-repo ``keys/ventulus.gpg``). The bundled key
#: file must hold exactly these keys. The current key expires 2028-08-03; its
#: successor has to ship here, in a release, well before then (module docstring).
REPOSITORY_KEY_FINGERPRINTS: frozenset[str] = frozenset(
    {
        "4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA",
    }
)

#: Each gpg call is local work on a few KB; anything slower is a wedged gpg.
GPG_TIMEOUT_S = 20.0

#: Status keywords that refuse the manifest outright, whatever else is reported:
#: altered data, or input that is not a detached signature.
_REFUSING_STATUS = frozenset(
    {
        "BADSIG",
        "NODATA",
        "UNEXPECTED",
        # A detached check never prints the signed text; an inline-signed
        # message would.
        "PLAINTEXT",
    }
)

#: Status keywords that stop one signature from counting without refusing the
#: others: a key this GUI does not hold (a successor key it predates), or an
#: expired or revoked key. None of them can make a signature count, so the
#: manifest still needs a good one by a pinned key.
_UNCOUNTED_STATUS = frozenset(
    {
        "ERRSIG",
        "NO_PUBKEY",
        "EXPSIG",
        "EXPKEYSIG",
        "REVKEYSIG",
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
        # gpg ends each status line with LF. str.splitlines() would also split at
        # U+0085/U+2028/U+2029, which gpg passes through unescaped inside a
        # signer's user ID that whoever made the signature chose.
        for raw in text.split("\n"):
            if raw.startswith("[GNUPG:] "):
                parts = raw[len("[GNUPG:] ") :].split()
                if parts:
                    lines.append(tuple(parts))
        return GpgStatus(tuple(lines))

    def named(self, keyword: str) -> list[tuple[str, ...]]:
        return [line for line in self.lines if line[0] == keyword]

    def signatures(self) -> list[GpgStatus]:
        """The lines of each signature: every ``NEWSIG`` starts one."""
        groups: list[list[tuple[str, ...]]] = []
        for line in self.lines:
            if line[0] == "NEWSIG":
                groups.append([])
            if groups:
                groups[-1].append(line)
        return [GpgStatus(tuple(group)) for group in groups]


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
    fingerprints: Iterable[str] = REPOSITORY_KEY_FINGERPRINTS,
    gpg: str = "gpg",
) -> None:
    """Return only if *signature* carries a good signature over *data* by a pinned key.

    The key file must hold exactly the pinned keys: a file carrying any other key
    is refused, so a second key slipped into it cannot sign. *key_file* and
    *fingerprints* exist for the tests; production passes neither.
    """
    if shutil.which(gpg) is None:
        raise SignatureError("gpg is not installed, so the update information cannot be checked")
    key = key_file if key_file is not None else bundled_key_path()
    want = frozenset(fpr.upper() for fpr in fingerprints)
    if not want:
        raise SignatureError("no repository key is pinned")
    with tempfile.TemporaryDirectory(prefix="ventulus-gpg-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(mode=0o700)
        try:
            imported, code = _run(gpg, home, "--import", str(key))
            imported_fprs = {
                line[2].upper() for line in imported.named("IMPORT_OK") if len(line) > 2
            }
            if code != 0 or imported_fprs != want:
                raise SignatureError("the bundled keys are not the pinned repository keys")
            data_path = Path(tmp) / "data"
            sig_path = Path(tmp) / "data.sig"
            data_path.write_bytes(data)
            sig_path.write_bytes(signature)
            status, code = _run(gpg, home, "--verify", str(sig_path), str(data_path))
            _require_good(status, code, want)
        finally:
            _stop_daemons(home)


def _require_good(status: GpgStatus, code: int, want: frozenset[str]) -> None:
    """Accept when at least one signature is good and by a pinned primary key.

    gpg exits non-zero whenever any signature fails to check, including the
    successor key's signature on a GUI that predates it, so the exit status
    cannot decide a multi-signature file. Each signature is judged from its own
    status lines; the exit status still has to be 0 when every signature is good.
    """
    refused = sorted({line[0] for line in status.lines} & _REFUSING_STATUS)
    if refused:
        raise SignatureError(f"the signature is not valid ({', '.join(refused)})")
    signatures = status.signatures()
    if not signatures:
        raise SignatureError("gpg did not report a signature")
    good = [sig for sig in signatures if _counts(sig, want)]
    if not good:
        if any(sig.named("VALIDSIG") and _is_clean(sig) for sig in signatures):
            raise SignatureError("the signature is by a key other than the repository key")
        raise SignatureError("no signature is a good signature by the repository key")
    if len(good) == len(signatures) and (code != 0 or status.named("FAILURE")):
        raise SignatureError(f"gpg refused the signature (exit status {code})")


def _is_clean(sig: GpgStatus) -> bool:
    return not ({line[0] for line in sig.lines} & _UNCOUNTED_STATUS)


def _counts(sig: GpgStatus, want: frozenset[str]) -> bool:
    """One signature's lines: one GOODSIG, one VALIDSIG naming a pinned primary key."""
    if not _is_clean(sig) or len(sig.named("GOODSIG")) != 1:
        return False
    valid = sig.named("VALIDSIG")
    # VALIDSIG <sig-key-fpr> <date> <timestamp> <expire> <version> <reserved>
    #          <pubkey-algo> <hash-algo> <sig-class> <primary-key-fpr>
    return len(valid) == 1 and len(valid[0]) >= 11 and valid[0][10].upper() in want


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
