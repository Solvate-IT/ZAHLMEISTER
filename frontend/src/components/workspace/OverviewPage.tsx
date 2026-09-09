"use client";
import {useEffect,useMemo,useState} from "react";
import {api} from "@/lib/api";
import type {CollectionSummary,ParticipantOpenBalance} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {Loading,ErrorState,Empty} from "../State";

type OverviewTarget="lists"|"collections"|"settings";
type CreateAction="list"|"collection";

export function OverviewPage({onNavigate}:{onNavigate:(v:OverviewTarget,create?:CreateAction)=>void}){
  const {t,locale}=useI18n();
  const [collections,setCollections]=useState<CollectionSummary[]>([]);
  const [balances,setBalances]=useState<ParticipantOpenBalance[]>([]);
  const [state,setState]=useState<"loading"|"ok"|"error">("loading");
  async function load(){setState("loading");try{const [c,b]=await Promise.all([api.collections(),api.openBalances()]);setCollections(c);setBalances(b);setState("ok")}catch{setState("error")}}
  useEffect(()=>{void load()},[]);
  const totals=useMemo(()=>balances.reduce<Record<string,number>>((result,row)=>{result[row.currency]=(result[row.currency]??0)+Number(row.open_amount);return result},{}),[balances]);
  const money=(n:number,currency:string)=>new Intl.NumberFormat(locale,{style:"currency",currency}).format(n);
  if(state==="loading")return <Loading/>;
  if(state==="error")return <ErrorState onRetry={load}/>;
  return <>
    <div className="page-title"><div><h1>{t("overview")}</h1><div className="muted">{t("subtitle")}</div></div><div className="actions"><button className="button secondary" onClick={()=>onNavigate("lists","list")}>{t("newList")}</button><button className="button" onClick={()=>onNavigate("collections","collection")}>{t("newCollection")}</button></div></div>
    <div className="overview-open-metric"><Metric label={t("openAmount")} value={Object.entries(totals).length?Object.entries(totals).map(([currency,amount])=>money(amount,currency)).join(" · "):money(0,collections[0]?.currency||"EUR")}/></div>
    <section className="card overview-balances"><div className="row between"><h3>{t("openParticipantBalances")}</h3><span className="muted">{balances.length}</span></div>{balances.length===0?<Empty text={t("noOpenParticipantBalances")}/>:<div className="table-wrap"><table className="table overview-balance-table"><thead><tr><th>{t("name")}</th><th>{t("collections")}</th><th>{t("openAmount")}</th></tr></thead><tbody>{balances.map(row=><tr key={`${row.participant_id}-${row.currency}`}><td><strong>{row.name}</strong><div className="muted">{row.email??row.phone??"—"}</div></td><td>{row.collection_count}</td><td><strong>{money(Number(row.open_amount),row.currency)}</strong></td></tr>)}</tbody></table></div>}</section>
  </>
}
function Metric({label,value}:{label:string;value:string|number}){return <div className="metric"><div className="muted">{label}</div><div className="value">{value}</div></div>}
