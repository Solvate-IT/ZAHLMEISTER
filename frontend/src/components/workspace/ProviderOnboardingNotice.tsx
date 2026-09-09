"use client";

import {useI18n} from "@/lib/i18n";

type Provider="infobip"|"mollie"|"ponto";

const registrationUrls:Partial<Record<Provider,string>>={
  infobip:"https://www.infobip.com/en/signup",
  mollie:"https://my.mollie.com/dashboard/signup",
};

export function ProviderOnboardingNotice({provider}:{provider:Provider}){
  const {t}=useI18n();const registrationUrl=registrationUrls[provider];
  return <div className="provider-onboarding"><strong>{t(`${provider}OnboardingTitle`)}</strong><p className="muted">{t(`${provider}OnboardingHint`)}</p>{registrationUrl&&<a className="button secondary small" href={registrationUrl} target="_blank" rel="noreferrer">{t("registerWithProvider")}</a>}</div>
}
