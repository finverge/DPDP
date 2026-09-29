"""Regulatory-Change Watch Agent — BRD Sec. 6.6. Verified against a real
local HTTP server whose content we mutate between checks (not a mocked
httpx client), same standard as test_webhooks.py."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _MutableHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = self.server.next_status
        body = self.server.body
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if status < 400:
            self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture()
def watched_page():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MutableHandler)
    server.body = b"<html>Original DPDP notification text.</html>"
    server.next_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield server, f"http://127.0.0.1:{port}/notifications"
    server.shutdown()
    thread.join(timeout=2)


def _add_source(client, auth_headers, url, name="MeitY DPDP page"):
    resp = client.post("/regulatory-watch/sources", json={
        "name": name, "url": url, "created_by": "platform_ops",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add_rss_source(client, auth_headers, url, name="RBI notifications"):
    resp = client.post("/regulatory-watch/sources", json={
        "name": name, "url": url, "created_by": "platform_ops", "source_kind": "rss",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rss_body(items):
    """items: [{"title": str, "link": str|None, "pub_date": str|None}, ...] — same
    title/description/link/pubDate item shape RBI's real notifications_rss.xml uses."""
    parts = ["<?xml version='1.0' encoding='utf-8'?><rss version='2.0'><channel><title>Test Feed</title>"]
    for it in items:
        link = f"<link>{it['link']}</link>" if it.get("link") else ""
        pub = f"<pubDate>{it['pub_date']}</pubDate>" if it.get("pub_date") else ""
        parts.append(f"<item><title><![CDATA[{it['title']}]]></title><description><![CDATA[body]]></description>{link}{pub}</item>")
    parts.append("</channel></rss>")
    return "".join(parts).encode()


# ---------------------------------------------------------------------- #
# Source management
# ---------------------------------------------------------------------- #
def test_add_source_requires_platform_admin(client, auth_headers, watched_page):
    _, url = watched_page
    resp = client.post("/regulatory-watch/sources", json={
        "name": "x", "url": url, "created_by": "a",
    }, headers=auth_headers("rw1", role="tenant_admin"))
    assert resp.status_code == 403


