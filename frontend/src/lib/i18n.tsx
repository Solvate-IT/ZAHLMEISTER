"use client";

import {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
import de from "@/locales/de.json";
import en from "@/locales/en.json";
import {adminMessages} from "@/locales/admin";
import {billingMessages} from "@/locales/billing";
import {billingProfileMessages} from "@/locales/billingProfile";
import {integrationMessages} from "@/locales/integrations";
import {settingsMessages} from "@/locales/settings";

type Messages = Record<string, string>;
type Params = Record<string, string | number>;

const supported = ["bg","cs","da","de","el","en","es","et","fi","fr","ga","hr","hu","it","lt","lv","mt","nl","pl","pt","ro","sk","sl","sv"] as const;
const loaders: Record<string, () => Promise<{default: Messages}>> = {
  bg: () => import("@/locales/bg.json"), cs: () => import("@/locales/cs.json"),
  da: () => import("@/locales/da.json"), el: () => import("@/locales/el.json"),
  es: () => import("@/locales/es.json"), et: () => import("@/locales/et.json"),
  fi: () => import("@/locales/fi.json"), fr: () => import("@/locales/fr.json"),
  ga: () => import("@/locales/ga.json"), hr: () => import("@/locales/hr.json"),
  hu: () => import("@/locales/hu.json"), it: () => import("@/locales/it.json"),
  lt: () => import("@/locales/lt.json"), lv: () => import("@/locales/lv.json"),
  mt: () => import("@/locales/mt.json"), nl: () => import("@/locales/nl.json"),
  pl: () => import("@/locales/pl.json"), pt: () => import("@/locales/pt.json"),
  ro: () => import("@/locales/ro.json"), sk: () => import("@/locales/sk.json"), sl: () => import("@/locales/sl.json"), sv: () => import("@/locales/sv.json"),
};

interface I18nValue {
  locale: string;
  setLocale: (locale: string) => void;
  t: (key: string, params?: Params) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function normalizeLocale(value: string | null | undefined): string {
  const language = (value || "de").toLowerCase().split(/[-_]/)[0];
  return supported.includes(language as (typeof supported)[number]) ? language : "de";
}

export function I18nProvider({children}: {children: React.ReactNode}) {
  const [locale, setLocaleState] = useState("de");
  const [messages, setMessages] = useState<Messages>(de);

  useEffect(() => {
    const stored = typeof window !== "undefined" ? window.localStorage.getItem("zahlmeister_locale") : null;
    const next = normalizeLocale(stored || (typeof navigator !== "undefined" ? navigator.language : "de"));
    setLocaleState(next);
  }, []);

  useEffect(() => {
    if (locale === "de") { setMessages(de); return; }
    if (locale === "en") { setMessages(en); return; }
    const load = loaders[locale];
    if (!load) { setMessages(de); return; }
    let active = true;
    load().then(module => { if (active) setMessages(module.default); }).catch(() => { if (active) setMessages(de); });
    return () => { active = false; };
  }, [locale]);

  const setLocale = useCallback((value: string) => {
    const normalized = normalizeLocale(value);
    if (typeof window !== "undefined") window.localStorage.setItem("zahlmeister_locale", normalized);
    setLocaleState(normalized);
  }, []);

  const t = useCallback((key: string, params: Params = {}) => {
    const billingForLocale = billingMessages[locale] ?? billingMessages.en;
    const billingProfileForLocale = billingProfileMessages[locale] ?? billingProfileMessages.en;
    const adminForLocale = adminMessages[locale] ?? adminMessages.en;
    const integrationsForLocale = integrationMessages[locale] ?? integrationMessages.en;
    const settingsForLocale = settingsMessages[locale] ?? settingsMessages.en;
    const fallback = billingProfileForLocale[key]
      ?? billingProfileMessages.en[key]
      ?? billingForLocale[key]
      ?? billingMessages.en[key]
      ?? settingsForLocale[key]
      ?? settingsMessages.en[key]
      ?? integrationsForLocale[key]
      ?? integrationMessages.en[key]
      ?? adminForLocale[key]
      ?? adminMessages.en[key]
      ?? (de as Messages)[key]
      ?? (en as Messages)[key]
      ?? key;
    let value = billingProfileForLocale[key] ?? billingForLocale[key] ?? settingsForLocale[key] ?? messages[key] ?? fallback;
    for (const [name, replacement] of Object.entries(params)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
    return value;
  }, [messages, locale]);

  const value = useMemo(() => ({locale, setLocale, t}), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider missing");
  return value;
}

export const supportedLocales = supported;