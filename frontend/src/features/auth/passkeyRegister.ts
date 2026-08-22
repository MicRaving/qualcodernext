/**
 * Passkey registration for the logged-in server user.
 * (Separate module: react-refresh requires component-only exports in
 * component files.)
 */
import { api } from "@/lib/api";
import { b64uToBytes, bytesToB64u } from "@/features/auth/b64u";

/** Register a passkey for the CURRENTLY logged-in user (called from the
 *  server area after boot). Returns true on success. */
export async function registerPasskey(): Promise<boolean> {
  const options = (await api.authPasskeyRegisterBegin()) as unknown as Record<string, unknown>;
  const pub = {
    challenge: b64uToBytes(String(options.challenge)),
    rp: options.rp as PublicKeyCredentialRpEntity,
    user: options.user as PublicKeyCredentialUserEntity,
    pubKeyCredParams: options.pubKeyCredParams as PublicKeyCredentialParameters[],
    timeout: Number(options.timeout ?? 60_000),
    excludeCredentials: ((options.excludeCredentials as Array<Record<string, unknown>>) ?? []).map(
      (d) => ({ id: b64uToBytes(String(d.id)), type: "public-key" as PublicKeyCredentialType }),
    ),
    authenticatorSelection: options.authenticatorSelection as
      | AuthenticatorSelectionCriteria
      | undefined,
  };
  const credential = (await navigator.credentials.create({
    publicKey: pub,
  })) as PublicKeyCredential | null;
  if (!credential) return false;
  const r = credential.response as AuthenticatorAttestationResponse;
  const done = await api.authPasskeyRegisterComplete({
    id: credential.id,
    rawId: bytesToB64u(new Uint8Array(credential.rawId)),
    type: credential.type,
    response: {
      clientDataJSON: bytesToB64u(new Uint8Array(r.clientDataJSON)),
      attestationObject: bytesToB64u(new Uint8Array(r.attestationObject)),
    },
  });
  return Boolean(done.ok);
}
