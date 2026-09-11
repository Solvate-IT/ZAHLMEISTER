from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.api.routes.online_payments import router as online_payments_router
from app.models.entities import OnlinePaymentConnection
from app.services import mollie, mollie_onboarding


def test_mollie_oauth_state_roundtrip_and_tamper_rejection() -> None:
    organization_id = str(uuid4())
    state = mollie.sign_oauth_state(organization_id)
    assert mollie.verify_oauth_state(state) == organization_id

    body, signature = state.split('.', 1)
    tampered = f"{body[:-1]}A.{signature}"
    try:
        mollie.verify_oauth_state(tampered)
    except ValueError as exc:
        assert 'OAuth state' in str(exc)
    else:
        raise AssertionError('tampered OAuth state must be rejected')


def test_mollie_locale_normalization_uses_supported_fallbacks() -> None:
    assert mollie.normalize_locale('de-AT') == 'de_AT'
    assert mollie.normalize_locale('en') == 'en_GB'
    assert mollie.normalize_locale('sl-SI') is None
    assert mollie.normalize_locale(None) is None


def test_mollie_oauth_start_contract_uses_post() -> None:
    route = next(
        item
        for item in online_payments_router.routes
        if item.path == "/online-payments/mollie/oauth/start"
    )
    assert route.methods == {"POST"}


def test_mollie_client_link_prefill_uses_existing_customer_data() -> None:
    payload = mollie_onboarding.build_client_link_prefill(
        email=" billing@example.com ",
        display_name="Christian Fast",
        organization_name=" Solvate IT ",
        locale="de-AT",
        country="at",
        street_and_number="Teststraße 1",
        postal_code="8010",
        city="Graz",
        region="Steiermark",
        registration_number="FN 123",
        vat_number="ATU12345678",
    )

    assert payload == {
        "owner": {
            "email": "billing@example.com",
            "givenName": "Christian",
            "familyName": "Fast",
            "locale": "de_AT",
        },
        "name": "Solvate IT",
        "address": {
            "country": "AT",
            "streetAndNumber": "Teststraße 1",
            "postalCode": "8010",
            "city": "Graz",
            "region": "Steiermark",
        },
        "registrationNumber": "FN 123",
        "vatNumber": "ATU12345678",
    }


def test_mollie_client_link_prefill_falls_back_when_owner_cannot_be_derived() -> None:
    assert mollie_onboarding.build_client_link_prefill(
        email="billing@example.com",
        display_name="Christian",
        organization_name="Solvate IT",
        locale="de-AT",
        country="AT",
    ) is None


def test_mollie_onboarding_without_advanced_token_uses_standard_oauth(monkeypatch) -> None:
    monkeypatch.setattr(mollie_onboarding.settings, "mollie_connect_access_token", "")
    monkeypatch.setattr(
        mollie_onboarding,
        "oauth_authorization_url",
        lambda organization_id: f"https://oauth.example/{organization_id}",
    )

    url = asyncio.run(
        mollie_onboarding.onboarding_authorization_url(
            "organization-1",
            {"owner": {"email": "test@example.com"}},
        )
    )
    assert url == "https://oauth.example/organization-1"


def test_mollie_onboarding_creates_client_link_and_preserves_oauth_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "_links": {
                    "clientLink": {
                        "href": "https://my.mollie.com/client-link/test",
                    }
                }
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(mollie_onboarding.settings, "mollie_connect_access_token", "advanced_test")
    monkeypatch.setattr(mollie_onboarding.settings, "mollie_oauth_client_id", "app_test")
    monkeypatch.setattr(mollie_onboarding.httpx, "AsyncClient", lambda timeout: FakeClient())
    monkeypatch.setattr(mollie_onboarding, "oauth_authorization_url", lambda _: "https://fallback")
    monkeypatch.setattr(mollie_onboarding, "sign_oauth_state", lambda _: "signed-state")

    prefill = {
        "owner": {
            "email": "billing@example.com",
            "givenName": "Christian",
            "familyName": "Fast",
        },
        "name": "Solvate IT",
        "address": {"country": "AT"},
    }
    url = asyncio.run(mollie_onboarding.onboarding_authorization_url("organization-1", prefill))

    assert captured["url"] == "https://api.mollie.com/v2/client-links"
    assert captured["json"] == prefill
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer advanced_test"

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "my.mollie.com"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["app_test"]
    assert query["state"] == ["signed-state"]
    assert query["approval_prompt"] == ["auto"]
    assert query["scope"] == [mollie_onboarding.settings.mollie_oauth_scopes]


