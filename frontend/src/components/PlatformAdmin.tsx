"use client";

import Link from "next/link";
import {useEffect,useMemo,useState} from "react";
import {useRouter,useSearchParams} from "next/navigation";
import {api} from "@/lib/api";
import {AdminApiError,adminApi} from "@/lib/adminApi";
import type {AccountUser,PlatformAdminSummary,PlatformCustomer,PlatformCustomerDetail} from "@/lib/types";
import {Brand} from "./Brand";
import {LocaleSelect} from "./LocaleSelect";
import {Empty,Loading} from "./State";
import {useI18n} from "@/lib/i18n";

type AccessState="checking"|"login"|"authorized"|"denied";

export function PlatformAdmin(){
  const router=useRouter();
  const params=useSearchParams();
  const {t}=useI18n();
  const customerId=params.get("customer");
  const [access,setAccess]=useState<AccessState>("checking");
  const [summary,setSummary]=useState<PlatformAdminSummary|null>(null);
  const [customers,setCustomers]=useState<PlatformCustomer[]>([]);
  const [detail,setDetail]=useState<PlatformCustomerDetail|null>(null);
  const [loading,setLoading]=useState(true);
  const [search,setSearch]=useState("");
  const [notice,setNotice]=useState("");

  useEffect(()=>{
    let active=true;
    api.restore().then(user=>{
      if(!active)return;
      setAccess(user?.is_platform_admin?"authorized":user?"denied":"login");
      if(!user||!user.is_platform_admin)setLoading(false);
    }).catch(()=>{if(active){setAccess("login");setLoading(false)}});
    return()=>{active=false};
  },[]);

  async function load(){
    if(access!=="authorized")return;
    setLoading(true);setNotice("");
    try{
      if(customerId){setDetail(await adminApi.customer(customerId));return}
      const [s,c]=await Promise.all([adminApi.summary(),adminApi.customers()]);
      setSummary(s);setCustomers(c);setDetail(null);
    }catch(error){
      if(error instanceof AdminApiError&&error.status===401){
        await api.logout().catch(()=>{});
        setAccess("login");
        setSummary(null);setCustomers([]);setDetail(null);
        return;
      }
      if(error instanceof AdminApiError&&error.status===403){
        setAccess("denied");
        setSummary(null);setCustomers([]);setDetail(null);
        return;
      }
      if(customerId){setNotice(t("adminCustomerLoadError"));setDetail(null)}else{setNotice(t("requestFailed"))}
    }finally{setLoading(false)}
  }

  useEffect(()=>{if(access==="authorized")load()},[access,customerId]);
  const filtered=useMemo(()=>customers.filter(c=>`${c.organization_name} ${c.primary_email??""}`.toLowerCase().includes(search.toLowerCase())),[customers,search]);

  async function onAdminAuthenticated(user:AccountUser){
    if(!user.is_platform_admin){
      await api.logout().catch(()=>{});
      setAccess("denied");
      return;
    }
    setAccess("authorized");
    setLoading(true);
  }
  async function useDifferentAccount(){
    await api.logout().catch(()=>{});
    setSummary(null);setCustomers([]);setDetail(null);setNotice("");
    setAccess("login");
  }
  async function rename(customer:PlatformCustomer){
    const value=window.prompt(t("adminRenameCustomer"),customer.organization_name)?.trim();
    if(!value||value===customer.organization_name)return;
    try{await adminApi.updateCustomer(customer.organization_id,{organization_name:value});await load();setNotice(t("saved"))}catch{setNotice(t("requestFailed"))}
  }
  async function toggleApi(customer:PlatformCustomer){
    try{await adminApi.updateCustomer(customer.organization_id,{api_enabled:!customer.api_enabled});await load()}catch{setNotice(t("requestFailed"))}
  }
  async function grantPro(customer:PlatformCustomer){
    if(!window.confirm(t("adminGrantProConfirm")))return;
    try{await adminApi.grantPro(customer.organization_id);await load()}catch{setNotice(t("requestFailed"))}
  }
  async function revokePro(customer:PlatformCustomer){
    if(customer.billing_provider!=="admin")return;
    if(!window.confirm(t("adminRevokeProConfirm")))return;
    try{await adminApi.revokeAdminPro(customer.organization_id);await load()}catch{setNotice(t("requestFailed"))}
  }
  function openCustomer(id:string){router.push(`/admin?customer=${encodeURIComponent(id)}`)}

  if(access==="checking"||(access==="authorized"&&loading))return <AdminFrame><Loading/></AdminFrame>;
  if(access==="login")return <AdminFrame><AdminLogin onAuthenticated={onAdminAuthenticated}/></AdminFrame>;
  if(access==="denied")return <AdminFrame><div className="auth-card"><h1>{t("adminAccessDenied")}</h1><p className="muted">{t("adminAccessDeniedHint")}</p><div className="actions"><Link className="button secondary" href="/app">{t("backToApp")}</Link><button className="button" onClick={useDifferentAccount}>{t("adminUseDifferentAccount")}</button></div></div></AdminFrame>;

  return <div className="page-bg">
    <header className="topbar"><Link href="/app"><Brand compact/></Link><div className="top-actions"><LocaleSelect/><Link className="button secondary small" href="/app">{t("backToApp")}</Link></div></header>
    <main className="container section">
      {customerId?<CustomerDetail detail={detail} notice={notice} onBack={()=>router.push("/admin")} onRename={rename} onToggleApi={toggleApi} onGrantPro={grantPro} onRevokePro={revokePro} onReload={load}/>:<>
        <div className="page-title"><div><h1>{t("platformAdmin")}</h1><p className="muted">{t("platformAdminHint")}</p></div></div>
        {notice&&<div className="notice">{notice}</div>}
        {summary&&<div className="grid-4"><Metric label={t("adminCustomers")} value={summary.customers}/><Metric label={t("adminFreeCustomers")} value={summary.free_customers}/><Metric label={t("adminProCustomers")} value={summary.pro_customers}/><Metric label={t("adminActiveUsers")} value={summary.active_users}/></div>}
        <div className="toolbar" style={{marginTop:20}}><input className="input search" value={search} onChange={e=>setSearch(e.target.value)} placeholder={t("searchPlaceholder")}/><button className="button secondary" onClick={load}>{t("refresh")}</button></div>
        {filtered.length===0?<Empty text={t("adminNoCustomers")}/>:<div className="table-wrap"><table className="table"><thead><tr><th>{t("name")}</th><th>{t("email")}</th><th>{t("adminPlan")}</th><th>{t("participants")}</th><th>{t("collections")}</th><th>{t("lastLogin")}</th><th>{t("actions")}</th></tr></thead><tbody>{filtered.map(c=><tr key={c.organization_id}><td><button className="button ghost small" onClick={()=>openCustomer(c.organization_id)}><strong>{c.organization_name}</strong></button><div className="muted">{c.locale} · {c.currency}</div></td><td>{c.primary_email??"—"}<div className="muted">{c.active_user_count}/{c.user_count} {t("active")}</div></td><td><span className={`status-pill ${c.plan==="pro"?"paid":""}`}>{c.plan.toUpperCase()}</span><div className="muted">{c.billing_provider??"—"}{c.subscription_expires_at?` · ${new Date(c.subscription_expires_at).toLocaleDateString()}`:""}</div></td><td>{c.participants}<div className="muted">{c.participant_lists} {t("participantLists")}</div></td><td>{c.collections}</td><td>{c.last_login_at?new Date(c.last_login_at).toLocaleString():"—"}</td><td><div className="actions"><button className="button secondary small" onClick={()=>openCustomer(c.organization_id)}>{t("view")}</button><button className="button secondary small" onClick={()=>rename(c)}>{t("edit")}</button><button className="button secondary small" onClick={()=>toggleApi(c)}>{c.api_enabled?t("adminDisableApi"):t("adminEnableApi")}</button>{c.plan==="free"?<button className="button small" onClick={()=>grantPro(c)}>{t("adminGrantPro")}</button>:c.billing_provider==="admin"?<button className="button ghost small danger-text" onClick={()=>revokePro(c)}>{t("adminRevokePro")}</button>:null}</div></td></tr>)}</tbody></table></div>}
      </>}
    </main>
  </div>;
}

