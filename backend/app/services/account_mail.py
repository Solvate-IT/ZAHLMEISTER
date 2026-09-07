from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountMailCopy:
    verify_subject: str
    verify_intro: str
    verify_ignore: str
    reset_subject: str
    reset_intro: str
    reset_validity: str


_COPY: dict[str, AccountMailCopy] = {
    "bg": AccountMailCopy("Zahlmeister - Потвърдете имейл адреса", "Потвърдете имейл адреса си за Zahlmeister:", "Ако не сте се регистрирали, можете да игнорирате това съобщение.", "Zahlmeister - Нулиране на парола", "Използвайте този линк, за да нулирате паролата си за Zahlmeister:", "Линкът е валиден 60 минути."),
    "cs": AccountMailCopy("Zahlmeister - Potvrďte e-mailovou adresu", "Potvrďte svou e-mailovou adresu pro Zahlmeister:", "Pokud jste se neregistrovali, můžete tuto zprávu ignorovat.", "Zahlmeister - Obnovení hesla", "Pomocí tohoto odkazu obnovíte heslo k Zahlmeisteru:", "Odkaz platí 60 minut."),
    "da": AccountMailCopy("Zahlmeister - Bekræft e-mailadresse", "Bekræft din e-mailadresse til Zahlmeister:", "Hvis du ikke har registreret dig, kan du ignorere denne besked.", "Zahlmeister - Nulstil adgangskode", "Brug dette link til at nulstille din adgangskode til Zahlmeister:", "Linket er gyldigt i 60 minutter."),
    "de": AccountMailCopy("Zahlmeister - E-Mail-Adresse bestätigen", "Bitte bestätige deine E-Mail-Adresse für Zahlmeister:", "Falls du dich nicht registriert hast, kannst du diese Nachricht ignorieren.", "Zahlmeister - Passwort zurücksetzen", "Über diesen Link kannst du dein Zahlmeister-Passwort zurücksetzen:", "Der Link ist 60 Minuten gültig."),
    "el": AccountMailCopy("Zahlmeister - Επιβεβαίωση διεύθυνσης email", "Επιβεβαιώστε τη διεύθυνση email σας για το Zahlmeister:", "Αν δεν εγγραφήκατε, μπορείτε να αγνοήσετε αυτό το μήνυμα.", "Zahlmeister - Επαναφορά κωδικού", "Χρησιμοποιήστε αυτόν τον σύνδεσμο για να επαναφέρετε τον κωδικό Zahlmeister:", "Ο σύνδεσμος ισχύει για 60 λεπτά."),
    "en": AccountMailCopy("Zahlmeister - Confirm your email address", "Please confirm your email address for Zahlmeister:", "If you did not register, you can ignore this message.", "Zahlmeister - Reset your password", "Use this link to reset your Zahlmeister password:", "The link is valid for 60 minutes."),
    "es": AccountMailCopy("Zahlmeister - Confirma tu correo electrónico", "Confirma tu dirección de correo para Zahlmeister:", "Si no te registraste, puedes ignorar este mensaje.", "Zahlmeister - Restablecer contraseña", "Usa este enlace para restablecer tu contraseña de Zahlmeister:", "El enlace es válido durante 60 minutos."),
    "et": AccountMailCopy("Zahlmeister - Kinnita e-posti aadress", "Kinnita oma Zahlmeisteri e-posti aadress:", "Kui sa ei registreerunud, võid seda sõnumit eirata.", "Zahlmeister - Lähtesta parool", "Kasuta seda linki Zahlmeisteri parooli lähtestamiseks:", "Link kehtib 60 minutit."),
    "fi": AccountMailCopy("Zahlmeister - Vahvista sähköpostiosoite", "Vahvista Zahlmeisterin sähköpostiosoitteesi:", "Jos et rekisteröitynyt, voit jättää tämän viestin huomiotta.", "Zahlmeister - Palauta salasana", "Palauta Zahlmeister-salasanasi tämän linkin kautta:", "Linkki on voimassa 60 minuuttia."),
    "fr": AccountMailCopy("Zahlmeister - Confirmez votre adresse e-mail", "Confirmez votre adresse e-mail pour Zahlmeister :", "Si vous ne vous êtes pas inscrit, vous pouvez ignorer ce message.", "Zahlmeister - Réinitialiser le mot de passe", "Utilisez ce lien pour réinitialiser votre mot de passe Zahlmeister :", "Le lien est valable 60 minutes."),
    "ga": AccountMailCopy("Zahlmeister - Deimhnigh do sheoladh ríomhphoist", "Deimhnigh do sheoladh ríomhphoist do Zahlmeister:", "Murar chláraigh tú, is féidir leat neamhaird a dhéanamh den teachtaireacht seo.", "Zahlmeister - Athshocraigh do phasfhocal", "Úsáid an nasc seo chun do phasfhocal Zahlmeister a athshocrú:", "Tá an nasc bailí ar feadh 60 nóiméad."),
    "hr": AccountMailCopy("Zahlmeister - Potvrdite adresu e-pošte", "Potvrdite svoju adresu e-pošte za Zahlmeister:", "Ako se niste registrirali, možete zanemariti ovu poruku.", "Zahlmeister - Poništavanje lozinke", "Ovim linkom možete poništiti lozinku za Zahlmeister:", "Link vrijedi 60 minuta."),
    "hu": AccountMailCopy("Zahlmeister - E-mail-cím megerősítése", "Erősítsd meg a Zahlmeisterhez tartozó e-mail-címedet:", "Ha nem te regisztráltál, hagyd figyelmen kívül ezt az üzenetet.", "Zahlmeister - Jelszó visszaállítása", "Ezen a linken visszaállíthatod a Zahlmeister-jelszavadat:", "A link 60 percig érvényes."),
    "it": AccountMailCopy("Zahlmeister - Conferma il tuo indirizzo e-mail", "Conferma il tuo indirizzo e-mail per Zahlmeister:", "Se non ti sei registrato, puoi ignorare questo messaggio.", "Zahlmeister - Reimposta la password", "Usa questo link per reimpostare la password di Zahlmeister:", "Il link è valido per 60 minuti."),
    "lt": AccountMailCopy("Zahlmeister - Patvirtinkite el. pašto adresą", "Patvirtinkite savo Zahlmeister el. pašto adresą:", "Jei nesiregistravote, galite ignoruoti šį pranešimą.", "Zahlmeister - Atkurti slaptažodį", "Naudokite šią nuorodą Zahlmeister slaptažodžiui atkurti:", "Nuoroda galioja 60 minučių."),
    "lv": AccountMailCopy("Zahlmeister - Apstipriniet e-pasta adresi", "Apstipriniet savu Zahlmeister e-pasta adresi:", "Ja nereģistrējāties, varat ignorēt šo ziņojumu.", "Zahlmeister - Atiestatīt paroli", "Izmantojiet šo saiti, lai atiestatītu Zahlmeister paroli:", "Saite ir derīga 60 minūtes."),
    "mt": AccountMailCopy("Zahlmeister - Ikkonferma l-indirizz tal-email", "Ikkonferma l-indirizz tal-email tiegħek għal Zahlmeister:", "Jekk ma rreġistrajtx, tista’ tinjora dan il-messaġġ.", "Zahlmeister - Irrisettja l-password", "Uża din il-link biex tirrisettja l-password ta’ Zahlmeister:", "Il-link hija valida għal 60 minuta."),
    "nl": AccountMailCopy("Zahlmeister - Bevestig je e-mailadres", "Bevestig je e-mailadres voor Zahlmeister:", "Als je je niet hebt geregistreerd, kun je dit bericht negeren.", "Zahlmeister - Wachtwoord opnieuw instellen", "Gebruik deze link om je Zahlmeister-wachtwoord opnieuw in te stellen:", "De link is 60 minuten geldig."),
    "pl": AccountMailCopy("Zahlmeister - Potwierdź adres e-mail", "Potwierdź swój adres e-mail dla Zahlmeister:", "Jeśli nie zakładałeś konta, zignoruj tę wiadomość.", "Zahlmeister - Zresetuj hasło", "Użyj tego linku, aby zresetować hasło Zahlmeister:", "Link jest ważny przez 60 minut."),
    "pt": AccountMailCopy("Zahlmeister - Confirme o endereço de e-mail", "Confirme o seu endereço de e-mail para o Zahlmeister:", "Se não se registou, pode ignorar esta mensagem.", "Zahlmeister - Repor palavra-passe", "Use este link para repor a sua palavra-passe do Zahlmeister:", "O link é válido durante 60 minutos."),
    "ro": AccountMailCopy("Zahlmeister - Confirmă adresa de e-mail", "Confirmă adresa de e-mail pentru Zahlmeister:", "Dacă nu te-ai înregistrat, poți ignora acest mesaj.", "Zahlmeister - Resetează parola", "Folosește acest link pentru a reseta parola Zahlmeister:", "Linkul este valabil 60 de minute."),
    "sk": AccountMailCopy("Zahlmeister - Potvrďte e-mailovú adresu", "Potvrďte svoju e-mailovú adresu pre Zahlmeister:", "Ak ste sa neregistrovali, môžete túto správu ignorovať.", "Zahlmeister - Obnovenie hesla", "Pomocou tohto odkazu obnovíte heslo do Zahlmeisteru:", "Odkaz platí 60 minút."),
    "sl": AccountMailCopy("Zahlmeister - Potrdite e-poštni naslov", "Potrdite svoj e-poštni naslov za Zahlmeister:", "Če se niste registrirali, lahko to sporočilo prezrete.", "Zahlmeister - Ponastavite geslo", "S to povezavo ponastavite geslo za Zahlmeister:", "Povezava velja 60 minut."),
    "sv": AccountMailCopy("Zahlmeister - Bekräfta din e-postadress", "Bekräfta din e-postadress för Zahlmeister:", "Om du inte registrerade dig kan du ignorera detta meddelande.", "Zahlmeister - Återställ lösenord", "Använd den här länken för att återställa ditt Zahlmeister-lösenord:", "Länken gäller i 60 minuter."),
}


def _copy(locale: str) -> AccountMailCopy:
    language = (locale or "en").split("-", 1)[0].lower()
    return _COPY.get(language, _COPY["en"])


def verification_mail(locale: str, url: str) -> tuple[str, str]:
    copy = _copy(locale)
    return copy.verify_subject, f"{copy.verify_intro}\n\n{url}\n\n{copy.verify_ignore}"


def password_reset_mail(locale: str, url: str) -> tuple[str, str]:
    copy = _copy(locale)
    return copy.reset_subject, f"{copy.reset_intro}\n\n{url}\n\n{copy.reset_validity}"
