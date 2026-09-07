"use client";

import Link from "next/link";
import {useEffect,useMemo,useState} from "react";
import {useRouter} from "next/navigation";
import {adminApi} from "@/lib/adminApi";
import type {PlatformAdminSummary,PlatformCustomer} from "@/lib/types";
import {Brand} from "./Brand";
import {LocaleSelect} from "./LocaleSelect";
import {Empty,Loading} from "./State";
import {useI18n} from "@/lib/i18n";

export function PlatformAdmin(){
  const router=useRouter();
  const {t}=useI18n();
  const [summary,setSummary]=useState<PlatformAdminSummary|null>(null);
  const [customers,setCustomers]=useState<PlatformCustomer[]>([]);
  const [loading,setLoading]=useState(true);
  const [search,setSearch]=useState("");
  const [notice,setNotice]=useState("");

  async function load(){
    setLoading(true);setNotice("");
    try{
      const [s,c]=await Promise.all([adminApi.summary(),adminApi.customers()]);
      setSummary(s);setCustomers(c);
    }catch{
      router.replace("/app");
    }finally{setLoading(false)}
  }

  useEffect(()=>{load()},[]);
  const filtered=useMemo(()=>customers.filter(c=>`${c.organization_name} ${c.primary_email??""}`.toLowerCase().includes(search.toLowerCase())),[customers,search]);

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

  if(loading)return <div className="auth-wrap"><Loading/></div>;
  return <div className="page-bg">
    <header className="topbar"><Link href="/app"><Brand compact/></Link><div className="top-actions"><LocaleSelect/><Link className="button secondary small" href="/app">{t("backToApp")}</Link></div></header>
    <main className="container section">
      <div className="page-title"><div><h1>{t("platformAdmin")}</h1><p className="muted">{t("platformAdminHint")}</p></div></div>
      {notice&&<div className="notice">{notice}</div>}
      {summary&&<div className="grid-4"><Metric label={t("adminCustomers")} value={summary.customers}/><Metric label={t("adminFreeCustomers")} value={summary.free_customers}/><Metric label={t("adminProCustomers")} value={summary.pro_customers}/><Metric label={t("adminActiveUsers")} value={summary.active_users}/></div>}
      <div className="toolbar" style={{marginTop:20}}><input className="input search" value={search} onChange={e=>setSearch(e.target.value)} placeholder={t("searchPlaceholder")}/><button className="button secondary" onClick={load}>{t("refresh")}</button></div>
      {filtered.length===0?<Empty text={t("adminNoCustomers")}/>:<div className="table-wrap"><table className="table"><thead><tr><th>{t("name")}</th><th>{t("email")}</th><th>{t("adminPlan")}</th><th>{t("participants")}</th><th>{t("collections")}</th><th>{t("lastLogin")}</th><th>{t("actions")}</th></tr></thead><tbody>{filtered.map(c=><tr key={c.organization_id}><td><strong>{c.organization_name}</strong><div className="muted">{c.locale} · {c.currency}</div></td><td>{c.primary_email??"—"}<div className="muted">{c.active_user_count}/{c.user_count} {t("active")}</div></td><td><span className={`status-pill ${c.plan==="pro"?"paid":""}`}>{c.plan.toUpperCase()}</span><div className="muted">{c.billing_provider??"—"}{c.subscription_expires_at?` · ${new Date(c.subscription_expires_at).toLocaleDateString()}`:""}</div></td><td>{c.participants}<div className="muted">{c.participant_lists} {t("participantLists")}</div></td><td>{c.collections}</td><td>{c.last_login_at?new Date(c.last_login_at).toLocaleString():"—"}</td><td><div className="actions"><button className="button secondary small" onClick={()=>rename(c)}>{t("edit")}</button><button className="button secondary small" onClick={()=>toggleApi(c)}>{c.api_enabled?t("adminDisableApi"):t("adminEnableApi")}</button>{c.plan==="free"?<button className="button small" onClick={()=>grantPro(c)}>{t("adminGrantPro")}</button>:c.billing_provider==="admin"?<button className="button ghost small danger-text" onClick={()=>revokePro(c)}>{t("adminRevokePro")}</button>:null}</div></td></tr>)}</tbody></table></div>}
    </main>
  </div>;
}

function Metric({label,value}:{label:string;value:number}){return <div className="metric"><div className="muted">{label}</div><div className="value">{value}</div></div>}
