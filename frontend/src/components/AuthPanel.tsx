"use client";

import {useState} from "react";
import {api, ApiError} from "@/lib/api";
import {useI18n} from "@/lib/i18n";

export function AuthPanel({registerMode,onAuthenticated,onBack}:{registerMode:boolean;onAuthenticated:()=>void;onBack?:()=>void}){
  const {t,locale}=useI18n(); const [register,setRegister]=useState(registerMode); const [forgotMode,setForgotMode]=useState(false); const [busy,setBusy]=useState(false); const [error,setError]=useState(""); const [info,setInfo]=useState("");
  const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [name,setName]=useState("");
  async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError("");setInfo("");try{if(forgotMode){await api.forgotPassword(email.trim());setInfo(t("resetLinkSent"));return}if(register){await api.register({email,password,display_name:name,locale,currency:"EUR"})}else{await api.login(email,password)}onAuthenticated()}catch(e){setError(e instanceof ApiError && e.status===401?t("invalidCredentials"):register?t("registrationFailed"):t("authenticationFailed"))}finally{setBusy(false)}}
  function switchMode(nextRegister:boolean){setRegister(nextRegister);setForgotMode(false);setError("");setInfo("");setPassword("")}
  return <div className="auth-card">
    <div className="brand"><img src="/brand/logo.png" width="52" height="52" alt=""/><strong>{t("appName")}</strong></div>
    <h1>{forgotMode?t("forgotPassword"):register?t("register"):t("login")}</h1><p className="muted">{forgotMode?t("resetLinkSent").replace(/^Falls das Konto existiert, /,""):t("accountSubtitle")}</p>
    {error&&<div className="notice error">{error}</div>}{info&&<div className="notice success">{info}</div>}
    <form className="form" onSubmit={submit}>
      {register&&!forgotMode&&<div className="field"><label>{t("displayName")}</label><input className="input" value={name} onChange={e=>setName(e.target.value)} autoComplete="name"/></div>}
      <div className="field"><label>{t("email")}</label><input className="input" type="email" value={email} onChange={e=>setEmail(e.target.value)} autoComplete="email" required/></div>
      {!forgotMode&&<div className="field"><label>{t("password")}</label><input className="input" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete={register?"new-password":"current-password"} minLength={register?8:1} required/></div>}
      <button className="button" disabled={busy}>{forgotMode?t("continueLabel"):register?t("register"):t("login")}</button>
    </form>
    {!register&&!forgotMode&&<button className="button ghost" onClick={()=>{setForgotMode(true);setError("");setInfo("");setPassword("")}} disabled={busy}>{t("forgotPassword")}</button>}
    {forgotMode?<button className="button secondary" onClick={()=>{setForgotMode(false);setError("");setInfo("")}}>{t("login")}</button>:<button className="button secondary" onClick={()=>switchMode(!register)}>{register?t("haveAccount"):t("noAccount")}</button>}
    {onBack&&<button className="button ghost" onClick={onBack}>{t("backToWebsite")}</button>}
  </div>
}
