type Messages = Record<string, string>;

/**
 * Terms of use (/terms) and the consent wording at registration.
 *
 * DRAFT — must be reviewed by legal counsel before go-live. Whenever the terms
 * change materially, update termsVersionDate here and TERMS_VERSION in
 * backend/app/core/legal.py together: every acceptance is stored with the
 * version the user agreed to. Languages without their own text fall back to
 * English.
 */
export const TERMS_SECTIONS = [
  "scope",
  "service",
  "account",
  "plans",
  "duties",
  "data",
  "availability",
  "liability",
  "termination",
  "changes",
  "law",
] as const;

export const legalMessages: Record<string, Messages> = {
  de: {
    portalNavTerms: "Nutzungsbedingungen",
    portalTermsIntro:
      "Diese Bedingungen regeln die Nutzung von Zahlmeister durch Organisatorinnen und Organisatoren von Sammelaktionen.",
    termsVersionLabel: "Stand",
    termsVersionDate: "29. September 2026",
    termsConsentPrefix: "Ich akzeptiere die",
    termsConsentTermsLink: "Nutzungsbedingungen",
    termsConsentMiddle: "und habe die",
    termsConsentPrivacyLink: "Datenschutzerklärung",
    termsConsentSuffix: "gelesen.",
    termsConsentRequired: "Bitte akzeptiere die Nutzungsbedingungen, um fortzufahren.",
    terms_scope_title: "1. Geltungsbereich",
    terms_scope_body:
      "Diese Nutzungsbedingungen gelten für die Nutzung der Plattform Zahlmeister der Solvate IT GmbH, Lagergasse 23, 8020 Graz, Österreich (im Folgenden „wir“). Sie gelten für alle Personen, die ein Zahlmeister-Konto anlegen und damit Sammelaktionen organisieren (im Folgenden „Organisator“).",
    terms_service_title: "2. Leistungen",
    terms_service_body:
      "Zahlmeister unterstützt Organisatoren dabei, Geldbeträge von einer Gruppe zu sammeln: Teilnehmerlisten führen, Zahlungsaufforderungen und Erinnerungen versenden sowie eingehende Zahlungen zuordnen. Zahlungen fließen direkt auf das Bankkonto oder das Mollie-Konto des Organisators. Wir verwahren keine Gelder und sind kein Zahlungsdienstleister.",
    terms_account_title: "3. Konto",
    terms_account_body:
      "Die Angaben bei der Registrierung müssen wahr und vollständig sein. Zugangsdaten sind geheim zu halten. Der Versand von Nachrichten setzt eine bestätigte E-Mail-Adresse voraus. Wir dürfen Konten sperren, die missbräuchlich verwendet werden.",
    terms_plans_title: "4. Tarife und Zahlung",
    terms_plans_body:
      "Die Basisversion ist kostenlos und in ihrem Umfang begrenzt. Zahlmeister Pro ist ein Jahresabonnement zum beim Kauf angezeigten Preis inklusive Umsatzsteuer; es verlängert sich um jeweils ein Jahr, sofern es nicht vor Ablauf gekündigt wird. Über einen App-Store abgeschlossene Abonnements unterliegen zusätzlich dessen Bedingungen und werden dort verwaltet.",
    terms_duties_title: "5. Pflichten des Organisators",
    terms_duties_body:
      "Der Organisator verwendet Zahlmeister nur für rechtmäßige Zwecke, verantwortet die Inhalte seiner Nachrichten und kontaktiert ausschließlich Personen, zu denen er berechtigt ist, etwa als Mitglieder, Eltern oder Teilnehmende. Werbung, unerwünschte Massennachrichten und irreführende Zahlungsaufforderungen sind untersagt.",
    terms_data_title: "6. Daten der Teilnehmenden",
    terms_data_body:
      "Für die Daten seiner Teilnehmenden ist der Organisator Verantwortlicher im Sinne der DSGVO; wir verarbeiten sie in seinem Auftrag und nur zur Erbringung der Leistungen. Einzelheiten zur Datenverarbeitung enthält die Datenschutzerklärung.",
    terms_availability_title: "7. Verfügbarkeit",
    terms_availability_body:
      "Wir bemühen uns um eine hohe Verfügbarkeit, schulden aber keine ununterbrochene Erreichbarkeit. Wartungsarbeiten kündigen wir nach Möglichkeit im Voraus an.",
    terms_liability_title: "8. Haftung",
    terms_liability_body:
      "Wir haften unbeschränkt für Vorsatz und grobe Fahrlässigkeit sowie für Personenschäden. Im Übrigen ist die Haftung, soweit gesetzlich zulässig, ausgeschlossen. Zwingende Rechte von Verbraucherinnen und Verbrauchern, insbesondere nach dem Konsumentenschutzgesetz, bleiben unberührt.",
    terms_termination_title: "9. Laufzeit und Kündigung",
    terms_termination_body:
      "Das Konto kann jederzeit in den Einstellungen gelöscht werden. Ein bezahltes Abonnement endet mit Ablauf des bezahlten Zeitraums. Rechnungsdaten bewahren wir so lange auf, wie es gesetzlich vorgeschrieben ist.",
    terms_changes_title: "10. Änderungen",
    terms_changes_body:
      "Wir können diese Bedingungen mit Wirkung für die Zukunft ändern. Über wesentliche Änderungen informieren wir rechtzeitig vorab; die weitere Nutzung setzt die Zustimmung zur neuen Fassung voraus.",
    terms_law_title: "11. Anwendbares Recht",
    terms_law_body:
      "Es gilt österreichisches Recht unter Ausschluss der Verweisungsnormen. Gerichtsstand für Unternehmer ist Graz. Für Verbraucherinnen und Verbraucher gelten die gesetzlichen Gerichtsstände.",
  },
  en: {
    portalNavTerms: "Terms of Use",
    portalTermsIntro:
      "These terms govern the use of Zahlmeister by the organizers of payment collections.",
    termsVersionLabel: "Version",
    termsVersionDate: "29 September 2026",
    termsConsentPrefix: "I accept the",
    termsConsentTermsLink: "Terms of Use",
    termsConsentMiddle: "and have read the",
    termsConsentPrivacyLink: "Privacy Policy",
    termsConsentSuffix: ".",
    termsConsentRequired: "Please accept the terms of use to continue.",
    terms_scope_title: "1. Scope",
    terms_scope_body:
      "These terms of use apply to the use of the Zahlmeister platform operated by Solvate IT GmbH, Lagergasse 23, 8020 Graz, Austria (“we”). They apply to everyone who creates a Zahlmeister account to organize payment collections (the “organizer”).",
    terms_service_title: "2. Services",
    terms_service_body:
      "Zahlmeister helps organizers collect money from a group: keeping participant lists, sending payment requests and reminders, and matching incoming payments. Payments go directly to the organizer’s bank account or Mollie account. We do not hold funds and are not a payment service provider.",
    terms_account_title: "3. Account",
    terms_account_body:
      "Registration details must be true and complete, and access credentials must be kept secret. Sending messages requires a verified email address. We may suspend accounts that are misused.",
    terms_plans_title: "4. Plans and payment",
    terms_plans_body:
      "The basic version is free of charge and limited in scope. Zahlmeister Pro is a yearly subscription at the price shown at purchase, VAT included; it renews for another year unless cancelled before it ends. Subscriptions bought through an app store are additionally subject to that store’s terms and are managed there.",
    terms_duties_title: "5. Organizer obligations",
    terms_duties_body:
      "Organizers use Zahlmeister for lawful purposes only, are responsible for the content of their messages and contact only people they are entitled to contact, such as members, parents or participants. Advertising, unsolicited bulk messages and misleading payment requests are prohibited.",
    terms_data_title: "6. Participant data",
    terms_data_body:
      "The organizer is the controller under the GDPR for the data of their participants; we process it on the organizer’s behalf and only to provide the services. The privacy policy describes the processing in detail.",
    terms_availability_title: "7. Availability",
    terms_availability_body:
      "We aim for high availability but do not guarantee uninterrupted access. Where possible, we announce maintenance in advance.",
    terms_liability_title: "8. Liability",
    terms_liability_body:
      "We are liable without limitation for intent and gross negligence and for personal injury. Otherwise, liability is excluded to the extent permitted by law. Mandatory consumer rights, in particular under the Austrian Consumer Protection Act, remain unaffected.",
    terms_termination_title: "9. Term and termination",
    terms_termination_body:
      "The account can be deleted at any time in the settings. A paid subscription ends when the paid period expires. We keep invoicing records for as long as the law requires.",
    terms_changes_title: "10. Changes",
    terms_changes_body:
      "We may change these terms with effect for the future. We announce material changes in good time; continued use requires agreement to the new version.",
    terms_law_title: "11. Governing law",
    terms_law_body:
      "Austrian law applies, excluding its conflict-of-law rules. The place of jurisdiction for businesses is Graz; consumers keep their statutory places of jurisdiction.",
  },
};
