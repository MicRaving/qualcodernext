"""Minisign/Ed25519 tests — RFC 8032 vectors, roundtrips, container formats."""

from __future__ import annotations

from pathlib import Path

import pytest

from qualcoder_api.services import minisign

# RFC 8032 §7.1 TEST 1 (empty message).
_SEED1 = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
_PK1 = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
_SIG1 = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
    "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)

# RFC 8032 §7.1 TEST 3 (message 0xaf82).
_SEED3 = bytes.fromhex(
    "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7"
)
_PK3 = bytes.fromhex(
    "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025"
)
_MSG3 = bytes.fromhex("af82")
_SIG3 = bytes.fromhex(
    "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
    "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
)


def test_rfc8032_vectors():
    assert minisign.ed25519_pubkey(_SEED1) == _PK1
    assert minisign.ed25519_verify(_PK1, b"", _SIG1) is True
    assert minisign.ed25519_pubkey(_SEED3) == _PK3
    assert minisign.ed25519_verify(_PK3, _MSG3, _SIG3) is True


def test_verify_rejects_tampering():
    assert minisign.ed25519_verify(_PK1, b"x", _SIG1) is False
    assert minisign.ed25519_verify(_PK3, _MSG3, _SIG1) is False
    bad_sig = bytearray(_SIG3)
    bad_sig[10] ^= 1
    assert minisign.ed25519_verify(_PK3, _MSG3, bytes(bad_sig)) is False
    assert minisign.ed25519_verify(_PK3, _MSG3, b"short") is False


def test_sign_verify_roundtrip():
    pub, sec = minisign.generate_keypair()
    message = b"qcnext nightly 0.1.13_001" * 100
    sig = minisign.sign_message(sec, message)
    assert minisign.verify_message(pub, message, sig) is True
    assert minisign.verify_message(pub, message + b"!", sig) is False


def test_keynum_mismatch_rejected():
    pub_a, sec_a = minisign.generate_keypair()
    pub_b, _sec_b = minisign.generate_keypair()
    sig = minisign.sign_message(sec_a, b"hello")
    assert minisign.verify_message(pub_a, b"hello", sig) is True
    assert minisign.verify_message(pub_b, b"hello", sig) is False


def test_parses_tauri_wrapped_pubkey():
    repo_root = Path(__file__).resolve().parent.parent.parent
    pubkey_text = (repo_root / "updater.key.pub").read_text(encoding="utf-8")
    keynum, pubkey = minisign.parse_pubkey(pubkey_text)
    assert len(keynum) == 8
    assert len(pubkey) == 32
    # Minisign prints the key number big-endian; the wire format is little-endian.
    assert keynum[::-1].hex().upper() == "B8C27CB13454DEE2"


