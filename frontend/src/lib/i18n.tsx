"use client";

import {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
import de from "@/locales/de.json";
import en from "@/locales/en.json";
import {adminMessages} from "@/locales/admin";
import {billingMessages} from "@/locales/billing";
import {billingProfileMessages} from "@/locales/billingProfile";
import {integrationMessages} from "@/locales/integrations";
import {legalMessages} from "@/locales/legal";
import {settingsMessages} from "@/locales/settings";
import {storeBillingMessages} from "@/locales/storeBilling";
import {uxMessages} from "@/locales/ux";

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

function catalogValue(key:string,catalogs:Array<Messages|undefined>):string|undefined {
  for(const catalog of catalogs){
    const value=catalog?.[key];
    if(value!==undefined)return value;
  }
  return undefined;
}

export function I18nProvider({children}: {children: React.ReactNode}) {
  const [locale, setLocaleState] = useState("de");
  const [loaded, setLoaded] = useState<{locale:string;messages:Messages}>({locale:"de",messages:de});

  useEffect(() => {
    const stored = typeof window !== "undefined" ? window.localStorage.getItem("zahlmeister_locale") : null;
    const next = normalizeLocale(stored || (typeof navigator !== "undefined" ? navigator.language : "de"));
    setLocaleState(next);
  }, []);

  useEffect(() => {
    if (locale === "de") { setLoaded({locale,messages:de}); return; }
    if (locale === "en") { setLoaded({locale,messages:en}); return; }
    const load = loaders[locale];
    if (!load) { setLoaded({locale,messages:{}}); return; }
    let active = true;
    load().then(module => { if (active) setLoaded({locale,messages:module.default}); }).catch(() => { if (active) setLoaded({locale,messages:{}}); });
    return () => { active = false; };
  }, [locale]);

  const setLocale = useCallback((value: string) => {
    const normalized = normalizeLocale(value);
    if (typeof window !== "undefined") window.localStorage.setItem("zahlmeister_locale", normalized);
    setLocaleState(normalized);
  }, []);

  const t = useCallback((key: string, params: Params = {}) => {
    const localeMessages=loaded.locale===locale?loaded.messages:undefined;
    // Exhaust translations for the selected language before falling back to
    // English. This prevents an English module fallback from hiding a
    // translation that already exists in another locale catalog.
    const localizedCatalogs:Array<Messages|undefined>=[
      uxMessages[locale],
      legalMessages[locale],
      storeBillingMessages[locale],
      billingProfileMessages[locale],
      billingMessages[locale],
      settingsMessages[locale],
      integrationMessages[locale],
      adminMessages[locale],
      localeMessages,
    ];
    const fallbackCatalogs:Array<Messages|undefined>=[
      uxMessages.en,
      legalMessages.en,
      storeBillingMessages.en,
      billingProfileMessages.en,
      billingMessages.en,
      settingsMessages.en,
      integrationMessages.en,
      adminMessages.en,
      en as Messages,
      de as Messages,
    ];
    let value=catalogValue(key,localizedCatalogs)??catalogValue(key,fallbackCatalogs)??key;
    for (const [name, replacement] of Object.entries(params)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
    return value;
  }, [loaded, locale]);

  useEffect(()=>{
    if(typeof document==="undefined")return;
    document.documentElement.lang=locale;
    document.title=`${t("appName")} – ${t("headline")}`;
    document.querySelector('meta[name="description"]')?.setAttribute("content",t("subtitle"));
  },[locale,t]);

  const value = useMemo(() => ({locale, setLocale, t}), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider missing");
  return value;
}

export const supportedLocales = supported;
