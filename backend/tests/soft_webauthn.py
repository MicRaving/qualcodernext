"""Software WebAuthn authenticator for tests.

Fabricates REAL registration responses ("none" attestation, ES256 key)
and assertion signatures over authData || sha256(clientDataJSON) using
cbor2 + cryptography — the same wire format a browser produces for a
non-roaming authenticator. Lets the passkey flow be tested end-to-end
without a browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str):
        self.rp_id = rp_id
        self.origin = origin
        self.credential_id = os.urandom(32)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.sign_count = 0

    # ── COSE key ────────────────────────────────────────────────────────

    def _cose_key(self) -> dict:
        nums = self.key.public_key().public_numbers()
        return {
            1: 2,  # kty: EC2
            3: -7,  # alg: ES256
            -1: 1,  # crv: P-256
            -2: nums.x.to_bytes(32, "big"),
            -3: nums.y.to_bytes(32, "big"),
        }

    def _auth_data(self, attested_credential: bool) -> bytes:
        self.sign_count += 1
        flags = 0x01 | (0x40 if attested_credential else 0x00)  # UP (+AT)
        data = hashlib.sha256(self.rp_id.encode("utf-8")).digest()
        data += bytes([flags]) + self.sign_count.to_bytes(4, "big")
        if attested_credential:
            data += b"\x00" * 16  # AAGUID
            data += len(self.credential_id).to_bytes(2, "big") + self.credential_id
            data += cbor2.dumps(self._cose_key())
        return data

    def _client_data(self, type_: str, challenge_b64u: str) -> bytes:
        payload = {
            "type": type_,
            "challenge": challenge_b64u,
            "origin": self.origin,
            "crossOrigin": False,
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _credential_json(response_obj: dict) -> str:
        raw_id = response_obj["rawId"]
        if isinstance(raw_id, bytes):
            raw_id = _b64u(raw_id)
        inner = dict(response_obj)
        if isinstance(inner.get("rawId"), bytes):
            inner["rawId"] = _b64u(inner["rawId"])
        return json.dumps(
            {
                "id": raw_id,
                "rawId": raw_id,
                "type": "public-key",
                "response": inner,
            },
            separators=(",", ":"),
        )

    # ── public API ──────────────────────────────────────────────────────

    def register(self, options: dict) -> str:
        """Build an attestation response from registration options JSON."""
        client_data = self._client_data("webauthn.create", options["challenge"])
        attestation_object = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": self._auth_data(True)}
        )
        return self._credential_json(
            {
                "clientDataJSON": _b64u(client_data),
                "attestationObject": _b64u(attestation_object),
                "rawId": self.credential_id,
            }
        )

    def authenticate(self, options: dict) -> str:
        """Sign the challenge from authentication options JSON."""
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._auth_data(False)
        # ES256: sign authData || SHA256(clientDataJSON); ECDSA(SHA256())
        # performs the digest — do NOT pre-hash.
        der_sig = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        return self._credential_json(
            {
                "clientDataJSON": _b64u(client_data),
                "authenticatorData": _b64u(auth_data),
                "signature": _b64u(der_sig),
                "userHandle": None,
                "rawId": self.credential_id,
            }
        )
