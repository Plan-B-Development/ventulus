"""DEC-499: the update manifest counts only when the pinned repository key signed it."""

from __future__ import annotations

import subprocess

import pytest

from ventulus.services import signature
from ventulus.services.signature import SignatureError, verify_detached

DATA = b'{"schema": 1}\n'


def _verify(signer, data: bytes, sig: bytes, *, key_file=None, fingerprint=None) -> None:
    verify_detached(
        data,
        sig,
        key_file=key_file or signer.key_file,
        fingerprint=fingerprint or signer.fingerprint,
    )


def test_a_good_signature_by_the_pinned_key_is_accepted(update_signer):
    _verify(update_signer, DATA, update_signer.sign(DATA))


def test_altered_data_is_refused(update_signer):
    sig = update_signer.sign(DATA)
    _verify(update_signer, DATA, sig)  # the same signature passes on the original
    with pytest.raises(SignatureError, match="BADSIG"):
        _verify(update_signer, DATA + b" ", sig)


def test_a_signature_by_another_key_is_refused(update_signer):
    """Signed by a key the bundled file does not hold: gpg cannot check it."""
    with pytest.raises(SignatureError):
        _verify(update_signer, DATA, update_signer.sign(DATA, other=True))


def test_a_key_file_holding_another_key_is_refused_by_the_pin(update_signer):
    """A good signature by a key that is not the pinned one never counts."""
    sig = update_signer.sign(DATA, other=True)
    # Positive control: with that key pinned, the same signature is good.
    _verify(
        update_signer,
        DATA,
        sig,
        key_file=update_signer.other_key_file,
        fingerprint=update_signer.other_fingerprint,
    )
    with pytest.raises(SignatureError, match="pinned"):
        _verify(update_signer, DATA, sig, key_file=update_signer.other_key_file)


def test_a_second_key_slipped_into_the_key_file_is_refused(update_signer):
    sig = update_signer.sign(DATA, other=True)
    with pytest.raises(SignatureError, match="pinned"):
        _verify(update_signer, DATA, sig, key_file=update_signer.both_keys_file)


@pytest.mark.parametrize("sig", [b"", b"not a signature", b"\x89PNG\r\n" * 10])
def test_garbage_signatures_are_refused(update_signer, sig):
    with pytest.raises(SignatureError):
        _verify(update_signer, DATA, sig)


def test_an_inline_signed_message_is_refused(update_signer):
    """A signed message (not a detached signature) in the .sig file never counts."""
    inline = update_signer.sign(DATA, detached=False)
    with pytest.raises(SignatureError):
        _verify(update_signer, DATA, inline)


def test_two_signatures_are_refused(update_signer):
    """A signature file carrying two signatures is not "the" signature."""
    both = update_signer.sign(DATA) + update_signer.sign(DATA)
    with pytest.raises(SignatureError):
        _verify(update_signer, DATA, both)


def test_without_gpg_nothing_verifies(update_signer, monkeypatch):
    sig = update_signer.sign(DATA)
    monkeypatch.setattr(signature.shutil, "which", lambda _name: None)
    with pytest.raises(SignatureError, match="gpg is not installed"):
        _verify(update_signer, DATA, sig)


def test_the_bundled_key_is_the_pinned_repository_key(tmp_path):
    """The key every package ships (package data) is the one the pin names."""
    path = signature.bundled_key_path()
    assert path.is_file()
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    listing = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--with-colons", "--show-keys", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    primaries = [line for line in listing.splitlines() if line.startswith("pub:")]
    assert len(primaries) == 1
    first_fpr = next(line for line in listing.splitlines() if line.startswith("fpr:"))
    assert first_fpr.split(":")[9] == signature.REPOSITORY_KEY_FINGERPRINT


def test_the_bundled_key_is_package_data():
    """Built into the wheel, so every package format carries it."""
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    )
    patterns = pyproject["tool"]["setuptools"]["package-data"]["ventulus"]
    rel = signature.bundled_key_path().relative_to(Path(signature.__file__).resolve().parent.parent)
    assert any(rel.match(pattern) for pattern in patterns)


def test_a_good_signature_whose_primary_key_is_not_pinned_is_refused():
    """Behind the import check: gpg's own report must name the pinned key too.

    End to end this cannot fire while the keyring holds only the pinned key, so
    the status lines are given directly.
    """
    pinned = signature.REPOSITORY_KEY_FINGERPRINT
    other = "0" * 40

    def status(primary: str) -> signature.GpgStatus:
        return signature.GpgStatus.parse(
            "[GNUPG:] NEWSIG\n"
            "[GNUPG:] GOODSIG 1234 Test\n"
            f"[GNUPG:] VALIDSIG {primary} 2026-10-16 1 0 4 0 22 10 00 {primary}\n"
        )

    signature._require_good(status(pinned), pinned)  # positive control
    with pytest.raises(SignatureError, match="other than the repository key"):
        signature._require_good(status(other), pinned)
