"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import {useRouter,useSearchParams} from "next/navigation";
import {api,ApiError} from "@/lib/api";
import type {BillingEntitlement,BillingInvoice,BillingProfile,BillingProfileWrite,MollieBillingConfig} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {isNativeApp} from "@/lib/native";
import {Loading} from "../State";

const COUNTRY_CODES=["AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ","BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS","BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK","CL","CM","CN","CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC","EE","EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF","GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM","HN","HR","HT","HU","ID","IE","IL","IM","IN","IO","IQ","IR","IS","IT","JE","JM","JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC","LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK","ML","MM","MN","MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA","NC","NE","NF","NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG","PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW","SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS","ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO","TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI","VN","VU","WF","WS","YE","YT","ZA","ZM","ZW"] as const;
const OPEN_INVOICE_STATUSES=new Set(["creating","pending-payment","issued","overdue","payment-reversed","payment_reversed"]);

const EMPTY_PROFILE:BillingProfileWrite={customer_type:"consumer",given_name:"",family_name:"",organization_name:"",billing_email:"",street_and_number:"",postal_code:"",city:"",region:"",country:"",vat_number:"",organization_number:""};

export function BillingPage(){
  const {t,locale}=useI18n();
  const router=useRouter();
  const params=useSearchParams();
  const billingResult=params.get("billing");
  const [entitlement,setEntitlement]=useState<BillingEntitlement|null>(null);
  const [config,setConfig]=useState<MollieBillingConfig|null>(null);
  const [profile,setProfile]=useState<BillingProfile|null>(null);
  const [draft,setDraft]=useState<BillingProfileWrite>(EMPTY_PROFILE);
  const [invoices,setInvoices]=useState<BillingInvoice[]>([]);
  const [editingProfile,setEditingProfile]=useState(false);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const [native,setNative]=useState<boolean|null>(null);
  const profileSectionRef=useRef<HTMLElement|null>(null);
  const primaryProfileFieldRef=useRef<HTMLInputElement|null>(null);
  const regionNames=useMemo(()=>new Intl.DisplayNames([locale],{type:"region"}),[locale]);

  async function load(){
    setLoading(true);setError("");
    try{
      const [e,c,p,i]=await Promise.all([api.billingEntitlement(),api.mollieBillingConfig(),api.billingProfile(),api.billingInvoices()]);
      setEntitlement(e);setConfig(c);setProfile(p);setInvoices(i);
      if(p)setDraft(toDraft(p));else setDraft(EMPTY_PROFILE);
      if(!p)setEditingProfile(true);
    }catch{setError(t("billingError"))}finally{setLoading(false)}
  }
  function clearBillingResult(){const url=new URL(window.location.href);url.searchParams.delete("billing");router.replace(`${url.pathname}?${url.searchParams.toString()}`)}
  function openBillingProfile(){
    setEditingProfile(true);setError("");
    requestAnimationFrame(()=>{profileSectionRef.current?.scrollIntoView({behavior:"smooth",block:"start"});requestAnimationFrame(()=>primaryProfileFieldRef.current?.focus())});
  }

  useEffect(()=>{setNative(isNativeApp())},[]);
  useEffect(()=>{
    if(billingResult==="return"){
      setLoading(true);setError("");
      api.mollieBillingSync().then(async next=>{setEntitlement(next);await load();setNotice(next.active?t("billingActivated"):t("billingReturnProcessing"))}).catch(()=>setError(t("billingError"))).finally(()=>{setLoading(false);clearBillingResult()});
      return;
    }
    if(billingResult==="cancelled")setNotice(t("billingCheckoutCancelled"));
    load().finally(()=>{if(billingResult==="cancelled")clearBillingResult()});
  },[billingResult]);

  async function refresh(){
    if(!config?.available||native){await load();return}
    setBusy(true);setError("");
    try{const next=await api.mollieBillingSync();setEntitlement(next);await load();setNotice(next.active?t("billingActivated"):next.status==="pending"?t("billingReturnProcessing"):"")}catch{setError(t("billingError"))}finally{setBusy(false)}
  }
  async function saveProfile(e:React.FormEvent){
    e.preventDefault();setError("");
    if(!draft.billing_email||!draft.street_and_number||!draft.city||!draft.country||(draft.customer_type==="consumer"&&(!draft.given_name||!draft.family_name))||(draft.customer_type==="business"&&(!draft.organization_name||(!draft.vat_number&&!draft.organization_number)))){setError(t("billingRequiredFields"));return}
    setBusy(true);
    try{const saved=await api.saveBillingProfile(cleanDraft(draft));setProfile(saved);setDraft(toDraft(saved));setEditingProfile(false);setNotice(t("billingDetailsSaved"))}catch{setError(t("billingProfileInvalid"))}finally{setBusy(false)}
  }
  async function startCheckout(){
    if(!profile){openBillingProfile();setError(t("billingProfileRequired"));return}
    setBusy(true);setError("");setNotice(t("billingOpeningCheckout"));
    try{const checkout=await api.mollieBillingCheckout();window.location.assign(checkout.checkout_url)}catch(e){setNotice("");setError(e instanceof ApiError&&e.status===503?t("billingTaxUnavailable"):e instanceof ApiError&&e.status===422?t("billingProfileInvalid"):t("billingError"));setBusy(false)}
  }
  async function updateAutoRenew(enabled:boolean){
    setBusy(true);setError("");setNotice("");
    try{const next=await api.mollieBillingSetAutoRenew(enabled);setEntitlement(next);setNotice(enabled?t("saved"):(next.expires_at?t("billingCancelledNotice",{date:formatDate(next.expires_at,locale)}):t("saved")))}catch{setError(t("billingError"))}finally{setBusy(false)}
  }

  if(loading||native===null||!entitlement||!config)return <Loading/>;
  const active=entitlement.active;
  const pending=entitlement.provider==="mollie"&&entitlement.status==="pending";
  const price=config.amount?new Intl.NumberFormat(locale,{style:"currency",currency:config.currency}).format(Number(config.amount)):"";
  const provider=providerLabel(entitlement.provider,t);
  const status=statusLabel(entitlement.status,t);
  const showMollieDetails=!native||entitlement.provider==="mollie"||invoices.length>0;
  const openRenewalInvoice=invoices.find(item=>OPEN_INVOICE_STATUSES.has(item.status));
  const latestPaidInvoice=invoices.find(item=>item.status==="paid");
  const renewalInvoice=openRenewalInvoice??latestPaidInvoice;
  const renewalPrice=renewalInvoice?new Intl.NumberFormat(locale,{style:"currency",currency:renewalInvoice.currency}).format(Number(renewalInvoice.gross_amount)):price;
  const renewalDate=openRenewalInvoice?.period_start??latestPaidInvoice?.period_end??entitlement.expires_at;

  return <>
    <div className="page-title"><div><h1>{t("billingTitle")}</h1><div className="muted">{t("billingSubtitle")}</div></div><button className="button secondary" onClick={refresh} disabled={busy}>{t("billingRefresh")}</button></div>
    {error&&<div className="notice error">{error}</div>}{notice&&<div className="notice success">{notice}</div>}
    <div className="split billing-plan-grid">
      <section className="card"><div className="muted">{t("billingCurrentPlan")}</div><div className="payment-amount">{active?t("billingPro"):t("billingFree")}</div><p className="muted">{active?t("billingProHint"):t("billingFreeHint")}</p>{!active&&!pending&&<div className="notice">{t("billingFreeRegistration")}</div>}{(active||pending)&&<div className="stack">{provider&&<div className="row between"><span className="muted">{t("billingProvider")}</span><strong>{provider}</strong></div>}{status&&<div className="row between"><span className="muted">{t("billingStatus")}</span><span className={`status-pill ${entitlement.status??""}`}>{status}</span></div>}{active&&entitlement.expires_at&&<div className="notice">{t("billingEndsAt",{date:formatDate(entitlement.expires_at,locale)})}</div>}</div>}</section>
      <section className="card">
        {native?<><h3>{t("billingPro")}</h3><p className="muted">{t("billingNativeStoreHint")}</p></>:active?<><h3>{provider||t("billingPro")}</h3>{entitlement.provider==="mollie"&&<><div className="billing-renewal-row"><span className="muted">{t("billingRenews")}</span><RenewalSwitch checked={Boolean(entitlement.auto_renew)} disabled={busy} label={t("billingRenews")} onChange={updateAutoRenew}/></div>{entitlement.auto_renew?<><p className="muted">{renewalDate?t("billingNextRenewal",{date:formatDate(renewalDate,locale),price:renewalPrice}):t("billingProHint")}</p><div className="notice">{t("billingAutoDebitMandate")}</div></>:entitlement.expires_at&&<div className="notice">{t("billingCancelledNotice",{date:formatDate(entitlement.expires_at,locale)})}</div>}</>}</>:pending?<><h3>{t("billingReturnProcessing")}</h3><p className="muted">{t("billingProHint")}</p><div className="actions"><button className="button secondary" onClick={refresh} disabled={busy}>{t("billingRefresh")}</button><button className="button" onClick={startCheckout} disabled={busy}>{t("billingUpgrade")}</button></div></>:config.available?<><h3>{t("billingPro")}</h3><p><strong>{t("billingPriceYear",{price})}</strong></p><div className="billing-renewal-row"><span className="muted">{t("billingRenews")}</span><RenewalSwitch checked disabled label={t("billingRenews")} onChange={()=>{}}/></div><div className="notice">{t("billingAutoDebitMandate")}</div><p className="muted">{t("billingProHint")}</p>{config.environment==="test"&&<div className="notice"><strong>{t("billingTestMode")}</strong><div>{t("billingTestModeHint")}</div></div>}<button className="button" onClick={startCheckout} disabled={busy||!profile}>{busy?t("billingOpeningCheckout"):t("billingUpgrade")}</button>{!profile&&<button type="button" className="billing-profile-jump" onClick={openBillingProfile}>{t("billingProfileRequired")}</button>}</>:<><h3>{t("billingUnavailable")}</h3><p className="muted">{t("billingUnavailableHint")}</p></>}
      </section>
    </div>

    {showMollieDetails&&<section ref={profileSectionRef} className="card billing-section">
      <div className="row between"><div><h3>{t("billingDetailsTitle")}</h3><p className="muted">{t("billingDetailsHint")}</p></div>{profile&&!editingProfile&&<button className="button secondary" onClick={openBillingProfile}>{t("billingDetailsEdit")}</button>}</div>
      {editingProfile?<form className="form" onSubmit={saveProfile}>
        <div className="field"><label>{t("billingCustomerType")}</label><select className="input" value={draft.customer_type} onChange={e=>setDraft({...draft,customer_type:e.target.value as BillingProfileWrite["customer_type"]})}><option value="consumer">{t("billingConsumer")}</option><option value="business">{t("billingBusiness")}</option></select></div>
        {draft.customer_type==="consumer"?<div className="split"><div className="field"><label>{t("billingFirstName")}</label><input ref={primaryProfileFieldRef} className="input" value={draft.given_name??""} onChange={e=>setDraft({...draft,given_name:e.target.value})} required/></div><div className="field"><label>{t("billingFamilyName")}</label><input className="input" value={draft.family_name??""} onChange={e=>setDraft({...draft,family_name:e.target.value})} required/></div></div>:<><div className="field"><label>{t("billingLegalName")}</label><input ref={primaryProfileFieldRef} className="input" value={draft.organization_name??""} onChange={e=>setDraft({...draft,organization_name:e.target.value})} required/></div><div className="split"><div className="field"><label>{t("billingVatNumber")}</label><input className="input" value={draft.vat_number??""} onChange={e=>setDraft({...draft,vat_number:e.target.value})}/></div><div className="field"><label>{t("billingOrganizationNumber")}</label><input className="input" value={draft.organization_number??""} onChange={e=>setDraft({...draft,organization_number:e.target.value})}/></div></div><p className="muted">{t("billingVatHint")}</p></>}
        <div className="field"><label>{t("billingEmail")}</label><input type="email" className="input" value={draft.billing_email} onChange={e=>setDraft({...draft,billing_email:e.target.value})} required/></div>
        <div className="field"><label>{t("billingStreet")}</label><input className="input" value={draft.street_and_number} onChange={e=>setDraft({...draft,street_and_number:e.target.value})} required/></div>
        <div className="split"><div className="field"><label>{t("billingPostalCode")}</label><input className="input" value={draft.postal_code} onChange={e=>setDraft({...draft,postal_code:e.target.value})}/></div><div className="field"><label>{t("billingCity")}</label><input className="input" value={draft.city} onChange={e=>setDraft({...draft,city:e.target.value})} required/></div></div>
        <div className="split"><div className="field"><label>{t("billingRegion")}</label><input className="input" value={draft.region??""} onChange={e=>setDraft({...draft,region:e.target.value})}/></div><div className="field"><label>{t("billingCountry")}</label><select className="input" value={draft.country} onChange={e=>setDraft({...draft,country:e.target.value})} required><option value="">{t("billingCountryChoose")}</option>{COUNTRY_CODES.map(code=><option key={code} value={code}>{regionNames.of(code)??code}</option>)}</select></div></div>
        <div className="notice">{t("billingTaxScopeHint")}</div>
        <div className="actions"><button className="button" disabled={busy}>{t("billingDetailsSave")}</button>{profile&&<button type="button" className="button secondary" onClick={()=>{setDraft(toDraft(profile));setEditingProfile(false)}} disabled={busy}>{t("cancel")}</button>}</div>
      </form>:profile&&<div className="stack"><div><strong>{profile.customer_type==="business"?profile.organization_name:`${profile.given_name??""} ${profile.family_name??""}`.trim()}</strong><div className="muted">{profile.street_and_number} · {[profile.postal_code,profile.city].filter(Boolean).join(" ")} · {regionNames.of(profile.country)??profile.country}</div><div className="muted">{profile.billing_email}</div>{profile.customer_type==="business"&&(profile.vat_number||profile.organization_number)&&<div className="muted">{[profile.vat_number,profile.organization_number].filter(Boolean).join(" · ")}</div>}</div></div>}
    </section>}

    {showMollieDetails&&<section className="card billing-section"><h3>{t("billingInvoicesTitle")}</h3><p className="muted">{t("billingInvoicesHint")}</p>{invoices.length===0?<div className="muted">{t("billingNoInvoices")}</div>:<div className="table-wrap"><table className="table"><thead><tr><th>{t("billingInvoiceNumber")}</th><th>{t("billingInvoicePeriod")}</th><th>{t("billingInvoiceAmount")}</th><th>{t("billingInvoiceVat")}</th><th>{t("billingInvoiceStatus")}</th><th>{t("actions")}</th></tr></thead><tbody>{invoices.map(item=><tr key={item.id}><td>{item.invoice_number??"—"}</td><td>{formatDate(item.period_start,locale)} – {formatDate(item.period_end,locale)}</td><td>{new Intl.NumberFormat(locale,{style:"currency",currency:item.currency}).format(Number(item.gross_amount))}</td><td>{Number(item.vat_rate).toLocaleString(locale)} %</td><td><span className={`status-pill ${item.status}`}>{invoiceStatusLabel(item.status,t)}</span></td><td>{item.payment_url&&item.status!=="paid"&&item.status!=="cancelled"?<a className="button secondary small" href={item.payment_url} target="_blank" rel="noreferrer">{t("billingInvoicePay")}</a>:"—"}</td></tr>)}</tbody></table></div>}</section>}
  </>;
}

