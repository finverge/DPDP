"""Webhooks — FSD Sec. 5.4. Delivery is verified against a real local HTTP
receiver (not a mocked httpx client) so the signing/HTTP-call code path is
actually exercised, matching this suite's existing standard."""
import hashlib
import hmac
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _CapturingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.received.append({"headers": dict(self.headers), "body": body})
        self.send_response(self.server.next_status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):  # noqa: A002 — silence default stderr logging
        pass


@pytest.fixture()
def webhook_receiver():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.received = []
    server.next_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield server, f"http://127.0.0.1:{port}/hook"
    server.shutdown()
    thread.join(timeout=2)


def _create_subscription(client, auth_headers, tenant_id, url, events):
    resp = client.post("/webhooks/subscriptions", json={
        "tenant_id": tenant_id, "url": url, "events": events, "created_by": "dpo_1",
    }, headers=auth_headers(tenant_id))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve_new_notice(client, auth_headers, tenant_id, content="Notice text"):
    headers = auth_headers(tenant_id)
    draft = client.post("/notices", json={"tenant_id": tenant_id, "language": "en", "content": content}, headers=headers)
    notice_id = draft.json()["id"]
    client.post(f"/notices/{notice_id}/approve", json={"approved_by": "dpo_1"}, headers=headers)
    return notice_id


# ---------------------------------------------------------------------- #
# Subscription management
# ---------------------------------------------------------------------- #
def test_create_subscription_returns_secret_once(client, auth_headers):
    sub = _create_subscription(client, auth_headers, "w1", "https://processor.example/hook", ["consent.created"])
    assert "secret" in sub and len(sub["secret"]) == 48  # token_hex(24)

    listed = client.get("/webhooks/subscriptions", params={"tenant_id": "w1"}, headers=auth_headers("w1")).json()
    assert len(listed) == 1
    assert "secret" not in listed[0]


def test_create_subscription_rejects_unknown_event(client, auth_headers):
    resp = client.post("/webhooks/subscriptions", json={
        "tenant_id": "w2", "url": "https://processor.example/hook",
        "events": ["consent.exploded"], "created_by": "dpo_1",
    }, headers=auth_headers("w2"))
    assert resp.status_code == 422


def test_create_subscription_rejects_bad_url_scheme(client, auth_headers):
    resp = client.post("/webhooks/subscriptions", json={
        "tenant_id": "w3", "url": "ftp://processor.example/hook",
        "events": ["consent.created"], "created_by": "dpo_1",
    }, headers=auth_headers("w3"))
    assert resp.status_code == 422


