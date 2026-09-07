"use client";

import Link from "next/link";
import {Brand} from "./Brand";
import {LocaleSelect} from "./LocaleSelect";
import {useI18n} from "@/lib/i18n";

type LegalKind = "imprint" | "privacy";

const company = {
  address: "Lagergasse 23, 8020 Graz, Austria",
  register: "FN 565826y",
  court: "Landesgericht für ZRS Graz",
  vat: "ATU77378124",
  managingDirector: "Ing. Dipl.-Ing. Christian Fast, Bakk.rer.soc.oec.",
  email: "Support@Solvate.at",
  phone: "+43 699 17658283",
  web: "www.solvate.at",
  chamber: "Wirtschaftskammer Steiermark · WKO 5235155",
  profession: "Fachgruppe Unternehmensberatung und Informationstechnologie · IT-Dienstleister",
  authority: "Magistrat der Stadt Graz · GISA 36952014",
};

export function PublicLegalPage({kind}: {kind: LegalKind}) {
  const {t} = useI18n();
  const imprint = kind === "imprint";
  return <div className="page-bg premium-page legal-page">
    <header className="topbar premium-topbar">
      <Link href="/" className="brand-link"><Brand/></Link>
      <div className="top-actions portal-account-actions"><LocaleSelect/><Link className="button secondary" href="/?auth=login">{t("login")}</Link><Link className="button" href="/?auth=register">{t("register")}</Link></div>
    </header>
    <main className="container legal-container">
      <section className="legal-hero"><span className="eyebrow">{t(imprint ? "portalNavImprint" : "portalNavPrivacy")}</span><h1>{t(imprint ? "portalNavImprint" : "portalNavPrivacy")}</h1><p>{t(imprint ? "portalImprintIntro" : "portalPrivacyIntro")}</p></section>
      {imprint ? <Imprint/> : <Privacy/>}
    </main>
    <footer className="footer premium-footer"><div className="container footer-row"><span>© {new Date().getFullYear()} {t("portalCompanyName")}</span><div className="footer-links"><Link className="button ghost" href="/">{t("appName")}</Link><Link className="button ghost" href="/imprint/">{t("portalNavImprint")}</Link><Link className="button ghost" href="/privacy/">{t("portalNavPrivacy")}</Link></div></div></footer>
  </div>;
}

function Imprint() {
  const {t} = useI18n();
  const rows: [string,string][] = [
    [t("portalAddress"), company.address],
    [t("portalCompanyRegister"), company.register],
    [t("portalRegisterCourt"), company.court],
    [t("portalVatId"), company.vat],
    [t("portalManagingDirector"), company.managingDirector],
    [t("portalBusinessPurpose"), t("portalBusinessPurposeValue")],
    [t("email"), company.email],
    [t("phone"), company.phone],
  ];
  return <section className="legal-content"><div className="card legal-card"><h2>{t("portalCompanyName")}</h2><dl className="legal-details">{rows.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><div className="legal-official"><p>{company.web}</p><p>{company.chamber}</p><p>{company.profession}</p><p>{company.authority}</p></div></div></section>;
}

function Privacy() {
  const {t} = useI18n();
  return <section className="legal-content legal-grid"><div className="card legal-card"><h2>{t("portalPrivacyControllerTitle")}</h2><p><strong>{t("portalCompanyName")}</strong><br/>{company.address}<br/><a href={`mailto:${company.email}`}>{company.email}</a></p></div><div className="card legal-card"><h2>{t("portalPrivacyDataTitle")}</h2><p>{t("portalPrivacyDataBody")}</p></div><div className="card legal-card"><h2>{t("portalPrivacyRightsTitle")}</h2><p>{t("portalPrivacyRightsBody")}</p><p>Österreichische Datenschutzbehörde · Barichgasse 40–42 · 1030 Wien · dsb.gv.at</p></div></section>;
}
