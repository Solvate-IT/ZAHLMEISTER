"use client";

import {useState} from "react";
import {api, ApiError} from "@/lib/api";
import {useI18n} from "@/lib/i18n";
import {PasswordInput} from "./PasswordInput";

function validPassword(value:string):boolean{return value.length>=6&&/\d/.test(value)&&/[A-Za-zÀ-ÖØ-öø-ÿĀ-žΑ-ωА-я]/.test(value)}

export function AuthPanel({registerMode,onAuthenticated}:{registerMode:boolean;onAuthenticated:()=>void;onBack?:()=>void}){
  const {t,locale}=useI18n(); const [register,setRegister]=useState(registerMode); const [forgotMode,setForgotMode]=useState(false); const [busy,setBusy]=useState(false); const [error,setError]=useState(""); const [info,setInfo]=useState("");
  const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [name,setName]=useState("");
  async function submit(e:React.FormEvent){e.preventDefault();setError("");setInfo("");if(register&&!forgotMode&&!validPassword(password)){setError(t("passwordRequirements"));return}setBusy(true);try{if(forgotMode){await api.forgotPassword(email.trim());setInfo(t("resetLinkSent"));return}if(register){await api.register({email,password,display_name:name,locale,currency:"EUR"})}else{await api.login(email,password)}onAuthenticated()}catch(e){setError(e instanceof ApiError && e.status===401?t("invalidCredentials"):register?t("registrationFailed"):t("authenticationFailed"))}finally{setBusy(false)}}
  function switchMode(nextRegister:boolean){setRegister(nextRegister);setForgotMode(false);setError("");setInfo("");setPassword("")}
  return <div className="auth-card">
    <div className="brand"><img src="/brand/logo.png" width="52" height="52" alt=""/><strong>{t("appName")}</strong></div>
    <h1>{forgotMode?t("forgotPassword"):register?t("register"):t("login")}</h1>{!forgotMode&&<p className="muted">{t("accountSubtitle")}</p>}
    {error&&<div className="notice error">{error}</div>}{info&&<div className="notice success">{info}</div>}
    <form className="form" onSubmit={submit}>
      {register&&!forgotMode&&<div className="field"><label>{t("displayName")}</label><input className="input" value={name} onChange={e=>setName(e.target.value)} autoComplete="name"/></div>}
      <div className="field"><label>{t("email")}</label><input className="input" type="email" value={email} onChange={e=>setEmail(e.target.value)} autoComplete="email" required/></div>
      {!forgotMode&&<div className="field"><label>{t("password")}</label><PasswordInput value={password} onChange={e=>setPassword(e.target.value)} autoComplete={register?"new-password":"current-password"} minLength={register?6:1} required/>{register&&<span className="muted field-hint">{t("passwordRequirements")}</span>}</div>}
      <button className="button" disabled={busy}>{forgotMode?t("continueLabel"):register?t("register"):t("login")}</button>
    </form>
    {forgotMode?<div className="auth-secondary-links"><button className="button ghost" onClick={()=>{setForgotMode(false);setError("");setInfo("")}}>{t("login")}</button></div>:<div className="auth-secondary-links">{!register?<button className="button ghost" onClick={()=>{setForgotMode(true);setError("");setInfo("");setPassword("")}} disabled={busy}>{t("forgotPassword")}</button>:<span/>}<button className="button ghost" onClick={()=>switchMode(!register)}>{register?t("haveAccount"):t("noAccount")}</button></div>}
  </div>
}
