from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.models.entities import OnlinePaymentConnection
from app.services import mollie


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
