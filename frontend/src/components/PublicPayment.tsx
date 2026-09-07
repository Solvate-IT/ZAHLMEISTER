"use client";

import {useCallback, useEffect, useState} from "react";
import {useSearchParams} from "next/navigation";
import {api, ApiError} from "@/lib/api";
import type {PublicPayment} from "@/lib/types";
import {Capacitor} from "@capacitor/core";
import {useI18n} from "@/lib/i18n";
import {Brand} from "./Brand";
import {Loading} from "./State";

export function PublicPaymentPage() {
  const {t, locale} = useI18n();
  const params = useSearchParams();
  const token = params.get("token")?.trim() ?? "";
  const [payment, setPayment] = useState<PublicPayment | null>(null);
  const [error, setError] = useState(false);
  const [onlineBusy, setOnlineBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!token) {
      setError(true);
      return;
    }
    try {
      const value = await api.publicPayment(token);
      setPayment(value);
      setError(false);
    } catch {
      setError(true);
    }
  }, [token]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const onFocus = () => { void load(); };
    const onVisibility = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  async function payOnline() {
    if (!token || onlineBusy) return;
    setOnlineBusy(true);
    try {
      const checkout = await api.startOnlinePayment(token);
      const isNative = Capacitor.isNativePlatform();
      if (isNative) {
        const {Browser} = await import("@capacitor/browser");
        await Browser.open({url: checkout.checkout_url});
      } else {
        const opened = window.open(checkout.checkout_url, "_blank", "noopener,noreferrer");
        if (!opened) window.location.assign(checkout.checkout_url);
      }
    } catch (reason) {
      const message = reason instanceof ApiError && reason.status === 409 ? t("paymentReceived") : t("checkoutFailed");
      window.alert(message);
      await load();
    } finally {
      setOnlineBusy(false);
    }
  }

  return <div className="page-bg">
    <header className="topbar"><Brand compact/></header>
    <main className="payment-layout">
      {error ? <div className="card state"><strong>{t("paymentLinkInvalid")}</strong></div> : !payment ? <Loading/> : <PaymentBody payment={payment} qrUrl={api.publicPaymentQr(token)} onCopy={copy} onOnline={payOnline} onlineBusy={onlineBusy} locale={locale}/>} 
      {copied && <div className="toast" role="status">{t("copied")}</div>}
    </main>
  </div>;
}

function PaymentBody({payment, qrUrl, onCopy, onOnline, onlineBusy, locale}: {
  payment: PublicPayment;
  qrUrl: string;
  onCopy: (value: string) => Promise<void>;
  onOnline: () => Promise<void>;
  onlineBusy: boolean;
  locale: string;
}) {
  const {t} = useI18n();
  const amount = typeof payment.amount === "number" ? payment.amount : Number(payment.amount);
  const money = Number.isFinite(amount)
    ? new Intl.NumberFormat(locale, {style: "currency", currency: payment.currency}).format(amount)
    : `${payment.amount} ${payment.currency}`;
  const paid = payment.status === "paid";
  const bankAvailable = Boolean(payment.account_name && payment.iban);

  return <div className="stack">
    <div>
      <h1 style={{marginBottom: 6}}>{payment.collection_name}</h1>
      <div className="muted">{payment.participant_name}</div>
    </div>
    <div className="payment-amount">{money}</div>
    {paid ? <div className="notice success">{t("paymentReceived")}</div> : <>
      {payment.online_payment_available && <div className="stack">
        <button className="button" disabled={onlineBusy} onClick={() => void onOnline()}>{onlineBusy ? t("loading") : t("payOnline")}</button>
        <small className="muted" style={{textAlign: "center"}}>{t("onlineCheckoutHint")}</small>
      </div>}
      {payment.online_payment_available && bankAvailable && <div className="payment-divider"><span>{t("orBankTransfer")}</span></div>}
      {bankAvailable && <>
        {payment.epc_qr_data && <div className="stack"><img className="qr" src={qrUrl} alt={t("paymentQrCode")}/><small className="muted" style={{textAlign: "center"}}>{t("scanWithBankApp")}</small></div>}
        <div className="card">
          <CopyRow label={t("accountHolder")} value={payment.account_name!} onCopy={onCopy}/>
          <CopyRow label={t("iban")} value={payment.iban!} onCopy={onCopy}/>
          {payment.bic && <CopyRow label={t("bic")} value={payment.bic} onCopy={onCopy}/>} 
          <CopyRow label={t("paymentReference")} value={payment.payment_reference} onCopy={onCopy}/>
        </div>
      </>}
    </>}
  </div>;
}

function CopyRow({label, value, onCopy}: {label: string; value: string; onCopy: (value: string) => Promise<void>}) {
  const {t} = useI18n();
  return <div className="copy-row"><strong>{label}</strong><span className="code-inline">{value}</span><button className="button small secondary" type="button" onClick={() => void onCopy(value)}>{t("copy")}</button></div>;
}
