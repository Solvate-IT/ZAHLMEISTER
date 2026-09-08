"use client";

import {useEffect,useMemo,useState} from "react";

import {ApiError,api} from "@/lib/api";
import {supportedLocales,useI18n} from "@/lib/i18n";
import type {MessageTemplate,TemplateTranslationStatus} from "@/lib/types";

function languageName(uiLocale:string,language:string):string{
  try{return new Intl.DisplayNames([uiLocale],{type:"language"}).of(language)??language.toUpperCase()}catch{return language.toUpperCase()}
}

export function TemplateSettingsPanel(){
  const {t}=useI18n();
  const [items,setItems]=useState<MessageTemplate[]>([]);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [creating,setCreating]=useState(false);
  const [translation,setTranslation]=useState<TemplateTranslationStatus|null>(null);
  const [notice,setNotice]=useState("");

  async function load(preferredId?:string|null){
    try{
      const [templates,status]=await Promise.all([api.templates(),api.templateTranslationStatus()]);
      setItems(templates);
      setTranslation(status);
      const preferred=preferredId??selectedId;
      const next=templates.find(item=>item.id===preferred)??templates.find(item=>item.is_default)??templates[0]??null;
      setSelectedId(next?.id??null);
      if(!templates.length)setCreating(true);
    }catch{setNotice(t("loadError"))}
  }
  useEffect(()=>{void load()},[]);

  const selected=items.find(item=>item.id===selectedId)??null;
  const languages=translation?.supported_languages?.length?translation.supported_languages:[...supportedLocales];

  return <section className="card">
    <h3>{t("messageTemplates")}</h3>
    <p className="muted">{t("messageTemplateHint")}</p>
    {notice&&<div className="notice">{notice}</div>}
    <div style={{display:"flex",alignItems:"flex-start",gap:18,flexWrap:"wrap"}}>
      <div style={{display:"grid",gap:8,flex:"0 1 240px",minWidth:190}}>
        <TemplateListButton active={creating} onClick={()=>setCreating(true)} label={`+ ${t("newTemplate")}`}/>
        {items.map(item=><TemplateListButton key={item.id} active={!creating&&selectedId===item.id} onClick={()=>{setCreating(false);setSelectedId(item.id)}} label={item.name} secondary={item.is_default?t("defaultTemplate"):undefined}/>) }
      </div>
      <div style={{flex:"1 1 420px",minWidth:"min(100%, 360px)"}}>
        {creating?<NewTemplateEditor translation={translation} languages={languages} onCreated={async item=>{setCreating(false);setSelectedId(item.id);setNotice(t("templateSaved"));await load(item.id)}}/>:selected?<TemplateEditor item={selected} translation={translation} languages={languages} onChanged={async updated=>{setSelectedId(updated.id);setNotice(t("templateSaved"));await load(updated.id)}} onDeleted={async()=>{setNotice(t("saved"));setCreating(false);await load(null)}}/>:<div className="empty">{t("noData")}</div>}
      </div>
    </div>
  </section>
}

function TemplateListButton({active,onClick,label,secondary}:{active:boolean;onClick:()=>void;label:string;secondary?:string}){
  return <button type="button" onClick={onClick} style={{display:"grid",gap:3,textAlign:"left",border:"1px solid var(--border)",borderRadius:12,padding:"11px 12px",background:active?"#e9f2ff":"white",color:active?"var(--blue)":"var(--navy)",fontWeight:700}}><span>{label}</span>{secondary&&<small className="muted">{secondary}</small>}</button>
}

function NewTemplateEditor({translation,languages,onCreated}:{translation:TemplateTranslationStatus|null;languages:string[];onCreated:(item:MessageTemplate)=>void}){
  const {t,locale}=useI18n();
  const currentLanguage=locale.split("-")[0];
  const [name,setName]=useState("");
  const [body,setBody]=useState("");
  const [language,setLanguage]=useState(translation?.configured?"":currentLanguage);
  const [autoTranslate,setAutoTranslate]=useState(Boolean(translation?.configured));
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");

  async function create(){
    if(!name.trim()||!body.trim()||busy)return;
    setBusy(true);setError("");
    try{
      const item=await api.createTemplate({name:name.trim(),body:body.trim(),source_language:language||undefined,auto_translate:Boolean(translation?.configured&&autoTranslate)});
      onCreated(item);
    }catch(err){setError(err instanceof ApiError&&err.status===502?t("translationFailed"):t("requestFailed"))}
    finally{setBusy(false)}
  }

  return <div className="form">
    <strong>{t("newTemplate")}</strong>
    <div className="field"><label>{t("templateName")}</label><input className="input" autoFocus value={name} onChange={event=>setName(event.target.value)}/></div>
    <div className="field"><label>{t("sourceLanguage")}</label><select className="select" value={language} onChange={event=>setLanguage(event.target.value)}>{translation?.configured&&autoTranslate&&<option value="">{t("detectLanguageAutomatically")}</option>}{languages.map(code=><option key={code} value={code}>{languageName(locale,code)}</option>)}</select></div>
    <div className="field"><label>{t("initialTemplateText")}</label><textarea className="textarea" style={{minHeight:260}} value={body} onChange={event=>setBody(event.target.value)}/></div>
    <div className="notice">{t("variables")}: {"{{first_name}} · {{name}} · {{collection_name}} · {{amount}} · {{due_date}} · {{payment_link}} · {{payment_reference}}"}</div>
    {translation?.configured?<label className="checkbox"><input type="checkbox" checked={autoTranslate} onChange={event=>{const enabled=event.target.checked;setAutoTranslate(enabled);if(!enabled&&!language)setLanguage(currentLanguage)}}/>{t("autoTranslateMissing")}</label>:<p className="muted">{t("autoTranslationUnavailable")}</p>}
    {error&&<div className="notice error">{error}</div>}
    <div className="actions"><button type="button" className="button" onClick={create} disabled={busy||!name.trim()||!body.trim()}>{t("create")}</button></div>
  </div>
}