def test_update_toggle_active_and_delete(client, auth_headers):
    headers = auth_headers("w4")
    sub = _create_subscription(client, auth_headers, "w4", "https://processor.example/hook", ["consent.created"])

    patched = client.patch(f"/webhooks/subscriptions/{sub['id']}", json={"active": False}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    deleted = client.delete(f"/webhooks/subscriptions/{sub['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/webhooks/subscriptions", params={"tenant_id": "w4"}, headers=headers).json() == []


def test_rotate_secret_changes_it(client, auth_headers):
    headers = auth_headers("w5")
    sub = _create_subscription(client, auth_headers, "w5", "https://processor.example/hook", ["consent.created"])
    rotated = client.post(f"/webhooks/subscriptions/{sub['id']}/rotate-secret", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["secret"] != sub["secret"]


def test_subscriptions_require_auth(client):
    resp = client.get("/webhooks/subscriptions", params={"tenant_id": "w6"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------- #
# Real delivery, over a real socket, to consent.created / consent.withdrawn / data.accessed
# ---------------------------------------------------------------------- #
def test_consent_created_delivers_with_valid_signature(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    sub = _create_subscription(client, auth_headers, "w10", url, ["consent.created"])
    notice_id = _approve_new_notice(client, auth_headers, "w10")

    resp = client.post("/consents/capture", json={
        "tenant_id": "w10", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    assert resp.status_code == 200, resp.text
    record_id = resp.json()[0]["id"]

    assert len(server.received) == 1
    body_bytes = server.received[0]["body"]
    envelope = json.loads(body_bytes)
    assert envelope["event"] == "consent.created"
    assert envelope["tenant_id"] == "w10"
    assert envelope["data"]["consent_record_id"] == record_id
    assert envelope["data"]["purpose"] == "KYC"

    expected_sig = "sha256=" + hmac.new(sub["secret"].encode(), body_bytes, hashlib.sha256).hexdigest()
    assert server.received[0]["headers"]["X-ConsentBridge-Signature"] == expected_sig
    assert server.received[0]["headers"]["X-ConsentBridge-Event"] == "consent.created"

    deliveries = client.get("/webhooks/deliveries", params={"tenant_id": "w10"}, headers=auth_headers("w10")).json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "success"
    assert deliveries[0]["response_status"] == 200


def test_consent_withdrawn_delivers(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w11", url, ["consent.withdrawn"])
    notice_id = _approve_new_notice(client, auth_headers, "w11")
    captured = client.post("/consents/capture", json={
        "tenant_id": "w11", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    }).json()
    consent_id = captured[0]["id"]

    # not subscribed to consent.created, so nothing delivered yet
    assert len(server.received) == 0

    client.post(f"/consents/{consent_id}/withdraw", json={"actor": "dp1", "reason": "no longer needed"})
    assert len(server.received) == 1
    envelope = json.loads(server.received[0]["body"])
    assert envelope["event"] == "consent.withdrawn"
    assert envelope["data"]["consent_record_id"] == consent_id
    assert envelope["data"]["reason"] == "no longer needed"


def test_consent_modified_delivers(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w11b", url, ["consent.modified"])
    notice_id = _approve_new_notice(client, auth_headers, "w11b")
    captured = client.post("/consents/capture", json={
        "tenant_id": "w11b", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC", "duration_days": 365}],
    }).json()
    consent_id = captured[0]["id"]

    assert len(server.received) == 0  # not subscribed to consent.created

    resp = client.patch(f"/consents/{consent_id}", json={
        "duration_days": 30, "actor": "dp1", "reason": "renewal",
    })
    assert resp.status_code == 200

    assert len(server.received) == 1
    envelope = json.loads(server.received[0]["body"])
    assert envelope["event"] == "consent.modified"
    assert envelope["data"]["consent_record_id"] == consent_id
    assert envelope["data"]["previous_duration_days"] == 365
    assert envelope["data"]["duration_days"] == 30


def test_data_accessed_delivers_on_successful_masking_apply(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w12", url, ["data.accessed"])
    client.put("/masking/policies", json={
        "tenant_id": "w12", "purpose": "csv_export", "created_by": "a",
        "field_rules": {"account_number": "mask_last4"},
    }, headers=auth_headers("w12"))

    resp = client.post("/masking/apply", json={
        "tenant_id": "w12", "purpose": "csv_export", "actor": "analyst_1",
        "records": [{"account_number": "1234567890"}],
    })
    assert resp.status_code == 200

    assert len(server.received) == 1
    envelope = json.loads(server.received[0]["body"])
    assert envelope["event"] == "data.accessed"
    assert envelope["data"]["purpose"] == "csv_export"
    assert envelope["data"]["record_count"] == 1


def test_blocked_masking_apply_never_fires_data_accessed(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w13", url, ["data.accessed"])
    resp = client.post("/masking/apply", json={
        "tenant_id": "w13", "purpose": "no_such_policy", "actor": "analyst_1",
        "records": [{"x": "1"}],
    })
    assert resp.status_code == 422
    assert len(server.received) == 0


def test_unsubscribed_event_type_delivers_nothing(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w14", url, ["data.accessed"])  # not consent.created
    notice_id = _approve_new_notice(client, auth_headers, "w14")
    client.post("/consents/capture", json={
        "tenant_id": "w14", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    assert len(server.received) == 0


def test_inactive_subscription_never_delivers(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    headers = auth_headers("w15")
    sub = _create_subscription(client, auth_headers, "w15", url, ["consent.created"])
    client.patch(f"/webhooks/subscriptions/{sub['id']}", json={"active": False}, headers=headers)

    notice_id = _approve_new_notice(client, auth_headers, "w15")
    client.post("/consents/capture", json={
        "tenant_id": "w15", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    assert len(server.received) == 0


# ---------------------------------------------------------------------- #
# Retry-with-backoff and exhaustion
# ---------------------------------------------------------------------- #
def test_failed_delivery_schedules_a_backoff_retry(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    server.next_status = 500
    _create_subscription(client, auth_headers, "w20", url, ["consent.created"])
    notice_id = _approve_new_notice(client, auth_headers, "w20")
    client.post("/consents/capture", json={
        "tenant_id": "w20", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })

    deliveries = client.get("/webhooks/deliveries", params={"tenant_id": "w20"}, headers=auth_headers("w20")).json()
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d["status"] == "pending"
    assert d["attempt_count"] == 1
    assert d["response_status"] == 500
    # next_attempt_at should be roughly last_attempt_at + 30s (first backoff step)
    next_at = datetime.fromisoformat(d["next_attempt_at"])
    last_at = datetime.fromisoformat(d["last_attempt_at"])
    assert timedelta(seconds=25) < (next_at - last_at) < timedelta(seconds=35)


def test_process_due_deliveries_retries_and_eventually_exhausts(client, auth_headers, webhook_receiver):
    from app.db import SessionLocal
    from app.models import WebhookDelivery
    from app.webhooks import WEBHOOK_MAX_ATTEMPTS, process_due_deliveries

    server, url = webhook_receiver
    server.next_status = 500
    _create_subscription(client, auth_headers, "w21", url, ["consent.created"])
    notice_id = _approve_new_notice(client, auth_headers, "w21")
    client.post("/consents/capture", json={
        "tenant_id": "w21", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })

    db = SessionLocal()
    try:
        delivery = db.query(WebhookDelivery).filter_by(tenant_id="w21").one()
        assert delivery.attempt_count == 1

        # force every remaining attempt to be immediately due, and let the
        # receiver keep failing, until WEBHOOK_MAX_ATTEMPTS is exhausted
        for _ in range(WEBHOOK_MAX_ATTEMPTS - 1):
            delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
            processed = process_due_deliveries(db, tenant_id="w21")
            assert processed == 1
            db.refresh(delivery)

        assert delivery.attempt_count == WEBHOOK_MAX_ATTEMPTS
        assert delivery.status == "failed"
    finally:
        db.close()

    # exhausted deliveries stay visible, not deleted (FSD Sec. 5.4)
    deliveries = client.get(
        "/webhooks/deliveries", params={"tenant_id": "w21", "status": "failed"}, headers=auth_headers("w21"),
    ).json()
    assert len(deliveries) == 1


def test_manual_retry_endpoint_forces_immediate_attempt(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    server.next_status = 500
    headers = auth_headers("w22")
    _create_subscription(client, auth_headers, "w22", url, ["consent.created"])
    notice_id = _approve_new_notice(client, auth_headers, "w22")
    client.post("/consents/capture", json={
        "tenant_id": "w22", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    delivery = client.get("/webhooks/deliveries", params={"tenant_id": "w22"}, headers=headers).json()[0]
    assert delivery["attempt_count"] == 1

    server.next_status = 200  # "fixed the receiver"
    retried = client.post(f"/webhooks/deliveries/{delivery['id']}/retry", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "success"
    assert retried.json()["attempt_count"] == 2
    assert len(server.received) == 2


def test_retrying_a_successful_delivery_is_409(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    headers = auth_headers("w23")
    _create_subscription(client, auth_headers, "w23", url, ["consent.created"])
    notice_id = _approve_new_notice(client, auth_headers, "w23")
    client.post("/consents/capture", json={
        "tenant_id": "w23", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    delivery = client.get("/webhooks/deliveries", params={"tenant_id": "w23"}, headers=headers).json()[0]
    resp = client.post(f"/webhooks/deliveries/{delivery['id']}/retry", headers=headers)
    assert resp.status_code == 409


def test_process_due_endpoint_requires_platform_admin(client, auth_headers):
    resp = client.post("/webhooks/deliveries/process-due", headers=auth_headers("w24"))
    assert resp.status_code == 403

    resp2 = client.post("/webhooks/deliveries/process-due", headers=auth_headers(None, role="platform_admin"))
    assert resp2.status_code == 200
    assert "processed" in resp2.json()


# ---------------------------------------------------------------------- #
# breach.detected — fires once when drift pushes the tenant into "high"
# band, gated by a 24h cooldown against repeat firing
# ---------------------------------------------------------------------- #
def test_breach_detected_fires_once_on_entering_high_band(client, auth_headers, webhook_receiver):
    server, url = webhook_receiver
    _create_subscription(client, auth_headers, "w30", url, ["breach.detected"])
    client.put("/masking/policies", json={
        "tenant_id": "w30", "purpose": "kyc_share", "created_by": "a",
        "field_rules": {"pan": "mask_last4"},
    }, headers=auth_headers("w30"))

    # 8 drift-triggering accesses (no active consent grant covers "kyc_share"
    # for this data principal) -> score = 8*8 = 64 -> "high" band on the 8th.
    for i in range(9):
        resp = client.post("/masking/apply", json={
            "tenant_id": "w30", "purpose": "kyc_share", "actor": "analyst_1",
            "data_principal_id": "dp_drift", "records": [{"pan": "ABCDE1234F"}],
        })
        assert resp.status_code == 200

    breach_events = [
        json.loads(r["body"]) for r in server.received
        if json.loads(r["body"])["event"] == "breach.detected"
    ]
    # exactly one, despite 9 qualifying calls — the 24h cooldown stops repeats
    assert len(breach_events) == 1
    assert breach_events[0]["data"]["band"] == "high"