function RenewalSwitch({checked,disabled,label,onChange}:{checked:boolean;disabled:boolean;label:string;onChange:(checked:boolean)=>void}){return <label className="toggle-switch"><input type="checkbox" checked={checked} disabled={disabled} aria-label={label} onChange={e=>onChange(e.target.checked)}/><span className="toggle-switch-track" aria-hidden="true"/></label>}
function toDraft(profile:BillingProfile):BillingProfileWrite{return {customer_type:profile.customer_type,given_name:profile.given_name??"",family_name:profile.family_name??"",organization_name:profile.organization_name??"",billing_email:profile.billing_email,street_and_number:profile.street_and_number,postal_code:profile.postal_code,city:profile.city,region:profile.region??"",country:profile.country,vat_number:profile.vat_number??"",organization_number:profile.organization_number??""}}
function cleanDraft(draft:BillingProfileWrite):BillingProfileWrite{return {...draft,given_name:draft.given_name?.trim()||null,family_name:draft.family_name?.trim()||null,organization_name:draft.organization_name?.trim()||null,billing_email:draft.billing_email.trim(),street_and_number:draft.street_and_number.trim(),postal_code:draft.postal_code.trim(),city:draft.city.trim(),region:draft.region?.trim()||null,country:draft.country.trim().toUpperCase(),vat_number:draft.vat_number?.trim()||null,organization_number:draft.organization_number?.trim()||null}}
function formatDate(value:string,locale:string){return new Date(value).toLocaleDateString(locale)}
function providerLabel(provider:string|null,t:(key:string)=>string){const keys:Record<string,string>={apple:"billingManagedApple",google:"billingManagedGoogle",admin:"billingManagedAdmin",mollie:"billingManagedMollie"};return provider?t(keys[provider]??provider):""}
function statusLabel(status:string|null,t:(key:string)=>string){const keys:Record<string,string>={active:"billingStatusActive",grace_period:"billingStatusGrace",cancelled:"billingStatusCancelled",pending:"billingStatusPending",expired:"billingStatusExpired",on_hold:"billingStatusOnHold"};return status?t(keys[status]??status):""}
function invoiceStatusLabel(status:string,t:(key:string)=>string){const keys:Record<string,string>={paid:"billingInvoicePaid","pending-payment":"billingInvoicePending",issued:"billingInvoiceIssued",overdue:"billingInvoiceOverdue","payment-reversed":"billingInvoiceReversed",payment_reversed:"billingInvoiceReversed",cancelled:"billingInvoiceCancelled",canceled:"billingInvoiceCancelled",creating:"billingInvoicePending"};return t(keys[status]??"billingInvoicePending")}
