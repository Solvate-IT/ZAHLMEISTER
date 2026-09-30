"""Versions of the published legal texts.

Bump TERMS_VERSION whenever the terms of use shown at /terms change materially;
every acceptance is stored together with the version the user agreed to
(users.terms_accepted_at / users.terms_version). The frontend page shows the same
version (frontend/src/components/PublicLegalPage.tsx).
"""

TERMS_VERSION = "2026-09-29"
