"""DEC-499: the update manifest counts only when the pinned repository key signed it."""

from __future__ import annotations

import subprocess

import pytest

from ventulus.services import signature
from ventulus.services.signature import SignatureError, verify_detached

DATA = b'{"schema": 1}\n'


def _verify(signer, data: bytes, sig: bytes, *, key_file=None, fingerprints=None) -> None:
    verify_detached(
        data,
        sig,
        key_file=key_file or signer.key_file,
        fingerprints=fingerprints or (signer.fingerprint,),
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
        fingerprints=(update_signer.other_fingerprint,),
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


# --- Key rotation (UPD-a): a set of pinned keys, at least one good signature ----------


def _pin_both(signer) -> dict:
    return {
        "key_file": signer.both_keys_file,
        "fingerprints": (signer.fingerprint, signer.other_fingerprint),
    }


@pytest.mark.parametrize("signed_by", ["current", "successor", "both"])
def test_with_both_keys_pinned_either_key_or_both_may_sign(update_signer, signed_by):
    """The GUI release that ships the successor key accepts every rotation stage."""
    sig = {
        "current": lambda: update_signer.sign(DATA),
        "successor": lambda: update_signer.sign(DATA, other=True),
        "both": lambda: update_signer.sign(DATA, both=True),
    }[signed_by]()
    _verify(update_signer, DATA, sig, **_pin_both(update_signer))


def test_a_dual_signed_manifest_passes_a_gui_that_predates_the_successor(update_signer):
    """Pinning only the current key, the successor's signature does not count but
    does not refuse: gpg reports it as an unknown key and exits non-zero."""
    _verify(update_signer, DATA, update_signer.sign(DATA, both=True))


def test_an_unknown_key_signature_before_the_good_one_does_not_refuse(update_signer):
    """Reversed order: gpg's trailing FAILURE then lands among the good signature's lines."""
    sig = update_signer.sign(DATA, other=True) + update_signer.sign(DATA)
    _verify(update_signer, DATA, sig)


def test_a_dual_signed_manifest_passes_a_gui_that_pins_only_the_successor(update_signer):
    _verify(
        update_signer,
        DATA,
        update_signer.sign(DATA, both=True),
        key_file=update_signer.other_key_file,
        fingerprints=(update_signer.other_fingerprint,),
    )


def test_a_dual_signed_manifest_over_altered_data_is_refused(update_signer):
    sig = update_signer.sign(DATA, both=True)
    with pytest.raises(SignatureError, match="BADSIG"):
        _verify(update_signer, DATA + b" ", sig, **_pin_both(update_signer))


def test_one_bad_signature_beside_a_good_one_refuses_the_manifest(update_signer):
    """A good signature cannot carry a second one that fails over this data."""
    good = update_signer.sign(DATA)
    bad = update_signer.sign(DATA + b" ", other=True)
    _verify(update_signer, DATA, good, **_pin_both(update_signer))  # positive control
    with pytest.raises(SignatureError, match="BADSIG"):
        _verify(update_signer, DATA, good + bad, **_pin_both(update_signer))


def test_a_key_file_short_of_the_pinned_set_is_refused(update_signer):
    """The key file must hold every pinned key, so the pin and the file move together."""
    with pytest.raises(SignatureError, match="pinned"):
        _verify(
            update_signer,
            DATA,
            update_signer.sign(DATA),
            fingerprints=(update_signer.fingerprint, update_signer.other_fingerprint),
        )


def test_an_empty_pin_refuses(update_signer):
    with pytest.raises(SignatureError, match="no repository key"):
        verify_detached(
            DATA, update_signer.sign(DATA), key_file=update_signer.key_file, fingerprints=()
        )


def test_two_signatures_by_the_pinned_key_are_accepted(update_signer):
    both = update_signer.sign(DATA) + update_signer.sign(DATA)
    _verify(update_signer, DATA, both)


def test_without_gpg_nothing_verifies(update_signer, monkeypatch):
    sig = update_signer.sign(DATA)
    monkeypatch.setattr(signature.shutil, "which", lambda _name: None)
    with pytest.raises(SignatureError, match="gpg is not installed"):
        _verify(update_signer, DATA, sig)


def test_the_bundled_keys_are_the_pinned_repository_keys(tmp_path):
    """The keys every package ships (package data) are the ones the pin names."""
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
    # A primary key's fpr: record follows its pub: record; subkeys' follow sub:.
    lines = listing.splitlines()
    primaries = {
        lines[i + 1].split(":")[9]
        for i, line in enumerate(lines)
        if line.startswith("pub:") and lines[i + 1].startswith("fpr:")
    }
    assert primaries == signature.REPOSITORY_KEY_FINGERPRINTS
    assert len(primaries) == sum(line.startswith("pub:") for line in lines)


def test_the_bundled_keys_pass_the_import_check_with_the_production_defaults(monkeypatch):
    """No test key: the shipped file and pin reach the signature check together."""
    reached = []

    def spy(status, code, want):
        reached.append(want)
        raise SignatureError("stop here")

    monkeypatch.setattr(signature, "_require_good", spy)
    with pytest.raises(SignatureError, match="stop here"):
        verify_detached(DATA, b"")
    assert reached == [signature.REPOSITORY_KEY_FINGERPRINTS]


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
    pinned = frozenset({PINNED})

    signature._require_good(_status(_good(PINNED)), 0, pinned)  # positive control
    with pytest.raises(SignatureError, match="other than the repository key"):
        signature._require_good(_status(_good(OTHER)), 0, pinned)


PINNED = "A" * 40
OTHER = "0" * 40


def _good(primary: str) -> str:
    return (
        "[GNUPG:] NEWSIG\n"
        "[GNUPG:] GOODSIG 1234 Test\n"
        f"[GNUPG:] VALIDSIG {primary} 2026-10-16 1 0 4 0 22 10 00 {primary}\n"
    )


def _status(*sigs: str) -> signature.GpgStatus:
    return signature.GpgStatus.parse("".join(sigs))


@pytest.mark.parametrize(
    "uncounted",
    [
        # The current key, expired or revoked in this GUI's key file, beside its successor.
        "[GNUPG:] NEWSIG\n[GNUPG:] EXPKEYSIG 1234 Old\n"
        f"[GNUPG:] VALIDSIG {OTHER} 2026-10-16 1 0 4 0 22 10 00 {OTHER}\n",
        "[GNUPG:] NEWSIG\n[GNUPG:] REVKEYSIG 1234 Old\n"
        f"[GNUPG:] VALIDSIG {OTHER} 2026-10-16 1 0 4 0 22 10 00 {OTHER}\n",
        "[GNUPG:] NEWSIG\n[GNUPG:] EXPSIG 1234 Old\n",
    ],
)
def test_an_expired_or_revoked_signature_does_not_count_or_refuse(uncounted):
    pinned = frozenset({PINNED, OTHER})
    signature._require_good(_status(uncounted, _good(PINNED)), 0, pinned)
    with pytest.raises(SignatureError, match="no signature is a good signature"):
        signature._require_good(_status(uncounted), 0, pinned)


def test_a_pinned_key_that_also_reports_expiry_does_not_count():
    """GOODSIG and EXPKEYSIG in one signature's lines: the signature does not count."""
    mixed = _good(PINNED) + "[GNUPG:] EXPKEYSIG 1234 Test\n"
    with pytest.raises(SignatureError, match="no signature is a good signature"):
        signature._require_good(_status(mixed), 0, frozenset({PINNED}))


def test_a_failure_with_every_signature_good_is_refused():
    """The exit status still decides when no signature explains a non-zero exit."""
    pinned = frozenset({PINNED})
    signature._require_good(_status(_good(PINNED)), 0, pinned)  # positive control
    with pytest.raises(SignatureError, match="exit status 2"):
        signature._require_good(_status(_good(PINNED)), 2, pinned)
    with pytest.raises(SignatureError, match="exit status 0"):
        signature._require_good(
            _status(_good(PINNED), "[GNUPG:] FAILURE gpg-exit 33554433\n"), 0, pinned
        )


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85", "\r"])
def test_status_lines_split_only_at_newline(separator):
    """Text gpg prints unescaped inside a line cannot start a status line of its own."""
    injected = (
        "[GNUPG:] NEWSIG attacker"
        f"{separator}[GNUPG:] GOODSIG 1234 X"
        f"{separator}[GNUPG:] VALIDSIG {PINNED} 2026-10-16 1 0 4 0 22 10 00 {PINNED}\n"
        "[GNUPG:] ERRSIG 8F70FF98B7D1524A 22 10 00 1794269352 9 X\n"
        "[GNUPG:] NO_PUBKEY 8F70FF98B7D1524A\n"
    )
    status = signature.GpgStatus.parse(injected)
    assert [line[0] for line in status.lines] == ["NEWSIG", "ERRSIG", "NO_PUBKEY"]
    with pytest.raises(SignatureError):
        signature._require_good(status, 2, frozenset({PINNED}))


def test_no_signature_at_all_is_refused():
    with pytest.raises(SignatureError, match="did not report a signature"):
        signature._require_good(_status("[GNUPG:] KEY_CONSIDERED x 0\n"), 0, frozenset({PINNED}))
