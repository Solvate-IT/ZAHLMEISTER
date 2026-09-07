"use client";

import {useEffect, useMemo, useState} from "react";
import {api, ApiError} from "@/lib/api";
import type {ChannelSetting, CommunicationConnection} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {Modal} from "../Modal";
import {Loading} from "../State";

function channelLabel(t:(key:string)=>string, channel:string):string {
  const map:Record<string,string> = {
    email:"email", sms:"sms", whatsapp:"whatsApp", telegram:"telegram",
    instagram:"instagram", messenger:"messenger",
  };
  return t(map[channel] ?? channel);
}

function integrationStatus(t:(key:string)=>string, status:string):string {
  const map:Record<string,string> = {
    connected:"statusConnected", active:"active", not_tested:"statusNotTested",
    ok:"connectionOk", failed:"statusFailed", error:"statusError",
    disconnected:"statusDisconnected", connecting:"statusConnecting", disabled:"statusDisabled",
  };
  return t(map[status] ?? "statusUnknown");
}

function errorMessage(error:unknown, fallback:string):string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

export function CommunicationSettingsPanel() {
  const {t} = useI18n();
  const [settings,setSettings] = useState<ChannelSetting[]|null>(null);
  const [connections,setConnections] = useState<CommunicationConnection[]>([]);
  const [notice,setNotice] = useState("");
  const [mailServerOpen,setMailServerOpen] = useState(false);
  const [infobipOpen,setInfobipOpen] = useState(false);

  async function load() {
    try {
      const [rows, connectionRows] = await Promise.all([
        api.communicationSettings(),
        api.communicationConnections(),
      ]);
      setSettings(rows);
      setConnections(connectionRows);
    } catch {
      setNotice(t("loadError"));
      setSettings([]);
    }
  }

  useEffect(()=>{void load()},[]);
  useEffect(()=>{
    if(typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const result = params.get("microsoft365");
    if(!result) return;
    setNotice(
      result === "connected" ? t("microsoft365Connected") :
      result === "cancelled" ? t("microsoft365Cancelled") :
      t("microsoft365ConnectionFailed")
    );
    params.delete("microsoft365");
    const next = params.toString();
    window.history.replaceState({},"",`${window.location.pathname}${next?`?${next}`:""}`);
    void load();
  },[t]);

  const email = settings?.find(row=>row.channel==="email") ?? null;
  const infobip = connections.find(row=>row.provider==="infobip"&&row.status==="connected") ?? null;
  const microsoft = connections.find(row=>row.provider==="microsoft365") ?? null;
  const microsoftConnected = microsoft?.status === "connected";
  const customMailConfigured = Boolean(email?.fields?.smtp_host || email?.fields?.from_address);
  const emailProvider = useMemo(()=>{
    if(!email || email.mode === "external") return "external";
    if(email.provider === "microsoft365") return "microsoft365";
    if(email.provider === "infobip") return "infobip";
    return customMailConfigured ? "smtp_imap" : "platform";
  },[email,customMailConfigured]);

  if(settings===null) return <Loading/>;

  async function saveEmailProvider(next:string) {
    if(!email) return;
    try {
      if(next === "external") {
        await api.saveCommunicationSetting("email",{mode:"external",fields:{}});
      } else if(next === "platform") {
        await api.saveCommunicationSetting("email",{mode:"internal",provider:"smtp_imap",fields:{}});
      } else if(next === "smtp_imap") {
        setMailServerOpen(true);
        return;
      } else if(next === "microsoft365") {
        if(!microsoftConnected || !microsoft) {
          const result = await api.startMicrosoft365();
          window.location.assign(result.authorization_url);
          return;
        }
        await api.saveCommunicationSetting("email",{
          mode:"internal",provider:"microsoft365",connection_id:microsoft.id,fields:{}
        });
      } else if(next === "infobip" && infobip) {
        await api.saveCommunicationSetting("email",{
          mode:"internal",provider:"infobip",connection_id:infobip.id,
          sender:email.sender??"",fields:{}
        });
      }
      setNotice(t("saved"));
      await load();
    } catch(error) {
      setNotice(errorMessage(error,t("requestFailed")));
    }
  }

  async function updateOtherChannel(row:ChannelSetting, mode:string) {
    try {
      if(mode === "external") {
        await api.saveCommunicationSetting(row.channel,{mode:"external",fields:{}});
      } else {
        if(!infobip) {
          setInfobipOpen(true);
          setNotice(t("internalRequiresInfobip"));
          return;
        }
        await api.saveCommunicationSetting(row.channel,{
          mode:"internal",provider:"infobip",connection_id:infobip.id,
          sender:row.sender??"",fields:{}
        });
      }
      setNotice(t("saved"));
      await load();
    } catch(error) {
      setNotice(errorMessage(error,t("requestFailed")));
    }
  }

  const otherChannels = settings.filter(row=>row.channel!=="email");

  return <>
    <section className="card">
      <h3>{t("emailConfiguration")}</h3>
      <p className="muted">{t("emailProviderHint")}</p>
      {notice&&<div className="notice">{notice}</div>}
      <div className="form">
        <div className="field">
          <label>{t("emailDeliveryProvider")}</label>
          <select className="select" value={emailProvider} onChange={e=>void saveEmailProvider(e.target.value)}>
            <option value="external">{t("emailExternalApp")}</option>
            <option value="platform">{t("zahlmeisterEmail")}</option>
            <option value="smtp_imap">{t("ownEmailAccount")}</option>
            <option value="microsoft365">{t("microsoft365")}</option>
            {emailProvider==="infobip"&&<option value="infobip">Infobip</option>}
          </select>
        </div>

        {emailProvider==="platform"&&<div className="notice">{t("zahlmeisterEmailHint")}</div>}
        {emailProvider==="smtp_imap"&&<div className="card">
          <div className="row between">
            <div><strong>{t("ownEmailAccount")}</strong><div className="muted">{t("smtpImapHint")}</div></div>
            <button className="button secondary" onClick={()=>setMailServerOpen(true)}>{t("edit")}</button>
          </div>
        </div>}
        {emailProvider==="microsoft365"&&<MicrosoftConnectionCard connection={microsoft} onChanged={load} onNotice={setNotice}/>} 
        {emailProvider==="infobip"&&infobip&&<div className="field"><label>{t("senderResource")}</label><input className="input" value={email?.sender??""} onChange={e=>setSettings(settings.map(row=>row.channel==="email"?{...row,sender:e.target.value}:row))} onBlur={async e=>{try{await api.saveCommunicationSetting("email",{mode:"internal",provider:"infobip",connection_id:infobip.id,sender:e.target.value,fields:{}});await load()}catch(error){setNotice(errorMessage(error,t("requestFailed")))}}}/></div>}

        {email?.mode==="internal"&&<div className="actions">
          <button className="button secondary" onClick={async()=>{try{const result=await api.testCommunicationChannel("email");setNotice(result.ok?t("connectionOk"):(result.error||t("connectionError")));await load()}catch(error){setNotice(errorMessage(error,t("connectionError")))}}}>{t("testConnection")}</button>
          <span className={`status-pill ${email.status}`}>{email.configured?integrationStatus(t,email.status):t("statusError")}</span>
        </div>}
      </div>
    </section>

    <section className="card">
      <div className="row between">
        <div><h3>{t("communication")}</h3><p className="muted">{t("communicationHint")}</p></div>
        <button className="button secondary" onClick={()=>setInfobipOpen(true)}>{infobip?t("infobipConnectionSettings"):t("connectInfobip")}</button>
      </div>
      <div className="table-wrap"><table className="table"><thead><tr><th>{t("channel")}</th><th>{t("delivery")}</th><th>{t("senderResource")}</th><th>{t("status")}</th><th>{t("actions")}</th></tr></thead><tbody>
        {otherChannels.map(row=><tr key={row.channel}>
          <td><strong>{channelLabel(t,row.channel)}</strong></td>
          <td><select className="select" value={row.mode} onChange={e=>void updateOtherChannel(row,e.target.value)}><option value="external">{t("external")}</option><option value="internal" disabled={!infobip}>{t("internal")}</option></select></td>
          <td>{row.mode==="internal"&&infobip?<input className="input" value={row.sender??""} placeholder={t("senderResource")} onChange={e=>setSettings(settings.map(item=>item.channel===row.channel?{...item,sender:e.target.value}:item))} onBlur={async e=>{try{await api.saveCommunicationSetting(row.channel,{mode:"internal",provider:"infobip",connection_id:infobip.id,sender:e.target.value,fields:{}});await load()}catch(error){setNotice(errorMessage(error,t("requestFailed")))}}}/>:"—"}</td>
          <td><span className={`status-pill ${row.status}`}>{row.configured?integrationStatus(t,row.status):t("statusError")}</span></td>
          <td>{row.mode==="internal"&&<button className="button secondary small" onClick={async()=>{try{const result=await api.testCommunicationChannel(row.channel);setNotice(result.ok?t("connectionOk"):(result.error||t("connectionError")));await load()}catch(error){setNotice(errorMessage(error,t("connectionError")))}}}>{t("testConnection")}</button>}</td>
        </tr>)}
      </tbody></table></div>
    </section>

    {mailServerOpen&&<MailServerModal setting={email} onClose={()=>setMailServerOpen(false)} onSaved={async()=>{setMailServerOpen(false);setNotice(t("saved"));await load()}}/>}
    {infobipOpen&&<InfobipModal connection={infobip} onClose={()=>setInfobipOpen(false)} onSaved={async()=>{setInfobipOpen(false);await load()}}/>}
  </>;
}

function MicrosoftConnectionCard({connection,onChanged,onNotice}:{connection:CommunicationConnection|null;onChanged:()=>Promise<void>;onNotice:(value:string)=>void}) {
  const {t}=useI18n();
  if(!connection || connection.status!=="connected") return <div className="card"><p className="muted">{t("microsoft365Hint")}</p><button className="button" onClick={async()=>{try{const result=await api.startMicrosoft365();window.location.assign(result.authorization_url)}catch(error){onNotice(errorMessage(error,t("microsoft365Unavailable")))}}}>{t("connectMicrosoft365")}</button></div>;
  return <div className="card"><div className="row between"><div><strong>{t("microsoft365")}</strong><div className="muted">{connection.account_label??""}</div></div><span className={`status-pill ${connection.status}`}>{integrationStatus(t,connection.status)}</span></div><div className="actions"><button className="button secondary" onClick={async()=>{try{const result=await api.testCommunicationConnection(connection.id);onNotice(result.ok?t("connectionOk"):(result.error||t("connectionError")));await onChanged()}catch(error){onNotice(errorMessage(error,t("connectionError")))}}}>{t("testConnection")}</button><button className="button secondary" onClick={async()=>{try{const result=await api.startMicrosoft365();window.location.assign(result.authorization_url)}catch(error){onNotice(errorMessage(error,t("microsoft365Unavailable")))}}}>{t("reconnect")}</button><button className="button danger" onClick={async()=>{await api.disconnectCommunicationConnection(connection.id);await onChanged()}}>{t("disconnect")}</button></div></div>;
}

function MailServerModal({setting,onClose,onSaved}:{setting:ChannelSetting|null;onClose:()=>void;onSaved:()=>void}) {
  const {t}=useI18n();
  const source = setting?.fields ?? {};
  const text=(key:string, fallback="")=>String(source[key]??fallback);
  const number=(key:string, fallback:number)=>Number(source[key]??fallback);
  const bool=(key:string, fallback:boolean)=>typeof source[key]==="boolean"?Boolean(source[key]):fallback;
  const [form,setForm]=useState<Record<string,string|number|boolean>>({
    from_address:text("from_address"),from_name:text("from_name","Zahlmeister"),
    smtp_host:text("smtp_host"),smtp_port:number("smtp_port",587),smtp_username:text("smtp_username"),smtp_password:"",
    smtp_starttls:bool("smtp_starttls",true),smtp_ssl:bool("smtp_ssl",false),
    imap_host:text("imap_host"),imap_port:number("imap_port",993),imap_username:text("imap_username"),imap_password:"",
    imap_ssl:bool("imap_ssl",true),imap_starttls:bool("imap_starttls",false),imap_folder:text("imap_folder","INBOX"),
  });
  const [notice,setNotice]=useState("");
  function set(key:string,value:string|number|boolean){setForm(current=>({...current,[key]:value}))}
  async function save(e:React.FormEvent){e.preventDefault();try{await api.saveCommunicationSetting("email",{mode:"internal",provider:"smtp_imap",fields:form});onSaved()}catch(error){setNotice(errorMessage(error,t("requestFailed")))}}
  return <Modal title={t("ownEmailAccount")} onClose={onClose}><form className="form" onSubmit={save}>{notice&&<div className="notice error">{notice}</div>}<h4>{t("outgoingMail")}</h4><div className="field"><label>{t("senderEmail")}</label><input className="input" type="email" required value={String(form.from_address)} onChange={e=>set("from_address",e.target.value)}/></div><div className="field"><label>{t("senderName")}</label><input className="input" value={String(form.from_name)} onChange={e=>set("from_name",e.target.value)}/></div><div className="split"><div className="field"><label>{t("smtpServer")}</label><input className="input" required value={String(form.smtp_host)} onChange={e=>set("smtp_host",e.target.value)}/></div><div className="field"><label>{t("port")}</label><input className="input" type="number" min={1} max={65535} value={Number(form.smtp_port)} onChange={e=>set("smtp_port",Number(e.target.value))}/></div></div><div className="field"><label>{t("username")}</label><input className="input" value={String(form.smtp_username)} onChange={e=>set("smtp_username",e.target.value)}/></div><div className="field"><label>{t("password")}</label><input className="input" type="password" value={String(form.smtp_password)} placeholder={source.smtp_password_configured?t("keepExistingPassword"):""} onChange={e=>set("smtp_password",e.target.value)}/></div><div className="actions"><label className="checkbox"><input type="checkbox" checked={Boolean(form.smtp_starttls)} onChange={e=>set("smtp_starttls",e.target.checked)}/>{t("startTls")}</label><label className="checkbox"><input type="checkbox" checked={Boolean(form.smtp_ssl)} onChange={e=>set("smtp_ssl",e.target.checked)}/>{t("sslTls")}</label></div><h4>{t("incomingMail")}</h4><p className="muted">{t("incomingMailOptionalHint")}</p><div className="split"><div className="field"><label>{t("imapServer")}</label><input className="input" value={String(form.imap_host)} onChange={e=>set("imap_host",e.target.value)}/></div><div className="field"><label>{t("port")}</label><input className="input" type="number" min={1} max={65535} value={Number(form.imap_port)} onChange={e=>set("imap_port",Number(e.target.value))}/></div></div><div className="field"><label>{t("username")}</label><input className="input" value={String(form.imap_username)} onChange={e=>set("imap_username",e.target.value)}/></div><div className="field"><label>{t("password")}</label><input className="input" type="password" value={String(form.imap_password)} placeholder={source.imap_password_configured?t("keepExistingPassword"):""} onChange={e=>set("imap_password",e.target.value)}/></div><div className="field"><label>{t("folder")}</label><input className="input" value={String(form.imap_folder)} onChange={e=>set("imap_folder",e.target.value)}/></div><div className="actions"><label className="checkbox"><input type="checkbox" checked={Boolean(form.imap_ssl)} onChange={e=>set("imap_ssl",e.target.checked)}/>{t("sslTls")}</label><label className="checkbox"><input type="checkbox" checked={Boolean(form.imap_starttls)} onChange={e=>set("imap_starttls",e.target.checked)}/>{t("startTls")}</label></div><button className="button">{t("save")}</button></form></Modal>;
}

function InfobipModal({connection,onClose,onSaved}:{connection:CommunicationConnection|null;onClose:()=>void;onSaved:()=>void}) {
  const {t}=useI18n();
  const [base,setBase]=useState(connection?.base_url??"https://api.infobip.com");
  const [label,setLabel]=useState(connection?.account_label??"");
  const [key,setKey]=useState("");
  const [notice,setNotice]=useState("");
  async function save(){try{if(connection){await api.updateCommunicationConnection(connection.id,{base_url:base,account_label:label})}else{await api.connectInfobip({base_url:base,api_key:key,account_label:label})}onSaved()}catch(error){setNotice(errorMessage(error,t("requestFailed")))}}
  async function oauth(){try{const result=await api.startInfobip();window.location.assign(result.authorization_url)}catch{setNotice(t("infobipOAuthUnavailable"))}}
  return <Modal title={t("infobipConnectionSettings")} onClose={onClose}><div className="form">{notice&&<div className="notice error">{notice}</div>}<div className="field"><label>{t("accountLabel")}</label><input className="input" value={label} onChange={e=>setLabel(e.target.value)}/></div><div className="field"><label>{t("infobipBaseUrl")}</label><input className="input" value={base} onChange={e=>setBase(e.target.value)}/></div>{!connection&&<div className="field"><label>{t("infobipApiKey")}</label><input type="password" className="input" value={key} onChange={e=>setKey(e.target.value)}/></div>}<div className="actions"><button className="button" onClick={save}>{t("save")}</button>{!connection&&<button className="button secondary" onClick={oauth}>{t("oauth20")}</button>}</div>{connection&&<><button className="button secondary" onClick={async()=>{const result=await api.testCommunicationConnection(connection.id);setNotice(result.ok?t("connectionOk"):(result.error||t("connectionError")))}}>{t("testConnection")}</button><button className="button danger" onClick={async()=>{await api.disconnectCommunicationConnection(connection.id);onSaved()}}>{t("disconnect")}</button></>}</div></Modal>;
}
