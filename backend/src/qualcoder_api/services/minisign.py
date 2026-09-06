"""Minisign-compatible Ed25519 signing/verification — stdlib only.

Delta/nightly patches (``X.Y.Z_NNN`` zips from ``scripts/build-patch.py``)
are verified with the SAME keypair as the Tauri updater (``updater.key`` /
``updater.key.pub``), so a patch attacker needs the release signing key.
No third-party dependency: Ed25519 over Curve25519 is implemented in pure
Python (RFC 8032) — verification takes ~100 ms and runs at most once per
patch install, which is negligible next to the download.

Only unencrypted secret keys are supported (the release pipeline uses an
empty ``TAURI_SIGNING_PRIVATE_KEY_PASSWORD``). Encrypted ``rsign`` keys
raise ``ValueError`` instead of silently mis-signing.

Accepted encodings (all base64, all handled by the ``*_text`` helpers):

- public key: standard 2-line minisign ``.pub`` OR the single-line
  outer-base64 wrapping Tauri writes (as in the repo ``updater.key.pub``).
- signature: the 100-char base64 middle line of a minisign ``.sig``
  (``sig_alg || keynum || sig`` struct) OR a raw 64-byte signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

# --- Curve25519 / Ed25519 (RFC 8032, pure Python) ----------------------------

_B = 256
_Q = (1 << 255) - 19
_L = (1 << 252) + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_By = (4 * pow(5, _Q - 2, _Q)) % _Q
_Bx = _xrecover(_By)
_BASE = (_Bx % _Q, _By % _Q, 1, (_Bx * _By) % _Q)


def _edwards_add(p: tuple[int, int, int, int], q: tuple[int, int, int, int]):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = ((y1 - x1) * (y2 - x2)) % _Q
    b = ((y1 + x1) * (y2 + x2)) % _Q
    c = (t1 * 2 * _D * t2) % _Q
    d = (z1 * 2 * z2) % _Q
    e = (b - a) % _Q
    f = (d - c) % _Q
    g = (d + c) % _Q
    h = (b + a) % _Q
    return ((e * f) % _Q, (g * h) % _Q, (f * g) % _Q, (e * h) % _Q)


def _scalarmult(point: tuple[int, int, int, int], scalar: int):
    result = (0, 1, 1, 0)
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = _edwards_add(result, addend)
        addend = _edwards_add(addend, addend)
        scalar >>= 1
    return result


def _encode_point(point: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = point
    zi = pow(z, _Q - 2, _Q)
    x_aff = (x * zi) % _Q
    y_aff = (y * zi) % _Q
    bits = [(y_aff >> i) & 1 for i in range(_B - 1)] + [(x_aff & 1)]
    return bytes(sum(bits[i] << (i % 8) for i in range(j * 8, j * 8 + 8)) for j in range(_B // 8))


def _decode_point(data: bytes) -> tuple[int, int, int, int] | None:
    if len(data) != 32:
        return None
    y = sum(((data[i // 8] >> (i % 8)) & 1) << i for i in range(_B - 1))
    sign = (data[31] >> 7) & 1
    if y >= _Q:
        return None
    x = _xrecover(y)
    if (x & 1) != sign:
        x = _Q - x
    return (x, y, 1, (x * y) % _Q)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    """Sign ``message`` with a 32-byte Ed25519 seed; returns 64-byte sig."""
    if len(seed) != 32:
        raise ValueError("ed25519 seed must be 32 bytes")
    h = _sha512(seed)
    a = 2 ** (_B - 2) + sum(2**i for i in range(3, _B - 2) if (h[i // 8] >> (i % 8)) & 1)
    prefix = h[_B // 8 :]
    nonce = int.from_bytes(_sha512(prefix + message), "little") % _L
    r_point = _encode_point(_scalarmult(_BASE, nonce))
    pubkey = _encode_point(_scalarmult(_BASE, a))
    challenge = int.from_bytes(_sha512(r_point + pubkey + message), "little") % _L
    s = (nonce + challenge * a) % _L
    return r_point + s.to_bytes(32, "little")


def ed25519_verify(pubkey: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a 64-byte Ed25519 ``signature`` of ``message``."""
    if len(pubkey) != 32 or len(signature) != 64:
        return False
    r_bytes, s_bytes = signature[:32], signature[32:]
    s_value = int.from_bytes(s_bytes, "little")
    if s_value >= _L:
        return False
    a_point = _decode_point(pubkey)
    r_point = _decode_point(r_bytes)
    if a_point is None or r_point is None:
        return False
    challenge = int.from_bytes(_sha512(r_bytes + pubkey + message), "little") % _L
    left = _scalarmult(_BASE, s_value)
    right = _edwards_add(r_point, _scalarmult(a_point, challenge))
    return _encode_point(left) == _encode_point(right)


