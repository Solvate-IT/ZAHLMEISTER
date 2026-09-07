"use client";

import {useRef} from "react";
import {supportedLocales, useI18n} from "@/lib/i18n";

function languageLabel(code: string): string {
  let label = code.toUpperCase();
  try {
    label = new Intl.DisplayNames([code], {type: "language"}).of(code) ?? label;
  } catch {}
  return label ? label.charAt(0).toLocaleUpperCase(code) + label.slice(1) : code.toUpperCase();
}

export function LocaleSelect({className="locale-menu"}:{className?:string}) {
  const {t, locale, setLocale} = useI18n();
  const details = useRef<HTMLDetailsElement>(null);
  return <details className={className} ref={details}>
    <summary className="locale-trigger" aria-label={t("language")} title={languageLabel(locale)}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9"/>
        <path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9S14.4 18.5 12 21M12 3C9.6 5.5 8.4 8.5 8.4 12S9.6 18.5 12 21"/>
      </svg>
    </summary>
    <div className="locale-options" role="menu">
      {supportedLocales.map(code => <button
        type="button"
        role="menuitemradio"
        aria-checked={code===locale}
        className={code===locale?"active":""}
        key={code}
        onClick={()=>{setLocale(code);details.current?.removeAttribute("open")}}
      >{languageLabel(code)}</button>)}
    </div>
  </details>;
}