def test_mollie_payment_status_parser() -> None:
    status = mollie.payment_status_from_payload(
        {
            'id': 'tr_test',
            'status': 'paid',
            'amount': {'value': '12.50', 'currency': 'eur'},
            'method': 'applepay',
            'paidAt': '2026-09-06T09:00:00Z',
            'expiresAt': '2026-09-07T09:00:00Z',
        }
    )
    assert status.external_id == 'tr_test'
    assert status.status == 'paid'
    assert status.amount == Decimal('12.50')
    assert status.currency == 'EUR'
    assert status.method == 'applepay'
    assert status.paid_at == datetime(2026, 9, 6, 9, 0, tzinfo=UTC)


def test_mollie_checkout_requires_payment_profile() -> None:
    connection = OnlinePaymentConnection(
        organization_id=uuid4(),
        provider='mollie',
        profile_id=None,
        encrypted_config='unused',
    )

    async def run() -> None:
        try:
            await mollie.mollie_provider.create_checkout(
                object(),  # type: ignore[arg-type]
                connection,
                amount=Decimal('12.00'),
                currency='EUR',
                description='School trip',
                redirect_url='https://app.example/pay',
                webhook_url='https://app.example/webhook',
                metadata={'reference': 'ZM-1'},
                locale='de-AT',
                idempotency_key='idem-1',
            )
        except ValueError as exc:
            assert 'profile' in str(exc).lower()
        else:
            raise AssertionError('checkout without profile must be rejected')

    asyncio.run(run())


def test_mollie_checkout_uses_hosted_checkout_and_idempotency(monkeypatch) -> None:
    connection = OnlinePaymentConnection(
        organization_id=uuid4(),
        provider='mollie',
        profile_id='pfl_test',
        encrypted_config='unused',
    )
    captured: dict[str, object] = {}

    async def fake_authorization(session, current_connection):
        assert current_connection is connection
        return 'Bearer merchant-token'

    async def fake_request(method, path, **kwargs):
        captured['method'] = method
        captured['path'] = path
        captured.update(kwargs)
        return {
            'id': 'tr_test',
            'status': 'open',
            'expiresAt': '2026-09-06T10:00:00Z',
            '_links': {'checkout': {'href': 'https://www.mollie.com/checkout/test'}},
        }

    monkeypatch.setattr(mollie, 'authorization_for_connection', fake_authorization)
    monkeypatch.setattr(mollie, '_request_json', fake_request)
    monkeypatch.setattr(mollie, '_testmode', lambda _: False)

    async def run():
        return await mollie.mollie_provider.create_checkout(
            object(),  # type: ignore[arg-type]
            connection,
            amount=Decimal('12.00'),
            currency='eur',
            description='School trip',
            redirect_url='https://app.example/?pay=abc&online=return',
            webhook_url='https://app.example/api/v1/webhooks/mollie/key',
            metadata={'reference': 'ZM-1'},
            locale='de-AT',
            idempotency_key='attempt-uuid',
        )

    checkout = asyncio.run(run())
    assert checkout.external_id == 'tr_test'
    assert checkout.checkout_url == 'https://www.mollie.com/checkout/test'
    assert captured['method'] == 'POST'
    assert captured['path'] == 'payments'
    assert captured['idempotency_key'] == 'attempt-uuid'
    body = captured['json_body']
    assert isinstance(body, dict)
    assert body['profileId'] == 'pfl_test'
    assert body['amount'] == {'currency': 'EUR', 'value': '12.00'}
    assert body['locale'] == 'de_AT'
    assert body['metadata'] == {'reference': 'ZM-1'}
