from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BillingInvoiceCopy:
    line_description: str
    email_subject: str
    email_body: str
    reverse_charge_memo: str


_COPIES: dict[str, BillingInvoiceCopy] = {
    "bg": BillingInvoiceCopy("Zahlmeister Pro – 12 месеца", "Вашата фактура за Zahlmeister Pro", "Благодарим Ви. Вашата фактура за Zahlmeister Pro е приложена.", "Обратно начисляване – данъчното задължение се прехвърля на получателя."),
    "cs": BillingInvoiceCopy("Zahlmeister Pro – 12 měsíců", "Vaše faktura za Zahlmeister Pro", "Děkujeme. Vaše faktura za Zahlmeister Pro je přiložena.", "Přenesení daňové povinnosti – daň odvádí příjemce."),
    "da": BillingInvoiceCopy("Zahlmeister Pro – 12 måneder", "Din faktura for Zahlmeister Pro", "Tak. Din faktura for Zahlmeister Pro er vedhæftet.", "Omvendt betalingspligt – afgiftspligten overgår til modtageren."),
    "de": BillingInvoiceCopy("Zahlmeister Pro – 12 Monate", "Ihre Zahlmeister Pro Rechnung", "Vielen Dank. Im Anhang finden Sie Ihre Zahlmeister Pro Rechnung.", "Reverse Charge – die Steuerschuld geht auf den Leistungsempfänger über."),
    "el": BillingInvoiceCopy("Zahlmeister Pro – 12 μήνες", "Το τιμολόγιό σας για το Zahlmeister Pro", "Ευχαριστούμε. Επισυνάπτεται το τιμολόγιό σας για το Zahlmeister Pro.", "Αντίστροφη χρέωση – η φορολογική υποχρέωση μεταφέρεται στον λήπτη."),
    "en": BillingInvoiceCopy("Zahlmeister Pro – 12 months", "Your Zahlmeister Pro invoice", "Thank you. Your Zahlmeister Pro invoice is attached.", "Reverse charge – tax liability transfers to the recipient."),
    "es": BillingInvoiceCopy("Zahlmeister Pro – 12 meses", "Su factura de Zahlmeister Pro", "Gracias. Se adjunta su factura de Zahlmeister Pro.", "Inversión del sujeto pasivo – la obligación tributaria se transfiere al destinatario."),
    "et": BillingInvoiceCopy("Zahlmeister Pro – 12 kuud", "Teie Zahlmeister Pro arve", "Täname. Teie Zahlmeister Pro arve on lisatud.", "Pöördmaksustamine – maksukohustus läheb üle saajale."),
    "fi": BillingInvoiceCopy("Zahlmeister Pro – 12 kuukautta", "Zahlmeister Pro -laskusi", "Kiitos. Zahlmeister Pro -laskusi on liitteenä.", "Käännetty verovelvollisuus – verovelvollisuus siirtyy vastaanottajalle."),
    "fr": BillingInvoiceCopy("Zahlmeister Pro – 12 mois", "Votre facture Zahlmeister Pro", "Merci. Votre facture Zahlmeister Pro est jointe.", "Autoliquidation – la dette fiscale est transférée au destinataire."),
    "ga": BillingInvoiceCopy("Zahlmeister Pro – 12 mhí", "Do shonrasc Zahlmeister Pro", "Go raibh maith agat. Tá do shonrasc Zahlmeister Pro ceangailte.", "Frithmhuirear – aistrítear an dliteanas cánach chuig an bhfaighteoir."),
    "hr": BillingInvoiceCopy("Zahlmeister Pro – 12 mjeseci", "Vaš račun za Zahlmeister Pro", "Hvala. Vaš račun za Zahlmeister Pro nalazi se u privitku.", "Prijenos porezne obveze – porezna obveza prenosi se na primatelja."),
    "hu": BillingInvoiceCopy("Zahlmeister Pro – 12 hónap", "Zahlmeister Pro számlája", "Köszönjük. Zahlmeister Pro számláját csatoltuk.", "Fordított adózás – az adófizetési kötelezettség a vevőre száll át."),
    "it": BillingInvoiceCopy("Zahlmeister Pro – 12 mesi", "La sua fattura Zahlmeister Pro", "Grazie. In allegato trova la sua fattura Zahlmeister Pro.", "Inversione contabile – l'obbligo fiscale è trasferito al destinatario."),
    "lt": BillingInvoiceCopy("Zahlmeister Pro – 12 mėnesių", "Jūsų Zahlmeister Pro sąskaita", "Dėkojame. Jūsų Zahlmeister Pro sąskaita pridėta.", "Atvirkštinis apmokestinimas – mokestinė prievolė perkeliama gavėjui."),
    "lv": BillingInvoiceCopy("Zahlmeister Pro – 12 mēneši", "Jūsu Zahlmeister Pro rēķins", "Paldies. Jūsu Zahlmeister Pro rēķins ir pievienots.", "Apgrieztā PVN maksāšana – nodokļa saistības pāriet saņēmējam."),
    "mt": BillingInvoiceCopy("Zahlmeister Pro – 12-il xahar", "Il-fattura tiegħek ta' Zahlmeister Pro", "Grazzi. Il-fattura tiegħek ta' Zahlmeister Pro hija mehmuża.", "Reverse charge – l-obbligu tat-taxxa jgħaddi għand ir-riċevitur."),
    "nl": BillingInvoiceCopy("Zahlmeister Pro – 12 maanden", "Uw factuur voor Zahlmeister Pro", "Dank u. Uw factuur voor Zahlmeister Pro is bijgevoegd.", "Btw verlegd – de belastingplicht gaat over op de afnemer."),
    "pl": BillingInvoiceCopy("Zahlmeister Pro – 12 miesięcy", "Faktura za Zahlmeister Pro", "Dziękujemy. Faktura za Zahlmeister Pro znajduje się w załączniku.", "Odwrotne obciążenie – obowiązek podatkowy przechodzi na odbiorcę."),
    "pt": BillingInvoiceCopy("Zahlmeister Pro – 12 meses", "A sua fatura Zahlmeister Pro", "Obrigado. A sua fatura Zahlmeister Pro segue em anexo.", "Autoliquidação – a obrigação fiscal é transferida para o destinatário."),
    "ro": BillingInvoiceCopy("Zahlmeister Pro – 12 luni", "Factura dvs. Zahlmeister Pro", "Vă mulțumim. Factura dvs. Zahlmeister Pro este atașată.", "Taxare inversă – obligația fiscală se transferă beneficiarului."),
    "sk": BillingInvoiceCopy("Zahlmeister Pro – 12 mesiacov", "Vaša faktúra za Zahlmeister Pro", "Ďakujeme. Vaša faktúra za Zahlmeister Pro je v prílohe.", "Prenesenie daňovej povinnosti – daňová povinnosť prechádza na príjemcu."),
    "sl": BillingInvoiceCopy("Zahlmeister Pro – 12 mesecev", "Vaš račun za Zahlmeister Pro", "Hvala. Vaš račun za Zahlmeister Pro je priložen.", "Obrnjena davčna obveznost – davčna obveznost se prenese na prejemnika."),
    "sv": BillingInvoiceCopy("Zahlmeister Pro – 12 månader", "Din faktura för Zahlmeister Pro", "Tack. Din faktura för Zahlmeister Pro finns bifogad.", "Omvänd skattskyldighet – skattskyldigheten övergår till mottagaren."),
}


def billing_invoice_copy(locale: str) -> BillingInvoiceCopy:
    language = (locale or "en").replace("_", "-").split("-", 1)[0].lower()
    return _COPIES.get(language, _COPIES["en"])