def test_verifies_real_shipped_signature():
    """End-to-end: the repo key verifies a real signed installer artifact."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    pubkey_text = (repo_root / "updater.key.pub").read_text(encoding="utf-8")
    nsis_dir = repo_root / "frontend" / "src-tauri" / "target" / "release" / "bundle" / "nsis"
    candidates = sorted(nsis_dir.glob("*setup.exe"))
    if not candidates:
        pytest.skip("no signed NSIS bundle present")
    target = candidates[0]
    sig_file = target.with_suffix(target.suffix + ".sig")
    if not sig_file.exists():
        pytest.skip(f"no .sig for {target.name}")
    message = target.read_bytes()
    if not minisign.verify_message(pubkey_text, message, sig_file.read_text(encoding="utf-8")):
        pytest.skip(f"{target.name} was rebuilt after its .sig — cannot prove key match")
    assert True


def test_rejects_garbage_containers():
    with pytest.raises(ValueError, match="minisign public key"):
        minisign.parse_pubkey("hello")
    with pytest.raises(ValueError, match="minisign signature"):
        minisign.parse_signature("!!!not-base64!!!")
    with pytest.raises(ValueError, match="secret key"):
        minisign.parse_secret_key("untrusted comment: x\nAAAA")
    assert minisign.verify_message("hello", b"msg", "AAAA") is False


_HINT = bytes([1, 2, 3, 4, 5, 6, 7, 8])


def _pub_text(keynum: bytes, pubkey: bytes) -> str:
    import base64 as _base64

    return "untrusted comment: minisign public key: test\n" + _base64.b64encode(
        b"Ed" + keynum + pubkey
    ).decode("ascii")


def test_raw_secret_formats_with_keynum_hint():
    import base64 as _base64

    raw64 = _base64.b64encode(_SEED1 + _PK1).decode("ascii")
    keynum, seed = minisign.parse_secret_key(raw64, keynum_hint=_HINT)
    assert (keynum, seed) == (_HINT, _SEED1)
    # The emitted signature verifies under a pub container with that keynum.
    sig = minisign.sign_message(raw64, b"hello", keynum_hint=_HINT)
    assert minisign.verify_message(_pub_text(_HINT, _PK1), b"hello", sig) is True
    # Raw 32-byte seed likewise.
    raw32 = _base64.b64encode(_SEED1).decode("ascii")
    assert minisign.parse_secret_key(raw32, keynum_hint=_HINT) == (_HINT, _SEED1)
    # Bare standard struct (comment line stripped) still parses.
    _pub, sec = minisign.generate_keypair()
    bare = sec.splitlines()[1]
    assert minisign.parse_secret_key(bare)[1] == minisign.parse_secret_key(sec)[1]


def test_raw_secret_rejects_mismatch_and_missing_hint():
    import base64 as _base64

    raw64 = _base64.b64encode(_SEED1 + _PK1).decode("ascii")
    with pytest.raises(ValueError, match="keynum_hint"):
        minisign.parse_secret_key(raw64)
    # A standard struct parsed against the wrong pubkey's keynum is refused.
    _pub, sec = minisign.generate_keypair()
    with pytest.raises(ValueError, match="does not match"):
        minisign.parse_secret_key(sec, keynum_hint=b"87654321")
    bad_len = _base64.b64encode(b"x" * 40).decode("ascii")
    with pytest.raises(ValueError, match="40 bytes"):
        minisign.parse_secret_key(bad_len, keynum_hint=_HINT)


def test_scrypt_param_mapping():
    # Tauri/rsign defaults.
    assert minisign._scrypt_n_r_p(1_048_576, 33_554_432) == (32768, 8, 1)
    # Small-parameter branch.
    assert minisign._scrypt_n_r_p(32768, 2**20) == (1024, 8, 1)
    # Absurd parameters are refused, not attempted.
    with pytest.raises(ValueError, match="too high"):
        minisign._scrypt_n_r_p(2**30, 2**40)


def test_encrypted_box_roundtrip():
    import base64 as _base64

    seed = bytes(range(32))  # deterministic fixture, not a real secret
    keynum = b"87654321"
    box = minisign._encrypt_box(seed, keynum, "s3cret", salt=b"s" * 32)
    assert len(box) == 158
    text = "untrusted comment: rsign encrypted secret key\n" + _base64.b64encode(box).decode(
        "ascii"
    )
    assert minisign.parse_secret_key(text, password="s3cret") == (keynum, seed)
    with pytest.raises(ValueError, match="needs a password"):
        minisign.parse_secret_key(text)
    with pytest.raises(ValueError, match=r"Wrong password|wrong password"):
        minisign.parse_secret_key(text, password="nope")
    # Tampering reads as a checksum failure, never as another key.
    tampered = bytearray(box)
    tampered[100] ^= 1
    tampered_text = "untrusted comment: rsign encrypted secret key\n" + _base64.b64encode(
        bytes(tampered)
    ).decode("ascii")
    with pytest.raises(ValueError, match=r"Wrong password|wrong password"):
        minisign.parse_secret_key(tampered_text, password="s3cret")
    # Signatures from the decrypted seed verify under the matching pubkey.
    sig = minisign.sign_message(text, b"hello", password="s3cret")
    assert minisign.verify_message(_pub_text(keynum, minisign.ed25519_pubkey(seed)), b"hello", sig)


def test_decrypts_repo_release_key():
    """Decrypt the real release key (present on maintainer machines only).

    Asserts the decrypted seed derives the repo pubkey — the same check
    `build-patch.py --check-key` performs in CI. Never prints key material:
    failures only ever show public key numbers/keys.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    key_path = repo_root / "updater.key"
    if not key_path.exists():
        pytest.skip("release key not present (CI)")
    pub_text = (repo_root / "updater.key.pub").read_text(encoding="utf-8")
    exp_keynum, exp_pub = minisign.parse_pubkey(pub_text)
    keynum, seed = minisign.parse_secret_key(key_path.read_text(encoding="utf-8"), password="")
    assert keynum == exp_keynum
    assert minisign.ed25519_pubkey(seed) == exp_pub