def ed25519_pubkey(seed: bytes) -> bytes:
    """Derive the 32-byte Ed25519 public key for a 32-byte ``seed``."""
    if len(seed) != 32:
        raise ValueError("ed25519 seed must be 32 bytes")
    h = _sha512(seed)
    a = 2 ** (_B - 2) + sum(2**i for i in range(3, _B - 2) if (h[i // 8] >> (i % 8)) & 1)
    return _encode_point(_scalarmult(_BASE, a))


# --- Minisign key/signature containers ---------------------------------------

_SIG_ALG = b"Ed"


def _unwrap_outer_base64(text: str) -> str:
    """Unwrap Tauri's single-line outer-base64 key/sig files, if present."""
    stripped = (text or "").strip()
    if "\n" in stripped:
        return stripped
    try:
        decoded = base64.b64decode(stripped).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return stripped
    if decoded.startswith("untrusted comment:"):
        return decoded.strip()
    return stripped


def parse_pubkey(text: str) -> tuple[bytes, bytes]:
    """Parse a minisign public key → ``(keynum, pubkey)`` (8 + 32 bytes)."""
    lines = [line for line in _unwrap_outer_base64(text).splitlines() if line.strip()]
    if len(lines) != 2 or not lines[0].startswith("untrusted comment:"):
        raise ValueError("not a minisign public key (expected 2 lines)")
    try:
        raw = base64.b64decode(lines[1].strip())
    except ValueError as err:
        raise ValueError(f"invalid minisign public key encoding: {err}") from err
    if len(raw) != 42 or raw[:2] != _SIG_ALG:
        raise ValueError("invalid minisign public key (expected Ed + keynum + 32 bytes)")
    return raw[2:10], raw[10:42]


def parse_signature(text: str) -> tuple[bytes, bytes]:
    """Parse a minisign signature line → ``(keynum, sig)`` (8 + 64 bytes).

    Accepts the full 2/4-line ``.sig`` text (uses the first signature line),
    the bare 100-char base64 struct, or a bare 64-byte raw signature (which
    carries no key number — returned as ``b""``).
    """
    stripped = _unwrap_outer_base64(text).strip()
    candidate = stripped
    for line in stripped.splitlines():
        line = line.strip()
        if line and not line.startswith(("untrusted comment:", "trusted comment:")):
            candidate = line
            break
    try:
        raw = base64.b64decode(candidate)
    except ValueError as err:
        raise ValueError(f"invalid minisign signature encoding: {err}") from err
    if len(raw) == 64:
        return b"", raw
    if len(raw) != 74 or raw[:2] != _SIG_ALG:
        raise ValueError("invalid minisign signature (expected Ed + keynum + 64 bytes)")
    return raw[2:10], raw[10:74]


def parse_secret_key(
    text: str, *, keynum_hint: bytes | None = None, password: str | None = None
) -> tuple[bytes, bytes]:
    """Parse a minisign secret key → ``(keynum, seed)``.

    Accepted encodings for the payload (a 2-line file with an ``untrusted
    comment:`` first line, or the bare base64 payload alone):

    - password-encrypted rsign box (158 bytes — what ``tauri signer
      generate`` writes, even with an empty password); needs ``password``
      (``""`` is valid, ``None`` means missing);
    - standard unencrypted struct (74 bytes: ``Ed + keynum + seed + pub``);
    - raw 64 bytes (``seed + pub``) or raw 32-byte seed — these carry no key
      number, so ``keynum_hint`` (e.g. from the matching ``.pub``) is
      required and the derived pubkey is NOT self-checkable here (callers
      must compare against the known pubkey — see ``build-patch.py
      --check-key``).
    """
    stripped = _unwrap_outer_base64(text).strip()
    lines = [line for line in stripped.splitlines() if line.strip()]
    if len(lines) == 2 and lines[0].startswith("untrusted comment:"):
        payload = lines[1].strip()
    elif len(lines) == 1:
        payload = lines[0].strip()
    else:
        raise ValueError("not a minisign secret key (expected 2 lines or a bare payload)")
    try:
        raw = base64.b64decode(payload)
    except ValueError as err:
        raise ValueError(f"invalid minisign secret key encoding: {err}") from err
    if len(raw) == 158 and raw[:2] == _SIG_ALG:
        # Password-encrypted rsign box (what `tauri signer generate` writes,
        # even with an empty password): scrypt stream-XOR + Blake2b checksum.
        if password is None:
            raise ValueError("encrypted secret key needs a password (pass password=...)")
        return _decrypt_box(raw, password, keynum_hint)
    if len(raw) == 74 and raw[:2] == _SIG_ALG:
        secret = raw[10:74]
        seed, pubkey = secret[:32], secret[32:]
        if ed25519_pubkey(seed) != pubkey:
            raise ValueError("minisign secret key checksum failed (seed/pubkey mismatch)")
        keynum = raw[2:10]
        if keynum_hint is not None and keynum_hint != keynum:
            raise ValueError("secret key number does not match the expected public key")
        return keynum, seed
    if len(raw) in (64, 32):
        if keynum_hint is None or len(keynum_hint) != 8:
            raise ValueError("raw secret carries no key number — pass keynum_hint")
        seed, pubkey = (raw[:32], raw[32:]) if len(raw) == 64 else (raw, ed25519_pubkey(raw))
        if len(raw) == 64 and ed25519_pubkey(seed) != pubkey:
            raise ValueError("raw secret checksum failed (seed/pubkey mismatch)")
        return keynum_hint, seed
    raise ValueError(
        f"invalid minisign secret key (got {len(raw)} bytes, expected 158/74/64/32)"
    )


#: rsign encrypted-box layout (all integers little-endian).
_ENC_SIG_ALG = (0, 2)
_ENC_KDF_ALG = (2, 4)
_ENC_CHK_ALG = (4, 6)
_ENC_SALT = (6, 38)
_ENC_OPSLIMIT = (38, 46)
_ENC_MEMLIMIT = (46, 54)
_ENC_KEYNUM = (54, 62)
_ENC_SK = (62, 126)
_ENC_CHK = (126, 158)
_ENC_BOX_LEN = 158
_ENC_KDF_SCRYPT = b"Sc"
_ENC_CHK_BLAKE2B = b"B2"
_ENC_STREAM_LEN = 104
_ENC_MEMLIMIT_MAX = 1_073_741_824


def _scrypt_n_r_p(opslimit: int, memlimit: int) -> tuple[int, int, int]:
    """Port of rust-minisign ``raw_scrypt_params`` → ``(N, r, p)``."""
    opslimit = max(32768, opslimit)
    n_log2 = 1
    r = 8
    if opslimit < memlimit // 32:
        p = 1
        maxn = opslimit // (r * 4)
        while n_log2 < 63:
            if (1 << n_log2) > maxn // 2:
                break
            n_log2 += 1
    else:
        maxn = memlimit // (r * 128)
        while n_log2 < 63:
            if (1 << n_log2) > maxn // 2:
                break
            n_log2 += 1
        maxrp = min(0x3FFFFFFF, (opslimit // 4) // (1 << n_log2))
        p = maxrp // r
    if n_log2 > 20:
        raise ValueError("scrypt parameters too high")
    return (1 << n_log2, r, p)


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


def _decrypt_box(raw: bytes, password: str, keynum_hint: bytes | None) -> tuple[bytes, bytes]:
    """Decrypt a 158-byte rsign box → ``(keynum, seed)`` (raises on failure)."""
    if raw[_ENC_KDF_ALG[0] : _ENC_KDF_ALG[1]] != _ENC_KDF_SCRYPT:
        raise ValueError("unsupported secret-key KDF (expected scrypt)")
    if raw[_ENC_CHK_ALG[0] : _ENC_CHK_ALG[1]] != _ENC_CHK_BLAKE2B:
        raise ValueError("unsupported secret-key checksum (expected Blake2b)")
    salt = raw[_ENC_SALT[0] : _ENC_SALT[1]]
    opslimit = int.from_bytes(raw[_ENC_OPSLIMIT[0] : _ENC_OPSLIMIT[1]], "little")
    memlimit = int.from_bytes(raw[_ENC_MEMLIMIT[0] : _ENC_MEMLIMIT[1]], "little")
    if memlimit > _ENC_MEMLIMIT_MAX:
        raise ValueError("scrypt parameters too high")
    n, r, p = _scrypt_n_r_p(opslimit, memlimit)
    stream = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=memlimit * 2 + (1 << 20),
        dklen=_ENC_STREAM_LEN,
    )
    keynum = _xor_bytes(raw[_ENC_KEYNUM[0] : _ENC_KEYNUM[1]], stream[0:8])
    sk = _xor_bytes(raw[_ENC_SK[0] : _ENC_SK[1]], stream[8:72])
    chk = _xor_bytes(raw[_ENC_CHK[0] : _ENC_CHK[1]], stream[72:104])
    digest = hashlib.blake2b(b"Ed" + keynum + sk, digest_size=32).digest()
    if not hmac.compare_digest(digest, chk):
        raise ValueError("wrong password for that key")
    if keynum_hint is not None and keynum_hint != keynum:
        raise ValueError("secret key number does not match the expected public key")
    return keynum, sk[:32]


def _encrypt_box(
    seed: bytes, keynum: bytes, password: str, *, salt: bytes | None = None
) -> bytes:
    """Encrypt into a 158-byte rsign box (tests/tooling only; mirrors decrypt)."""
    if len(seed) != 32 or len(keynum) != 8:
        raise ValueError("seed must be 32 bytes and keynum 8 bytes")
    salt = salt if salt is not None else os.urandom(32)
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    opslimit, memlimit = 1_048_576, 33_554_432
    n, r, p = _scrypt_n_r_p(opslimit, memlimit)
    stream = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=memlimit * 2 + (1 << 20),
        dklen=_ENC_STREAM_LEN,
    )
    sk = seed + ed25519_pubkey(seed)
    chk = hashlib.blake2b(b"Ed" + keynum + sk, digest_size=32).digest()
    return (
        b"Ed"
        + b"Sc"
        + b"B2"
        + salt
        + opslimit.to_bytes(8, "little")
        + memlimit.to_bytes(8, "little")
        + _xor_bytes(keynum, stream[0:8])
        + _xor_bytes(sk, stream[8:72])
        + _xor_bytes(chk, stream[72:104])
    )


def sign_message(
    secret_key_text: str,
    message: bytes,
    *,
    keynum_hint: bytes | None = None,
    password: str | None = None,
) -> str:
    """Sign ``message``; returns the base64 74-byte minisign signature line."""
    keynum, seed = parse_secret_key(
        secret_key_text, keynum_hint=keynum_hint, password=password
    )
    return base64.b64encode(_SIG_ALG + keynum + ed25519_sign(seed, message)).decode("ascii")


def verify_message(pubkey_text: str, message: bytes, signature_b64: str) -> bool:
    """Verify ``message`` against a minisign signature (keynum must match)."""
    try:
        keynum, pubkey = parse_pubkey(pubkey_text)
        sig_keynum, sig = parse_signature(signature_b64)
    except ValueError:
        return False
    if sig_keynum and sig_keynum != keynum:
        return False
    return ed25519_verify(pubkey, message, sig)


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh keypair (tests/tooling only) → ``(pub, secret)`` texts."""
    seed = os.urandom(32)
    keynum = os.urandom(8)
    pubkey = ed25519_pubkey(seed)
    pub = "untrusted comment: minisign public key: test\n" + base64.b64encode(
        _SIG_ALG + keynum + pubkey
    ).decode("ascii")
    sec = "untrusted comment: minisign secret key: test\n" + base64.b64encode(
        _SIG_ALG + keynum + seed + pubkey
    ).decode("ascii")
    return pub, sec
