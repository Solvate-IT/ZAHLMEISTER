"use client";

import {useCallback, useEffect, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {api} from "@/lib/api";
import {useI18n} from "@/lib/i18n";
import {Brand} from "./Brand";
import {PasswordInput} from "./PasswordInput";

function validPassword(value:string):boolean{return value.length>=6&&/\d/.test(value)&&/[A-Za-zÀ-ÖØ-öø-ÿĀ-žΑ-ωА-я]/.test(value)}

export function AccountActionPage() {
  const {t} = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const action = params.get("action") ?? "";
  const token = params.get("token") ?? "";
  const verifying = action === "verify-email";
  const resetting = action === "reset-password";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const verify = useCallback(async () => {
    if (!token || !verifying) return;
    setBusy(true); setError("");
    try { await api.verifyEmail(token); setSuccess(true); }
    catch { setError(t("invalidLink")); }
    finally { setBusy(false); }
  }, [token, verifying, t]);

  useEffect(() => { if (verifying) void verify(); }, [verifying, verify]);

  async function reset(event: React.FormEvent) {
    event.preventDefault();
    if (!validPassword(password)) { setError(t("passwordRequirements")); return; }
    if (password !== confirm) { setError(t("passwordsDoNotMatch")); return; }
    setBusy(true); setError("");
    try { await api.resetPassword(token, password); setSuccess(true); }
    catch { setError(t("invalidLink")); }
    finally { setBusy(false); }
  }

  const validAction = verifying || resetting;
  return <div className="page-bg"><div className="auth-wrap"><div className="auth-card"><Brand/>
    {!validAction || !token ? <div className="notice error">{t("invalidLink")}</div> : success ? <div className="stack"><div className="notice success">{verifying ? t("verificationSuccess") : t("passwordResetSuccess")}</div><button className="button" onClick={() => router.replace("/")}>{t("done")}</button></div> : verifying ? <div className="stack"><h1 className="auth-title">{t("verifyEmail")}</h1>{busy && <div className="state"><span className="spinner"/>{t("loading")}</div>}{error && <><div className="notice error">{error}</div><button className="button secondary" onClick={() => void verify()} disabled={busy}>{t("retry")}</button></>}</div> : <form className="form" onSubmit={reset}><h1 className="auth-title">{t("resetPassword")}</h1><div className="field"><label htmlFor="new-password">{t("newPassword")}</label><PasswordInput id="new-password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} required minLength={6}/><span className="muted field-hint">{t("passwordRequirements")}</span></div><div className="field"><label htmlFor="confirm-password">{t("confirmPassword")}</label><PasswordInput id="confirm-password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} required minLength={6}/></div>{error && <div className="notice error">{error}</div>}<button className="button" disabled={busy}>{busy ? t("loading") : t("resetPassword")}</button></form>}
  </div></div></div>;
}
