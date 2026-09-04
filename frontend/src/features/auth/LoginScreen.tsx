/**
 * LoginScreen — server-mode auth gate (SERVER_PLAN.md §6.7).
 *
 * Password login first-class; passkey sign-in via native
 * navigator.credentials.get() against /auth/passkey/login/*. After a
 * successful login the token is stored and the normal app boots.
 */
import { useState } from "react";
import { KeyRound, LoaderCircle, LogIn } from "lucide-react";
import { Button, ErrorBanner, Input } from "@/components/ui/orchestrator";
import { api } from "@/lib/api";
import { b64uToBytes, bytesToB64u } from "@/features/auth/b64u";
import { errorMessage } from "@/lib/utils";
import { setToken } from "@/lib/session";
import { useI18n } from "@/lib/i18n";

interface LoginSuccess {
  token: string;
}

function parseLoginSuccess(res: unknown): LoginSuccess {
  if (res && typeof res === "object" && "token" in res) {
    const token = (res as { token?: unknown }).token;
    if (typeof token === "string" && token.length > 0 && token.length <= 8192) {
      return { token };
    }
  }
  throw new Error("Invalid login response");
}

export function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function finishLogin(result: LoginSuccess) {
    setToken(result.token);
    onAuthed();
  }

  async function loginWithPassword() {
    if (!username || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.authLogin({ username, password });
      await finishLogin(parseLoginSuccess(res));
    } catch (e) {
      setError(errorMessage(e, t("auth.loginError")));
    } finally {
      setBusy(false);
    }
  }

  async function loginWithPasskey() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const begin = (await api.authPasskeyLoginBegin(username)) as { options?: unknown };
      const options = (begin?.options ?? {}) as Record<string, unknown>;
      if (!options || typeof options.challenge !== "string" || !options.challenge) {
        throw new Error("Invalid passkey options");
      }
      const rp = options.rp as { id?: unknown } | undefined;
      const authSel = options.authenticatorSelection as { userVerification?: unknown } | undefined;
      const allowList = Array.isArray(options.allowCredentials)
        ? (options.allowCredentials as Array<Record<string, unknown>>)
        : [];
      const pub = {
        challenge: b64uToBytes(String(options.challenge)),
        rpId: typeof rp?.id === "string" ? rp.id : undefined,
        timeout: Number(
          typeof options.timeout === "number" || typeof options.timeout === "string"
            ? options.timeout
            : 60_000,
        ),
        userVerification: (typeof authSel?.userVerification === "string"
          ? authSel.userVerification
          : "preferred") as UserVerificationRequirement,
        allowCredentials: allowList.map((d) => ({
          id: b64uToBytes(String(d.id)),
          type: "public-key" as PublicKeyCredentialType,
        })),
      };
      const assertion = (await navigator.credentials.get({ publicKey: pub })) as PublicKeyCredential | null;
      if (!assertion) throw new Error(t("auth.passkeyCancelled"));
      const r = assertion.response as AuthenticatorAssertionResponse;
      const done = await api.authPasskeyLoginComplete({
        username,
        response: {
          id: assertion.id,
          rawId: bytesToB64u(new Uint8Array(assertion.rawId)),
          type: assertion.type,
          response: {
            clientDataJSON: bytesToB64u(new Uint8Array(r.clientDataJSON)),
            authenticatorData: bytesToB64u(new Uint8Array(r.authenticatorData)),
            signature: bytesToB64u(new Uint8Array(r.signature)),
            userHandle: r.userHandle ? bytesToB64u(new Uint8Array(r.userHandle)) : null,
          },
        },
      });
      await finishLogin(parseLoginSuccess(done));
    } catch (e) {
      setError(errorMessage(e, t("auth.loginError")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-bg">
      <form
        className="w-80 max-w-[90vw]"
        onSubmit={(e) => {
          e.preventDefault();
          void loginWithPassword();
        }}
      >
        <h1 className="text-center text-sm font-semibold text-text-primary">
          {t("app.title")}
        </h1>
        <p className="mt-1 text-center text-xs text-text-secondary">{t("auth.signInPrompt")}</p>
        <div className="mt-4 space-y-2">
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t("auth.username")}
            aria-label={t("auth.username")}
            autoComplete="username"
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("auth.password")}
            aria-label={t("auth.password")}
            autoComplete="current-password"
          />
        </div>
        {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}
        <div className="mt-3 flex flex-col gap-2">
          <Button type="submit" variant="primary" disabled={busy || !username || !password}>
            {busy ? <LoaderCircle size={14} className="animate-spin" aria-hidden /> : <LogIn size={14} aria-hidden />}
            {t("auth.signIn")}
          </Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={() => void loginWithPasskey()}>
            <KeyRound size={14} aria-hidden />
            {t("auth.passkeySignIn")}
          </Button>
        </div>
      </form>
    </div>
  );
}