function AdminFrame({children}:{children:React.ReactNode}){
  return <div className="page-bg"><header className="topbar"><Link href="/"><Brand compact/></Link><div className="top-actions"><LocaleSelect/><Link className="button secondary small" href="/">←</Link></div></header><main className="auth-wrap">{children}</main></div>;
}

function AdminLogin({onAuthenticated}:{onAuthenticated:(user:AccountUser)=>void}){
  const {t}=useI18n();
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [info,setInfo]=useState("");
  async function submit(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError("");setInfo("");
    try{onAuthenticated(await adminApi.login(email.trim(),password))}catch{setError(t("adminInvalidCredentials"))}finally{setBusy(false)}
  }
  async function forgot(){
    if(!email.trim())return;
    setBusy(true);setError("");setInfo("");
    try{await api.forgotPassword(email.trim());setInfo(t("resetLinkSent"))}catch{setError(t("requestFailed"))}finally{setBusy(false)}
  }
  return <div className="auth-card">
    <div className="brand"><Brand compact/></div>
    <h1>{t("adminLoginTitle")}</h1>
    <p className="muted">{t("adminLoginHint")}</p>
    {error&&<div className="notice error">{error}</div>}{info&&<div className="notice success">{info}</div>}
    <form className="form" onSubmit={submit}>
      <div className="field"><label>{t("email")}</label><input className="input" type="email" value={email} onChange={e=>setEmail(e.target.value)} autoComplete="username" required/></div>
      <div className="field"><label>{t("password")}</label><input className="input" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/></div>
      <button className="button" disabled={busy}>{t("login")}</button>
    </form>
    <button className="button ghost" onClick={forgot} disabled={busy||!email.trim()}>{t("forgotPassword")}</button>
    <p className="muted">{t("adminLoginSecurityHint")}</p>
  </div>;
}

