"use client";
import {useEffect,useMemo,useState} from "react";
import {api} from "@/lib/api";
import type {CollectionSummary,ParticipantListSummary,ParticipantOpenBalance} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {Loading,ErrorState,Empty} from "../State";

type OverviewTarget="lists"|"collections"|"settings";
type CreateAction="list"|"collection";

export function OverviewPage({onNavigate}:{onNavigate:(v:OverviewTarget,create?:CreateAction)=>void}){
  const {t,locale}=useI18n();
  const [lists,setLists]=useState<ParticipantListSummary[]>([]);
  const [collections,setCollections]=useState<CollectionSummary[]>([]);
  const [balances,setBalances]=useState<ParticipantOpenBalance[]>([]);
  const [state,setState]=useState<"loading"|"ok"|"error">("loading");

  async function load(){
    setState("loading");
    try{
      const [l,c,b]=await Promise.all([api.lists(),api.collections(),api.openBalances()]);
      setLists(l);setCollections(c);setBalances(b);setState("ok");
    }catch{setState("error")}
  }

  useEffect(()=>{void load()},[]);

  const participants=useMemo(()=>lists.reduce((sum,list)=>sum+list.participant_count,0),[lists]);
  const totals=useMemo(()=>balances.reduce<Record<string,number>>((result,row)=>{result[row.currency]=(result[row.currency]??0)+Number(row.open_amount);return result},{}),[balances]);
  const money=(n:number,currency:string)=>new Intl.NumberFormat(locale,{style:"currency",currency}).format(n);
  const openValue=Object.entries(totals).length
    ?Object.entries(totals).map(([currency,amount])=>money(amount,currency)).join(" · ")
    :money(0,collections[0]?.currency||"EUR");

  if(state==="loading")return <Loading/>;
  if(state==="error")return <ErrorState onRetry={load}/>;

  return <>
    <div className="page-title"><div><h1>{t("overview")}</h1><div className="muted">{t("subtitle")}</div></div><div className="actions"><button className="button secondary" onClick={()=>onNavigate("lists","list")}>{t("newList")}</button><button className="button" onClick={()=>onNavigate("collections","collection")}>{t("newCollection")}</button></div></div>

    <div className="grid-4">
      <Metric label={t("participantLists")} value={lists.length}/>
      <Metric label={t("participants")} value={participants}/>
      <Metric label={t("collections")} value={collections.length}/>
      <Metric label={t("openAmount")} value={openValue}/>
    </div>

    <div className="split">
      <section className="card">
        <div className="row between"><h3>{t("recentCollections")}</h3><button className="button ghost small" onClick={()=>onNavigate("collections")}>{t("all")}</button></div>
        {collections.length===0?<Empty text={t("noCollections")}/>:collections.slice(0,5).map(collection=>{const openCount=Math.max(0,collection.participant_count-collection.paid_count);const openAmount=Number(collection.amount)*openCount;return <div className="mini-row" key={collection.id}><div><strong>{collection.name}</strong><div className="muted">{t("openTotal")}: {openCount}/{collection.participant_count}</div><div className="progress"><span style={{width:`${collection.participant_count?openCount/collection.participant_count*100:0}%`}}/></div></div><strong>{money(openAmount,collection.currency)}</strong></div>})}
      </section>
      <section className="card">
        <div className="row between"><h3>{t("participantLists")}</h3><button className="button ghost small" onClick={()=>onNavigate("lists")}>{t("all")}</button></div>
        {lists.length===0?<Empty text={t("noLists")}/>:lists.slice(0,7).map(list=><div className="mini-row" key={list.id}><strong>{list.name}</strong><span>{t("people",{count:list.participant_count})}</span></div>)}
      </section>
    </div>

    <section className="card overview-balances"><div className="row between"><h3>{t("openParticipantBalances")}</h3><span className="muted">{balances.length}</span></div>{balances.length===0?<Empty text={t("noOpenParticipantBalances")}/>:<div className="table-wrap"><table className="table overview-balance-table"><thead><tr><th>{t("name")}</th><th>{t("collections")}</th><th>{t("openAmount")}</th></tr></thead><tbody>{balances.map(row=><tr key={`${row.participant_id}-${row.currency}`}><td><strong>{row.name}</strong><div className="muted">{row.email??row.phone??"—"}</div></td><td>{row.collection_count}</td><td><strong>{money(Number(row.open_amount),row.currency)}</strong></td></tr>)}</tbody></table></div>}</section>
  </>
}

function Metric({label,value}:{label:string;value:string|number}){return <div className="metric"><div className="muted">{label}</div><div className="value">{value}</div></div>}
