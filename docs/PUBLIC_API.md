# Zahlmeister Public API

The customer Public API allows an organization to manage participant lists and collections from an external system and to query collection payment status.

## Base URL

All customer API endpoints are below:

```text
https://<your-zahlmeister-host>/api/public/v1
```

The host depends on the Zahlmeister installation. The path is stable.

## Enabling access and creating credentials

1. Open **Configuration → API & integrations** in Zahlmeister.
2. Enable API access for the organization.
3. Create an API credential and select only the scopes the external integration needs.
4. Copy the returned API key immediately. The raw key is shown only once; only a hash is stored afterwards.
5. Revoke the credential in Zahlmeister when it is no longer required.

API access is tenant-isolated. The organization is derived from the API credential; clients do not send an organization id.

## Authentication

Send the credential as a Bearer token:

```http
Authorization: Bearer <API_KEY>
```

Example:

```bash
curl \
  -H "Authorization: Bearer <API_KEY>" \
  https://<your-zahlmeister-host>/api/public/v1/participant-lists
```

## Scopes

| Scope | Allows |
| --- | --- |
| `participants:read` | Read participant lists and participants |
| `participants:write` | Create participant lists and add participants |
| `collections:read` | Read collections and their participant/payment details |
| `collections:write` | Create collections |
| `payments:read` | Read the summarized payment status of a collection |

Credentials should receive the smallest required scope set.

## Endpoints

### List participant lists

`GET /participant-lists`

Required scope: `participants:read`

Returns all participant lists of the authenticated organization with their participant count.

### Create participant list

`POST /participant-lists`

Required scope: `participants:write`

Minimal request:

```json
{
  "name": "Class 3A"
}
```

`name` is optional. Zahlmeister applies its normal unique-name rules.

### Read participant list

`GET /participant-lists/{list_id}`

Required scope: `participants:read`

Returns the list and its participants. Participant responses include name, contact data, optional message language, channel addresses and effective channel availability.

### Add participant

`POST /participant-lists/{list_id}/participants`

Required scope: `participants:write`

Example:

```json
{
  "name": "Anna Example",
  "email": "anna@example.com",
  "phone": "+431234567",
  "locale": "de",
  "channel_addresses": {
    "telegram": "anna_example"
  }
}
```

`email`, `phone`, `locale` and `channel_addresses` are optional. `locale` accepts the same supported message-language codes as the Zahlmeister UI. Duplicate participants and plan limits are enforced by the same backend business rules as the application.

### List collections

`GET /collections`

Required scope: `collections:read`

Returns all collections of the authenticated organization with aggregated payment counts and the effective communication configuration.

### Create collection

`POST /collections`

Required scope: `collections:write`

Minimal example:

```json
{
  "participant_list_id": "<UUID>",
  "name": "Summer camp",
  "amount": "45.00",
  "currency": "EUR",
  "communication_channel": "auto"
}
```

Relevant optional fields include `send_at`, `due_at`, `message_template_id`, `message_body_override`, `reminder_rules`, `include_payment_link` and `include_payment_qr`.

The receiving bank account must already be configured in Zahlmeister. Collection creation uses the same validation and business rules as the normal application.

### Read collection

`GET /collections/{collection_id}`

Required scope: `collections:read`

Returns the collection plus its participants, payment references, payment URLs, paid/open status, delivery information and reminder counters.

### Read collection payment status

`GET /collections/{collection_id}/status`

Required scope: `payments:read`

Example response:

```json
{
  "id": "<UUID>",
  "name": "Summer camp",
  "currency": "EUR",
  "amount": "45.00",
  "participant_count": 25,
  "paid_count": 18,
  "open_count": 7,
  "paid_amount": "810.00",
  "total_amount": "1125.00",
  "status": "active"
}
```

This endpoint is intended for external systems that only need the current collection/payment progress without loading all participant details.

## HTTP status codes

Typical responses:

| Status | Meaning |
| --- | --- |
| `200` | Request succeeded |
| `201` | Resource created |
| `401` | API key missing, invalid, expired or revoked |
| `403` | API access disabled, required scope missing, or another server-side permission/business limit denied the action |
| `404` | Resource does not exist for the authenticated organization |
| `409` | Business conflict, for example a duplicate participant or missing prerequisite |
| `422` | Request validation failed |

FastAPI validation errors are returned as JSON. Clients should not depend on human-readable error text; use the HTTP status and response structure.

## Data types and identifiers

- Resource identifiers are UUID strings.
- Monetary values should be sent as decimal values/strings, never floating-point approximations in financial logic.
- Date/time values use ISO 8601.
- API responses are JSON.
- The API never accepts an organization id from the client; tenant context comes exclusively from the credential.

## Current API boundary

The current Public API intentionally exposes only the supported external workflow: create/read participant lists, add participants, create/read collections and read payment status. Update/delete operations, direct payment mutation and communication-provider configuration are not part of the Public API unless explicitly added in a future version.