def test_add_source_rejects_bad_url_scheme(client, auth_headers):
    resp = client.post("/regulatory-watch/sources", json={
        "name": "x", "url": "ftp://example.com/x", "created_by": "a",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 422


def test_any_staff_role_can_list_sources(client, auth_headers, watched_page):
    _, url = watched_page
    _add_source(client, auth_headers, url)
    for role in ("tenant_admin", "dpo", "compliance_officer", "platform_admin"):
        resp = client.get("/regulatory-watch/sources", headers=auth_headers("rw2", role=role))
        assert resp.status_code == 200, (role, resp.text)


def test_default_source_kind_is_page_hash(client, auth_headers, watched_page):
    _, url = watched_page
    source = _add_source(client, auth_headers, url)
    assert source["source_kind"] == "page_hash"


def test_add_source_rejects_unknown_source_kind(client, auth_headers, watched_page):
    _, url = watched_page
    resp = client.post("/regulatory-watch/sources", json={
        "name": "x", "url": url, "created_by": "a", "source_kind": "carrier_pigeon",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 422


def test_default_category_is_dpdp(client, auth_headers, watched_page):
    _, url = watched_page
    source = _add_source(client, auth_headers, url)
    assert source["category"] == "dpdp"


def test_add_source_with_ckycr_category(client, auth_headers, watched_page):
    _, url = watched_page
    resp = client.post("/regulatory-watch/sources", json={
        "name": "CERSAI circulars", "url": url, "created_by": "a", "category": "ckycr",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "ckycr"


def test_sources_filterable_by_category(client, auth_headers, watched_page):
    server, url = watched_page
    _add_source(client, auth_headers, url, name="MeitY DPDP page")
    resp = client.post("/regulatory-watch/sources", json={
        "name": "CERSAI circulars", "url": url, "created_by": "a", "category": "ckycr",
    }, headers=auth_headers(None, role="platform_admin"))
    assert resp.status_code == 200, resp.text

    headers = auth_headers("rw-cat", role="compliance_officer")
    ckycr_only = client.get("/regulatory-watch/sources", params={"category": "ckycr"}, headers=headers).json()
    assert all(s["category"] == "ckycr" for s in ckycr_only)
    assert any(s["name"] == "CERSAI circulars" for s in ckycr_only)
    assert not any(s["name"] == "MeitY DPDP page" for s in ckycr_only)


def test_update_source_category(client, auth_headers, watched_page):
    _, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    assert source["category"] == "dpdp"

    patched = client.patch(f"/regulatory-watch/sources/{source['id']}", json={"category": "ckycr"}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["category"] == "ckycr"


def test_update_and_delete_source(client, auth_headers, watched_page):
    _, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)

    patched = client.patch(f"/regulatory-watch/sources/{source['id']}", json={"active": False}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    deleted = client.delete(f"/regulatory-watch/sources/{source['id']}", headers=headers)
    assert deleted.status_code == 204


# ---------------------------------------------------------------------- #
# Change detection
# ---------------------------------------------------------------------- #
def test_first_check_establishes_baseline_without_alerting(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)

    checked = client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["last_status"] == "ok"

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


def test_unchanged_content_never_alerts(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)

    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # same content again

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


def test_content_change_creates_an_alert(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url, name="MeitY DPDP framework page")

    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline
    server.body = b"<html>NEW: revised breach-intimation format effective immediately.</html>"
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    matching = [a for a in alerts if a["source_id"] == source["id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "new"
    assert matching[0]["source_name"] == "MeitY DPDP framework page"
    assert matching[0]["url"] == url


def test_fetch_error_is_recorded_not_treated_as_a_change(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline, ok

    server.next_status = 403  # MeitY-style bot block
    checked = client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    body = checked.json()
    assert body["last_status"] == "error"
    assert body["last_error"] is not None

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


def test_check_all_sources_summary(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline

    server.body = b"<html>changed for check-all test</html>"
    summary = client.post("/regulatory-watch/check-all", headers=headers).json()
    assert summary["checked"] >= 1
    assert summary["new_alerts"] >= 1


def test_check_all_requires_platform_admin(client, auth_headers):
    resp = client.post("/regulatory-watch/check-all", headers=auth_headers("rw9", role="dpo"))
    assert resp.status_code == 403


# ---------------------------------------------------------------------- #
# "rss" source_kind — per-item diff against a real machine-readable feed
# (modeled on RBI's actual notifications_rss.xml item shape)
# ---------------------------------------------------------------------- #
def test_rss_source_first_check_establishes_baseline_without_alerting(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = _rss_body([{"title": "Notification A", "link": f"{url}?Id=1", "pub_date": "Tue, 01 Sep 2026 10:00:00"}])
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)

    checked = client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["last_status"] == "ok"

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


def test_rss_new_item_creates_an_alert_with_real_title_and_date(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = _rss_body([{"title": "Notification A", "link": f"{url}?Id=1", "pub_date": "Tue, 01 Sep 2026 10:00:00"}])
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline

    server.body = _rss_body([
        {"title": "Notification B", "link": f"{url}?Id=2", "pub_date": "Wed, 02 Sep 2026 11:00:00"},
        {"title": "Notification A", "link": f"{url}?Id=1", "pub_date": "Tue, 01 Sep 2026 10:00:00"},
    ])
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    matching = [a for a in alerts if a["source_id"] == source["id"]]
    assert len(matching) == 1  # only the genuinely new item, not the one already seen at baseline
    assert "Notification B" in matching[0]["detail"]
    assert "02 Sep 2026" in matching[0]["detail"]
    assert matching[0]["url"] == f"{url}?Id=2"


def test_rss_unchanged_feed_never_alerts(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = _rss_body([{"title": "Notification A", "link": f"{url}?Id=1", "pub_date": "Tue, 01 Sep 2026 10:00:00"}])
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # same feed again

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


def test_rss_multiple_new_items_in_one_check_each_get_their_own_alert(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = _rss_body([])
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline, empty feed

    server.body = _rss_body([
        {"title": "New 1", "link": f"{url}?Id=10", "pub_date": "Mon, 07 Sep 2026 09:00:00"},
        {"title": "New 2", "link": f"{url}?Id=11", "pub_date": "Tue, 08 Sep 2026 09:00:00"},
    ])
    checked = client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    assert checked.status_code == 200

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    matching = [a for a in alerts if a["source_id"] == source["id"]]
    assert len(matching) == 2
    titles = {a["detail"].split(" (")[0] for a in matching}
    assert titles == {"New 1", "New 2"}


def test_rss_malformed_xml_is_recorded_as_error_not_a_crash(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = b"<rss><channel><item><title>unterminated"
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)

    checked = client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    assert checked.status_code == 200
    body = checked.json()
    assert body["last_status"] == "error"
    assert "malformed" in body["last_error"].lower()


def test_rss_item_with_no_link_falls_back_to_title_hash_identity(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = _rss_body([{"title": "No-link notice", "pub_date": "Mon, 01 Sep 2026 09:00:00"}])
    headers = auth_headers(None, role="platform_admin")
    source = _add_rss_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # baseline
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # identical item again, still no link

    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)  # not re-alerted just for lacking a <link>


def test_changing_source_kind_resets_the_baseline(client, auth_headers, watched_page):
    server, url = watched_page
    server.body = b"<html>original</html>"
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)  # page_hash
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)  # establishes page_hash baseline

    server.body = _rss_body([{"title": "Fresh item", "link": f"{url}?Id=1", "pub_date": "Mon, 01 Sep 2026 09:00:00"}])
    switched = client.patch(f"/regulatory-watch/sources/{source['id']}", json={"source_kind": "rss"}, headers=headers)
    assert switched.status_code == 200
    assert switched.json()["source_kind"] == "rss"

    # first check after switching kind is a fresh baseline, not an alert flood
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    alerts = client.get("/regulatory-watch/alerts", headers=headers).json()
    assert not any(a["source_id"] == source["id"] for a in alerts)


# ---------------------------------------------------------------------- #
# Acknowledging alerts — the human config-impact mapping step
# ---------------------------------------------------------------------- #
def test_acknowledge_alert_records_note_and_actor(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    server.body = b"<html>revised DPIA structure published</html>"
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)

    alert = [a for a in client.get("/regulatory-watch/alerts", headers=headers).json()
              if a["source_id"] == source["id"]][0]

    ack = client.post(f"/regulatory-watch/alerts/{alert['id']}/acknowledge", json={
        "acknowledged_by": "dpo_platform_1",
        "note": "New DPIA structure adds a 'cross-border transfer' field — maps to DPIADraft.snapshot_json; all tenants affected.",
    }, headers=headers)
    assert ack.status_code == 200, ack.text
    body = ack.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_by"] == "dpo_platform_1"
    assert "cross-border transfer" in body["note"]


def test_double_acknowledge_is_409(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    server.body = b"<html>changed again</html>"
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    alert = [a for a in client.get("/regulatory-watch/alerts", headers=headers).json()
              if a["source_id"] == source["id"]][0]

    client.post(f"/regulatory-watch/alerts/{alert['id']}/acknowledge",
                json={"acknowledged_by": "a", "note": "reviewed"}, headers=headers)
    second = client.post(f"/regulatory-watch/alerts/{alert['id']}/acknowledge",
                          json={"acknowledged_by": "a", "note": "reviewed again"}, headers=headers)
    assert second.status_code == 409


def test_acknowledge_requires_platform_admin(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    server.body = b"<html>changed once more</html>"
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    alert = [a for a in client.get("/regulatory-watch/alerts", headers=headers).json()
              if a["source_id"] == source["id"]][0]

    resp = client.post(f"/regulatory-watch/alerts/{alert['id']}/acknowledge",
                        json={"acknowledged_by": "a", "note": "n"}, headers=auth_headers("rw10", role="dpo"))
    assert resp.status_code == 403


def test_alerts_filterable_by_status(client, auth_headers, watched_page):
    server, url = watched_page
    headers = auth_headers(None, role="platform_admin")
    source = _add_source(client, auth_headers, url)
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    server.body = b"<html>filter test change</html>"
    client.post(f"/regulatory-watch/sources/{source['id']}/check-now", headers=headers)
    alert = [a for a in client.get("/regulatory-watch/alerts", headers=headers).json()
              if a["source_id"] == source["id"]][0]

    new_only = client.get("/regulatory-watch/alerts", params={"status": "new"}, headers=headers).json()
    assert any(a["id"] == alert["id"] for a in new_only)

    client.post(f"/regulatory-watch/alerts/{alert['id']}/acknowledge",
                json={"acknowledged_by": "a", "note": "n"}, headers=headers)

    new_only_after = client.get("/regulatory-watch/alerts", params={"status": "new"}, headers=headers).json()
    assert not any(a["id"] == alert["id"] for a in new_only_after)
    ack_only = client.get("/regulatory-watch/alerts", params={"status": "acknowledged"}, headers=headers).json()
    assert any(a["id"] == alert["id"] for a in ack_only)
