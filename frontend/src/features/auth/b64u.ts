/** base64url <-> bytes for WebAuthn ceremonies. */

export function b64uToBytes(value: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export function bytesToB64u(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
