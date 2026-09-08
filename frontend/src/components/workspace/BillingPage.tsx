"use client";

import {useEffect,useState} from "react";
import {useRouter,useSearchParams} from "next/navigation";
import {api} from "@/lib/api";
import type {BillingEntitlement,MollieBillingConfig} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {isNativeApp} from "@/lib/native";
import {Modal} from "../Modal";
import {Loading} from "../State";

export function BillingPage(){
  const {t,locale}=useI18n();
  const router=useRouter();
  const params=useSearchParams();
  const billingResult=params.get("billing");
  const [entitlement,setEntitlement]=useState<BillingEntitlement|null>(null);
  const [config,setConfig]=useState<MollieBillingConfig|null>(null);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const [native,setNative]=useState<boolean|null>(null);
  const [cancelOpen,setCancelOpen]=useState(false);

  async function load(){setLoading(true);setError("");try{const [e,c]=await Promise.all([api.billingEntitlement(),api.mollieBillingConfig()]);setEntitlement(e);setConfig(c)}catch{setError(t("billingError"))}finally{setLoading(false)}}
  function clearBillingResult(){const url=new URL(window.location.href);url.searchParams.delete("billing");router.replace(`${url.pathname}?${url.searchParams.toString()}`)}

  useEffect(()=>{setNative(isNativeApp())},[]);
  useEffect(()=>{
    if(billingResult==="return"){
      setLoading(true);setError("");
      api.mollieBillingSync().then(async next=>{setEntitlement(next);setConfig(await api.mollieBillingConfig());setNotice(next.active?t("billingActivated"):t("billingReturnProcessing"))}).catch(()=>setError(t("billingError"))).finally(()=>{setLoading(false);clearBillingResult()});
      return;
    }
    if(billingResult==="cancelled")setNotice(t("billingCheckoutCancelled"));
    load().finally(()=>{if(billingResult==="cancelled")clearBillingResult()});
  },[billingResult]);

  async function refresh(){if(!config?.available||native){await load();return}setBusy(true);setError("");try{const [next,nextConfig]=await Promise.all([api.mollieBillingSync(),api.mollieBillingConfig()]);setEntitlement(next);setConfig(nextConfig);setNotice(next.active?t("billingActivated"):next.status==="pending"?t("billingReturnProcessing"):"")}catch{setError(t("billingError"))}finally{setBusy(false)}}
  async function startCheckout(){setBusy(true);setError("");setNotice(t("billingOpeningCheckout"));try{const checkout=await api.mollieBillingCheckout();window.location.assign(checkout.checkout_url)}catch{setNotice("");setError(t("billingError"));setBusy(false)}}
  async function cancelRenewal(){setBusy(true);setError("");try{const next=await api.mollieBillingCancel();setEntitlement(next);setCancelOpen(false);setNotice(next.expires_at?t("billingCancelledNotice",{date:formatDate(next.expires_at,locale)}):t("billingStatusCancelled"))}catch{setError(t("billingError"))}finally{setBusy(false)}}

  if(loading||native===null||!entitlement||!config)return <Loading/>;
  const active=entitlement.active;
  const pending=entitlement.provider==="mollie"&&entitlement.status==="pending";
  const price=config.amount?new Intl.NumberFormat(locale,{style:"currency",currency:config.currency}).format(Number(config.amount)):"";
  const provider=providerLabel(entitlement.provider,t);
  const status=statusLabel(entitlement.status,t);

  return <>
    <div className="page-title"><div><h1>{t("billingTitle")}</h1><div className="muted">{t("billingSubtitle")}</div></div><button className="button secondary" onClick={refresh} disabled={busy}>{t("billingRefresh")}</button></div>
    {error&&<div className="notice error">{error}</div>}{notice&&<div className="notice success">{notice}</div>}
    <div className="split">
      <section className="card"><div className="muted">{t("billingCurrentPlan")}</div><div className="payment-amount">{active?t("billingPro"):t("billingFree")}</div><p className="muted">{active?t("billingProHint"):t("billingFreeHint")}</p>{!active&&!pending&&<div className="notice">{t("billingFreeRegistration")}</div>}{(active||pending)&&<div className="stack">{provider&&<div className="row between"><span className="muted">{t("billingProvider")}</span><strong>{provider}</strong></div>}{status&&<div className="row between"><span className="muted">{t("billingStatus")}</span><span className={`status-pill ${entitlement.status??""}`}>{status}</span></div>}{active&&entitlement.auto_renew!==null&&<div className="row between"><span className="muted">{t("billingRenews")}</span><strong>{entitlement.auto_renew?t("billingYes"):t("billingNo")}</strong></div>}{active&&entitlement.expires_at&&<div className="notice">{t("billingEndsAt",{date:formatDate(entitlement.expires_at,locale)})}</div>}</div>}</section>
      <section className="card">
        {native?<><h3>{t("billingPro")}</h3><p className="muted">{t("billingNativeStoreHint")}</p></>:active?<><h3>{provider||t("billingPro")}</h3>{entitlement.provider==="mollie"&&entitlement.auto_renew&&<><p className="muted">{entitlement.expires_at?t("billingEndsAt",{date:formatDate(entitlement.expires_at,locale)}):t("billingProHint")}</p><button className="button danger" onClick={()=>setCancelOpen(true)} disabled={busy}>{t("billingCancel")}</button></>}{entitlement.provider==="mollie"&&!entitlement.auto_renew&&entitlement.expires_at&&<div className="notice">{t("billingCancelledNotice",{date:formatDate(entitlement.expires_at,locale)})}</div>}</>:pending?<><h3>{t("billingReturnProcessing")}</h3><p className="muted">{t("billingProHint")}</p><div className="actions"><button className="button secondary" onClick={refresh} disabled={busy}>{t("billingRefresh")}</button><button className="button" onClick={startCheckout} disabled={busy}>{t("billingUpgrade")}</button></div></>:config.available?<><h3>{t("billingPro")}</h3><p><strong>{t("billingPriceYear",{price})}</strong></p><div className="row between"><span className="muted">{t("billingRenews")}</span><strong>{t("billingYes")}</strong></div><p className="muted">{t("billingProHint")}</p>{config.environment==="test"&&<div className="notice"><strong>{t("billingTestMode")}</strong><div>{t("billingTestModeHint")}</div></div>}<button className="button" onClick={startCheckout} disabled={busy}>{busy?t("billingOpeningCheckout"):t("billingUpgrade")}</button></>:<><h3>{t("billingUnavailable")}</h3><p className="muted">{t("billingUnavailableHint")}</p></>}
      </section>
    </div>
    {cancelOpen&&<Modal title={t("billingCancelTitle")} onClose={()=>setCancelOpen(false)}><div className="stack"><p>{t("billingCancelQuestion")}</p><div className="actions"><button className="button secondary" onClick={()=>setCancelOpen(false)} disabled={busy}>{t("billingKeepSubscription")}</button><button className="button danger" onClick={cancelRenewal} disabled={busy}>{t("billingConfirmCancel")}</button></div></div></Modal>}
  </>;
}

function formatDate(value:string,locale:string){return new Date(value).toLocaleDateString(locale)}
function providerLabel(provider:string|null,t:(key:string)=>string){const keys:Record<string,string>={apple:"billingManagedApple",google:"billingManagedGoogle",admin:"billingManagedAdmin",mollie:"billingManagedMollie"};return provider?t(keys[provider]??provider):""}
function statusLabel(status:string|null,t:(key:string)=>string){const keys:Record<string,string>={active:"billingStatusActive",grace_period:"billingStatusGrace",cancelled:"billingStatusCancelled",pending:"billingStatusPending",expired:"billingStatusExpired",on_hold:"billingStatusOnHold"};return status?t(keys[status]??status):""}