function CustomerDetail({detail,notice,onBack,onRename,onToggleApi,onGrantPro,onRevokePro,onReload}:{detail:PlatformCustomerDetail|null;notice:string;onBack:()=>void;onRename:(c:PlatformCustomer)=>void;onToggleApi:(c:PlatformCustomer)=>void;onGrantPro:(c:PlatformCustomer)=>void;onRevokePro:(c:PlatformCustomer)=>void;onReload:()=>void}){
  const {t,locale}=useI18n();
  if(!detail)return <><button className="button secondary small" onClick={onBack}>{t("adminBackToCustomers")}</button>{notice&&<div className="notice error">{notice}</div>}</>;
  const date=(value?:string|null)=>value?new Date(value).toLocaleString(locale):"—";
  return <>
    <div className="page-title"><div><button className="button ghost small" onClick={onBack}>{t("adminBackToCustomers")}</button><h1>{detail.organization_name}</h1><p className="muted">{detail.primary_email??"—"} · {t("adminCustomerSince")} {new Date(detail.created_at).toLocaleDateString(locale)}</p></div><div className="actions"><button className="button secondary" onClick={()=>onRename(detail)}>{t("edit")}</button><button className="button secondary" onClick={onReload}>{t("refresh")}</button></div></div>
    {notice&&<div className="notice">{notice}</div>}
    <div className="grid-4"><Metric label={t("adminPlan")} value={detail.plan.toUpperCase()}/><Metric label={t("users")} value={detail.user_count}/><Metric label={t("participants")} value={detail.participants}/><Metric label={t("collections")} value={detail.collections}/></div>
    <section className="card" style={{marginTop:20}}><h3>{t("adminCustomerOverview")}</h3><div className="grid-4"><Info label={t("language")} value={detail.locale}/><Info label={t("currency")} value={detail.currency}/><Info label={t("adminApiStatus")} value={detail.api_enabled?t("active"):t("statusDisabled")}/><Info label={t("lastLogin")} value={date(detail.last_login_at)}/></div><div className="actions" style={{marginTop:16}}><button className="button secondary" onClick={()=>onToggleApi(detail)}>{detail.api_enabled?t("adminDisableApi"):t("adminEnableApi")}</button>{detail.plan==="free"?<button className="button" onClick={()=>onGrantPro(detail)}>{t("adminGrantPro")}</button>:detail.billing_provider==="admin"?<button className="button ghost danger-text" onClick={()=>onRevokePro(detail)}>{t("adminRevokePro")}</button>:null}</div></section>
    <section className="card" style={{marginTop:20}}><h3>{t("adminBilling")}</h3><div className="grid-4"><Info label={t("adminBillingProvider")} value={detail.billing_provider??"—"}/><Info label={t("status")} value={detail.subscription_status??"—"}/><Info label={t("adminExpiresAt")} value={date(detail.subscription_expires_at)}/><Info label={t("adminSubscriptionCount")} value={String(detail.subscriptions.length)}/></div>{detail.subscriptions.length===0?<Empty text={t("adminNoSubscriptions")}/>:<div className="table-wrap" style={{marginTop:16}}><table className="table"><thead><tr><th>{t("adminBillingProvider")}</th><th>{t("adminProduct")}</th><th>{t("status")}</th><th>{t("adminPurchasedAt")}</th><th>{t("adminExpiresAt")}</th><th>{t("adminAutoRenew")}</th><th>{t("adminLastVerified")}</th></tr></thead><tbody>{detail.subscriptions.map(s=><tr key={s.id}><td>{s.provider}<div className="muted">{s.environment??"—"}</div></td><td>{s.product_id}</td><td><span className={`status-pill ${s.status==="active"||s.status==="grace_period"?"paid":""}`}>{s.status}</span></td><td>{date(s.purchased_at||s.created_at)}</td><td>{date(s.expires_at)}</td><td>{s.auto_renew===null||s.auto_renew===undefined?"—":s.auto_renew?t("yes"):t("no")}</td><td>{date(s.last_verified_at)}</td></tr>)}</tbody></table></div>}</section>
    <section className="card" style={{marginTop:20}}><h3>{t("adminUsers")}</h3>{detail.users.length===0?<Empty/>:<div className="table-wrap"><table className="table"><thead><tr><th>{t("name")}</th><th>{t("email")}</th><th>{t("status")}</th><th>{t("adminEmailVerified")}</th><th>{t("adminCreatedAt")}</th><th>{t("lastLogin")}</th></tr></thead><tbody>{detail.users.map(u=><tr key={u.id}><td>{u.display_name}</td><td>{u.email}</td><td>{u.is_active?t("active"):t("statusDisabled")}</td><td>{u.email_verified?t("yes"):t("no")}</td><td>{date(u.created_at)}</td><td>{date(u.last_login_at)}</td></tr>)}</tbody></table></div>}</section>
  </>;
}

function Metric({label,value}:{label:string;value:number|string}){return <div className="metric"><div className="muted">{label}</div><div className="value">{value}</div></div>}
function Info({label,value}:{label:string;value:string}){return <div><div className="muted">{label}</div><strong>{value}</strong></div>}
