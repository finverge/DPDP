# ConsentBridge (DPDP Compliance Platform) — Core Service

Phases 1–3 (BRD Sec. 12) of [ConsentBridge](../BRD/Finverge_DPDP_BRD_v1.1.docx): Phase 1's Consent
Management Engine, Data Minimization & Masking engine, and Grievance/DPO module; Phase 2's multi-tenant
onboarding, white-label branding, and usage metering; Phase 3's deterministic AI-native capability layer
(drift detection, breach-risk scoring, notice/DPIA drafting, grievance triage, purpose-gated cross-sell,
structured rights Q&A — see `app/ai.py`'s module docstring for the honest "no LLM calls" scope statement).

**Standalone, runnable, real** — not a stub. SQLite by default (zero setup), Postgres via `DPDP_DATABASE_URL`
for anything beyond a laptop. Two real consumers exist today:

- **Finverge DLP LOS `diy-portal`** — native TypeScript integration (`frontend/diy-portal/src/lib/dpdpApi.ts`,
  `ConsentStep.tsx`, `PrivacyCenter.tsx`).
- **The embeddable SDK widget** (`../sdk/dpdp-consent-widget.js`) — the third-party integration path, proven
  against a mock "Acme Fintech" host page (`../sdk/demo.html`).
- **Fraud360** — the Data Minimization/Masking module's first consumer (see `INTEGRATION.md` once the
  Fraud360-side wiring lands).

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8110
python seed_dev_data.py   # approves a working notice + DPO contact for the two dev tenants
```

Then: http://localhost:8110/docs

## Modules

| Module | Endpoints | FSD ref |
|---|---|---|
| Notices | `POST /notices`, `POST /notices/{id}/approve`, `GET /notices/current` | Sec. 3.1 |
| Consent | `POST /consents/capture`, `POST /consents/{id}/withdraw`, `GET /consents`, `GET /consents/{id}/audit` | Sec. 3.2–3.4 |
| Data Minimization & Masking | `PUT /masking/policies`, `GET /masking/policies`, `POST /masking/apply` | Sec. 4 |
| Grievance | `POST /grievances`, `GET /grievances`, `GET /grievances/{id}`, `POST /grievances/{id}/resolve`, `POST /grievances/{id}/flag-frivolous` | Sec. 8.3 |
| DPO contact | `PUT /dpo-contact`, `GET /dpo-contact` | §8(9)-(10) |
| Tenants (Phase 2) | `POST /tenants`, `GET /tenants/{id}`, `PUT /tenants/{id}/branding`, `GET /tenants/{id}/usage` | BRD Sec. 8 |
| AI capabilities (Phase 3) | `GET /ai/drift-flags`, `GET /ai/breach-risk`, `POST /ai/draft-notice`, `POST /ai/draft-dpia/{tenant_id}`, `GET /ai/dpia/{tenant_id}[/history]`, `POST /ai/triage-grievance/{id}`, `POST /ai/cross-sell/candidates`, `GET /ai/rights-assistant` | BRD Sec. 6 |

## Design rules carried through every module

- **Tenant-scoped everywhere** — every table has `tenant_id`, every query filters on it explicitly (see
  `app/models.py` tenancy note).
- **Fail-closed, not fail-open** — `/consents/capture` rejects an unapproved notice; `/masking/apply` rejects
  a purpose with no configured policy (422, not a silent unmasked pass-through); a masked record omits any
  field not explicitly named in the policy.
- **Every action is audited** — captures, withdrawals, masking applications, and masking *blocks* all write to
  an audit trail; nothing is "successes only."
- **Honest AI scope** — `app/ai.py`'s capabilities are deterministic detection/assembly (real signals this
  service already tracks), not generative-model calls; no LLM provider is configured in this environment. See
  its module docstring before assuming any capability does more than it says.
- **No payment handling** — Phase 2's `UsageEvent` log is the metering data a real billing system would read;
  this service never touches a card, invoice, or payment processor.

## Tests

```bash
pytest -q
```

45 tests, no live dependencies — each test session gets a fresh, disposable SQLite file (`tests/conftest.py`).
