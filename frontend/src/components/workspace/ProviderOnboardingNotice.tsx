"use client";

import {useI18n} from "@/lib/i18n";

type Provider="infobip"|"mollie"|"ponto";

const registrationUrls:Record<Provider,string>={
  infobip:"https://www.infobip.com/en/signup",
  mollie:"https://my.mollie.com/dashboard/signup",
  ponto:"https://myponto.com/",
};

export function ProviderOnboardingNotice({provider}:{provider:Provider}){
  const {t}=useI18n();
  return <div className="provider-onboarding"><strong>{t(`${provider}OnboardingTitle`)}</strong><p className="muted">{t(`${provider}OnboardingHint`)}</p><a className="button secondary small" href={registrationUrls[provider]} target="_blank" rel="noreferrer">{t("registerWithProvider")}</a></div>
}
