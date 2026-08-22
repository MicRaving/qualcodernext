"""WebAuthn passkeys — registration + assertion (SERVER_PLAN.md §6.4).

Challenges live in the metadata DB (not memory) so a server restart does
not lose in-flight registrations; they are SINGLE USE (consumed on read).
Requires ``QC_RP_ID`` (and optionally ``QC_RP_ORIGIN``, defaulting to
``https://<QC_RP_ID>``).
"""
from __future__ import annotations

import json

import webauthn
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    generate_user_handle,
    options_to_json,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from qualcoder_api.core.server_config import load_server_config
from qualcoder_api.persistence import metadata_db

CHALLENGE_TTL_SECS = 300


def _rp() -> tuple[str, str]:
    cfg = load_server_config()
    if not cfg.rp_id:
        raise RuntimeError("passkeys require QC_RP_ID to be set")
    return cfg.rp_id, (cfg.rp_origin or f"https://{cfg.rp_id}")


def _client_data(response_json: str) -> dict:
    payload = json.loads(response_json)
    return json.loads(
        base64url_to_bytes(payload["response"]["clientDataJSON"]).decode("utf-8")
    )


async def _consume_client_challenge(response_json: str, kind: str) -> bytes:
    """Extract + consume the single-use challenge from a response."""
    from webauthn.helpers.exceptions import (
        InvalidAuthenticationResponse,
        InvalidRegistrationResponse,
    )

    client_data = _client_data(response_json)
    row = await metadata_db.take_challenge(client_data["challenge"], kind)
    if row is None:
        exc = (
            InvalidRegistrationResponse
            if kind == "register"
            else InvalidAuthenticationResponse
        )
        raise exc(f"unknown or expired {kind} challenge")
    return base64url_to_bytes(client_data["challenge"])


async def begin_registration(user: dict) -> str:
    """PublicKeyCredentialCreationOptions JSON for a logged-in user."""
    rp_id, _ = _rp()
    allow = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["credential_id"]))
        for row in await metadata_db.list_passkeys(user["id"])
    ]
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name="QualCoder",
        user_id=generate_user_handle(),
        user_name=user["username"],
        user_display_name=user.get("display_name") or user["username"],
        exclude_credentials=allow,
    )
    await metadata_db.put_challenge(
        bytes_to_base64url(options.challenge), "register", int(user["id"]), CHALLENGE_TTL_SECS
    )
    return options_to_json(options)


async def complete_registration(user: dict, response_json: str) -> dict:
    """Verify an attestation and store the credential; returns a summary."""
    rp_id, origin = _rp()
    expected_challenge = await _consume_client_challenge(response_json, "register")
    credential = parse_registration_credential_json(response_json)
    verification = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_origin=origin,
        expected_rp_id=rp_id,
        require_user_verification=False,
    )
    credential_id_b64 = bytes_to_base64url(verification.credential_id)
    await metadata_db.add_passkey(
        user_id=int(user["id"]),
        credential_id=credential_id_b64,
        public_key=verification.credential_public_key.hex(),
        sign_count=int(verification.sign_count),
        transports="",
        name="",
    )
    return {"credential_id": credential_id_b64, "sign_count": int(verification.sign_count)}


async def begin_login(username: str | None) -> str:
    """Authentication options JSON. When the user exists their registered
    credentials narrow the request; unknown users get an empty allow list
    (their assertion simply will not verify)."""
    rp_id, _ = _rp()
    user = await metadata_db.get_user_by_username(username) if username else None
    allow = []
    if user is not None:
        allow = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["credential_id"]))
            for row in await metadata_db.list_passkeys(user["id"])
        ]
    options = webauthn.generate_authentication_options(rp_id=rp_id, allow_credentials=allow)
    await metadata_db.put_challenge(
        bytes_to_base64url(options.challenge),
        "login",
        int(user["id"]) if user else None,
        CHALLENGE_TTL_SECS,
    )
    return options_to_json(options)


async def complete_login(username: str, response_json: str) -> dict:
    """Verify an assertion; returns the owning user row on success."""
    rp_id, origin = _rp()
    expected_challenge = await _consume_client_challenge(response_json, "login")
    credential = parse_authentication_credential_json(response_json)
    passkey = await metadata_db.get_passkey_by_credential_id(bytes_to_base64url(credential.raw_id))
    user = await metadata_db.get_user_by_username(username) if username else None
    if passkey is None or user is None or passkey["user_id"] != user["id"]:
        raise InvalidAuthenticationResponse("unknown credential for this user")
    verification = webauthn.verify_authentication_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=bytes.fromhex(passkey["public_key"]),
        credential_current_sign_count=int(passkey["sign_count"]),
        require_user_verification=False,
    )
    await metadata_db.update_passkey_sign_count(
        int(passkey["id"]), int(verification.new_sign_count)
    )
    fresh = await metadata_db.get_user_by_id(int(user["id"]))
    if fresh is None:
        raise InvalidAuthenticationResponse("user vanished")
    return fresh
