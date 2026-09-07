"use client";

import {useEffect,useMemo,useState} from "react";

import {ApiError,api} from "@/lib/api";
import {supportedLocales,useI18n} from "@/lib/i18n";
import type {MessageTemplate,TemplateTranslationStatus} from "@/lib/types";

function languageName(uiLocale:string,language:string):string{
  try{return new Intl.DisplayNames([uiLocale],{type:"language"}).of(language)??language.toUpperCase()}catch{return language.toUpperCase()}
}

export function TemplateSettingsPanel(){
  const {t,locale}=useI18n();
  const currentLanguage=locale.split("-")[0];
  const [items,setItems]=useState<MessageTemplate[]>([]);
  const [selected,setSelected]=useState<MessageTemplate|null>(null);
  const [translation,setTranslation]=useState<TemplateTranslationStatus|null>(null);
  const [notice,setNotice]=useState("");
  const [newName,setNewName]=useState("");
  const [newBody,setNewBody]=useState("");
  const [newLanguage,setNewLanguage]=useState("");
  const [autoTranslate,setAutoTranslate]=useState(true);
  const [busy,setBusy]=useState(false);

  async function load(){
    try{
      const [templates,status]=await Promise.all([api.templates(),api.templateTranslationStatus()]);
      setItems(templates);
      setTranslation(status);
      setAutoTranslate(current=>status.configured?current:false);
      if(!status.configured)setNewLanguage(current=>current||currentLanguage);
      if(selected)setSelected(templates.find(item=>item.id===selected.id)??null);
    }catch{setNotice(t("loadError"))}
  }
  useEffect(()=>{void load()},[]);

  async function create(){
    if(!newName.trim()||!newBody.trim()||busy)return;
    setBusy(true);setNotice("");
    try{
      const item=await api.createTemplate({
        name:newName.trim(),
        body:newBody.trim(),
        source_language:newLanguage||undefined,
        auto_translate:Boolean(translation?.configured&&autoTranslate),
      });
      setNewName("");setNewBody("");setNewLanguage(translation?.configured?"":currentLanguage);setSelected(item);await load();setNotice(t("templateSaved"));
    }catch(error){setNotice(error instanceof ApiError&&error.status===502?t("translationFailed"):t("requestFailed"))}
    finally{setBusy(false)}
  }

  const languages=translation?.supported_languages?.length?translation.supported_languages:[...supportedLocales];
  return <section className="card">
    <h3>{t("messageTemplates")}</h3>
    <p className="muted">{t("messageTemplateHint")}</p>
    {notice&&<div className="notice">{notice}</div>}
    <div className="card form">
      <strong>{t("newTemplate")}</strong>
      <div className="field"><label>{t("templateName")}</label><input className="input" value={newName} onChange={event=>setNewName(event.target.value)}/></div>
      <div className="field"><label>{t("sourceLanguage")}</label><select className="select" value={newLanguage} onChange={event=>setNewLanguage(event.target.value)}>{translation?.configured&&autoTranslate&&<option value="">{t("detectLanguageAutomatically")}</option>}{languages.map(language=><option key={language} value={language}>{languageName(locale,language)}</option>)}</select></div>
      <div className="field"><label>{t("initialTemplateText")}</label><textarea className="textarea" style={{minHeight:180}} value={newBody} onChange={event=>setNewBody(event.target.value)}/></div>
      <div className="notice">{t("variables")}: {"{{first_name}} · {{name}} · {{collection_name}} · {{amount}} · {{due_date}} · {{payment_link}} · {{payment_reference}}"}</div>
      {translation?.configured?<label className="checkbox"><input type="checkbox" checked={autoTranslate} onChange={event=>{const enabled=event.target.checked;setAutoTranslate(enabled);if(!enabled&&!newLanguage)setNewLanguage(currentLanguage)}}/>{t("autoTranslateMissing")}</label>:<p className="muted">{t("autoTranslationUnavailable")}</p>}
      <button className="button" onClick={create} disabled={busy||!newName.trim()||!newBody.trim()}>{t("create")}</button>
    </div>
    <div className="split">
      <div className="stack">{items.map(item=><button key={item.id} className={`button ${selected?.id===item.id?"":"secondary"}`} onClick={()=>setSelected(item)}>{item.name}{item.is_default?` · ${t("defaultTemplate")}`:""}</button>)}</div>
      {selected&&<TemplateEditor item={selected} translation={translation} languages={languages} onChanged={async updated=>{setSelected(updated);setNotice(t("templateSaved"));await load()}} onDeleted={async()=>{setSelected(null);setNotice(t("saved"));await load()}}/>}
    </div>
  </section>
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
  async function translateMissing(){if(!translation?.configured||!body.trim()||busy)return;setBusy(true);setError("");try{let updated=await api.updateTemplate(item.id,{name,translations:{[language]:body},is_default:isDefault});updated=await api.translateMissingTemplate(item.id,language);onChanged(updated)}catch(error){setError(error instanceof ApiError&&error.status===502?t("translationFailed"):t("requestFailed"))}finally{setBusy(false)}}
  async function remove(){if(item.is_default||busy||!confirm(t("confirmDelete")))return;setBusy(true);try{await api.deleteTemplate(item.id);onDeleted()}catch{setError(t("requestFailed"))}finally{setBusy(false)}}

  const translatedCount=Object.keys(item.translations).length;
  return <div className="form">
    <div className="field"><label>{t("templateName")}</label><input className="input" value={name} onChange={event=>setName(event.target.value)}/></div>
    <div className="row between"><div className="field" style={{flex:1}}><label>{t("messageLanguage")}</label><select className="select" value={language} onChange={event=>changeLanguage(event.target.value)}>{languages.map(code=><option key={code} value={code}>{languageName(locale,code)}{item.translations[code]?" ✓":""}</option>)}</select></div><span className="muted">{t("translationCoverage",{current:translatedCount,total:languages.length})}</span></div>
    <div className="field"><label>{t("message")}</label><textarea className="textarea" style={{minHeight:240}} value={body} placeholder={t("missingTranslationHint")} onChange={event=>setBody(event.target.value)}/></div>
    <div className="notice">{t("variables")}: {"{{first_name}} · {{name}} · {{collection_name}} · {{amount}} · {{due_date}} · {{payment_link}} · {{payment_reference}}"}</div>
    <label className="checkbox"><input type="checkbox" checked={isDefault} onChange={event=>setDefault(event.target.checked)}/>{t("makeDefaultTemplate")}</label>
    {error&&<div className="notice error">{error}</div>}
    <div className="actions"><button className="button" onClick={save} disabled={busy||!body.trim()}>{t("save")}</button>{translation?.configured&&translatedCount<languages.length&&<button className="button secondary" onClick={translateMissing} disabled={busy||!body.trim()}>{t("translateMissingLanguages")}</button>}{!item.is_default&&<button className="button danger" onClick={remove} disabled={busy}>{t("delete")}</button>}</div>
  </div>
}