function TemplateEditor({item,translation,languages,onChanged,onDeleted}:{item:MessageTemplate;translation:TemplateTranslationStatus|null;languages:string[];onChanged:(item:MessageTemplate)=>void;onDeleted:()=>void}){
  const {t,locale}=useI18n();
  const initialLanguage=useMemo(()=>{const current=locale.split("-")[0];return item.translations[current]?current:Object.keys(item.translations)[0]??current},[item,locale]);
  const [language,setLanguage]=useState(initialLanguage);
  const [name,setName]=useState(item.name);
  const [body,setBody]=useState(item.translations[initialLanguage]??"");
  const [isDefault,setDefault]=useState(item.is_default);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");

  useEffect(()=>{const next=item.translations[language]!==undefined?language:(Object.keys(item.translations)[0]??locale.split("-")[0]);setName(item.name);setLanguage(next);setBody(item.translations[next]??"");setDefault(item.is_default)},[item]);
  function changeLanguage(next:string){setLanguage(next);setBody(item.translations[next]??"");setError("")}
  async function save(){if(!body.trim()||busy)return;setBusy(true);setError("");try{const updated=await api.updateTemplate(item.id,{name,translations:{[language]:body},is_default:isDefault});onChanged(updated)}catch{setError(t("requestFailed"))}finally{setBusy(false)}}
  async function translateMissing(){if(!translation?.configured||!body.trim()||busy)return;setBusy(true);setError("");try{let updated=await api.updateTemplate(item.id,{name,translations:{[language]:body},is_default:isDefault});updated=await api.translateMissingTemplate(item.id,language);onChanged(updated)}catch(err){setError(err instanceof ApiError&&err.status===502?t("translationFailed"):t("requestFailed"))}finally{setBusy(false)}}
  async function remove(){if(item.is_default||busy||!confirm(t("confirmDelete")))return;setBusy(true);try{await api.deleteTemplate(item.id);onDeleted()}catch{setError(t("requestFailed"))}finally{setBusy(false)}}

  const translatedCount=Object.keys(item.translations).length;
  return <div className="form">
    <div className="field"><label>{t("templateName")}</label><input className="input" value={name} onChange={event=>setName(event.target.value)}/></div>
    <div className="row between"><div className="field" style={{flex:1}}><label>{t("messageLanguage")}</label><select className="select" value={language} onChange={event=>changeLanguage(event.target.value)}>{languages.map(code=><option key={code} value={code}>{languageName(locale,code)}{item.translations[code]?" ✓":""}</option>)}</select></div><span className="muted">{t("translationCoverage",{current:translatedCount,total:languages.length})}</span></div>
    <div className="field"><label>{t("message")}</label><textarea className="textarea" style={{minHeight:300}} value={body} placeholder={t("missingTranslationHint")} onChange={event=>setBody(event.target.value)}/></div>
    <div className="notice">{t("variables")}: {"{{first_name}} · {{name}} · {{collection_name}} · {{amount}} · {{due_date}} · {{payment_link}} · {{payment_reference}}"}</div>
    <label className="checkbox"><input type="checkbox" checked={isDefault} onChange={event=>setDefault(event.target.checked)}/>{t("makeDefaultTemplate")}</label>
    {error&&<div className="notice error">{error}</div>}
    <div className="actions"><button type="button" className="button" onClick={save} disabled={busy||!body.trim()}>{t("save")}</button>{translation?.configured&&translatedCount<languages.length&&<button type="button" className="button secondary" onClick={translateMissing} disabled={busy||!body.trim()}>{t("translateMissingLanguages")}</button>}{!item.is_default&&<button type="button" className="button danger" onClick={remove} disabled={busy}>{t("delete")}</button>}</div>
  </div>
}
