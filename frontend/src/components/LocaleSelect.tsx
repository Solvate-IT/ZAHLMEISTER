"use client";

import {supportedLocales, useI18n} from "@/lib/i18n";

export function LocaleSelect({className="select locale-select"}:{className?:string}) {
  const {t, locale, setLocale} = useI18n();
  return <select className={className} value={locale} onChange={event => setLocale(event.target.value)} aria-label={t("language")}>
    {supportedLocales.map(code => {
      let label = code.toUpperCase();
      try { label = new Intl.DisplayNames([code], {type:"language"}).of(code) ?? label; } catch {}
      return <option key={code} value={code}>{label}</option>;
    })}
  </select>;
}
