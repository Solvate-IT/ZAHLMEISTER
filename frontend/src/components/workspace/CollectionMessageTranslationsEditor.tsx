"use client";

import {useEffect,useMemo,useState} from "react";

import {ApiError,api} from "@/lib/api";
import {useI18n} from "@/lib/i18n";
import type {CollectionMessageTranslations} from "@/lib/types";

function languageName(uiLocale:string,language:string):string{
  try{return new Intl.DisplayNames([uiLocale],{type:"language"}).of(language)??language.toUpperCase()}catch{return language.toUpperCase()}
}

export function CollectionMessageTranslationsEditor({collectionId}:{collectionId:string}){
  const {t,locale}=useI18n();
  const [data,setData]=useState<CollectionMessageTranslations|null>(null);
  const [language,setLanguage]=useState(locale.split("-")[0]);
  const [body,setBody]=useState("");
  const [savedBody,setSavedBody]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");

  async function load(){
    setBusy(true);setError("");
    try{
      const next=await api.collectionMessageTranslations(collectionId);
      setData(next);
      const preferred=next.translations[language]!==undefined?language:(next.required_languages[0]??Object.keys(next.translations)[0]??locale.split("-")[0]);
      const text=next.translations[preferred]??"";
      setLanguage(preferred);setBody(text);setSavedBody(text);
    }catch{setError(t("loadError"))}finally{setBusy(false)}
  }

  useEffect(()=>{void load()},[collectionId]);

  const languages=useMemo(()=>Array.from(new Set([...(data?.required_languages??[]),...Object.keys(data?.translations??{})])).sort(),[data]);
  const changed=body.trim()!==savedBody.trim();

  function changeLanguage(next:string){
    setLanguage(next);
    const text=data?.translations[next]??"";
    setBody(text);setSavedBody(text);setError("");
  }

  async function save(){
    if(!body.trim()||busy)return;
    setBusy(true);setError("");
    try{
      const next=await api.saveCollectionMessageTranslation(collectionId,language,body.trim());
      setData(next);setSavedBody(body.trim());
    }catch{setError(t("requestFailed"))}finally{setBusy(false)}
  }

  async function translateOtherLanguages(){
    if(!body.trim()||busy||!data?.translation_configured)return;
    setBusy(true);setError("");
    try{
      const next=await api.translateCollectionMessageLanguages(collectionId,language,body.trim());
      setData(next);setSavedBody(body.trim());
    }catch(err){setError(err instanceof ApiError&&err.status===502?t("translationFailed"):t("requestFailed"))}finally{setBusy(false)}
  }

  if(!data&&busy)return <div className="muted">{t("loading")}</div>;
  return <div className="card stack">
    <strong>{t("collectionMessageTranslations")}</strong>
    <p className="muted">{t("collectionMessageTranslationsHint")}</p>
    <div className="field"><label>{t("messageLanguage")}</label><select className="select" value={language} onChange={event=>changeLanguage(event.target.value)}>{languages.map(code=><option key={code} value={code}>{languageName(locale,code)}{data?.translations[code]?" ✓":""}</option>)}</select></div>
    <div className="field"><label>{t("message")}</label><textarea className="textarea" style={{minHeight:220}} value={body} onChange={event=>setBody(event.target.value)}/></div>
    {error&&<div className="notice error">{error}</div>}
    <div className="actions">
      <button type="button" className="button secondary" disabled={busy||!body.trim()||!changed} onClick={save}>{t("saveTranslation")}</button>
      {data?.translation_configured&&<button type="button" className="button" disabled={busy||!body.trim()} onClick={translateOtherLanguages}>{t("translateOtherLanguages")}</button>}
    </div>
  </div>
}
