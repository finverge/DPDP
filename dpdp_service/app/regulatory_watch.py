"""Regulatory-Change Watch Agent (BRD Sec. 6.6) — best-effort change
detection over a curated list of official sources, in one of two modes
per source (source_kind on RegulatoryWatchSource):

1. "page_hash" (the original, still the fallback for any source with no
   real feed) — no official machine-readable feed exists for DPDP
   Gazette/MeitY notifications (checked directly this engagement — no
   RSS, no API). MeitY's own site (meity.gov.in) returns HTTP 403 to an
   identified, honest automated request, confirming it can't be reliably
   polled headlessly either. Whole-body hash diff: a change *alarm*, not
   content understanding — no NLP/LLM reads the page to say what changed.

2. "rss" (added once a real feed was actually found and confirmed live —
   RBI publishes a genuine notifications RSS feed at
   rbi.org.in/notifications_rss.xml, checked directly, unlike MeitY) — a
   real upgrade over whole-page hashing where a source has one: each
   watched feed's <item> entries are parsed and diffed by stable
   identifier (each item's <link>, which RBI's feed always includes and
   contains a unique notification ID; falling back to a hash of
   title+pubDate for any future RSS source that omits <link>). A new item
   produces its own alert carrying the item's real title and date in
   `detail` — "here is the new notification" rather than "the page
   changed, go look."

Neither mode does content *understanding*: there is no NLP/LLM reading a
page or feed item to say which DPDP provision it touches — BRD Sec. 6.6's
"maps... to the exact config fields it affects across every tenant" step
is a human's job in both modes (POST /regulatory-watch/alerts/{id}/
acknowledge's `note` field), same "deterministic detection, human
interprets" split as drift/breach-risk detection in app/ai.py.

Known false-positive source, "page_hash" only: naive whole-body hashing
will flag a page as "changed" for any dynamic content unrelated to the
actual regulation (a rotating banner, an embedded timestamp, a session
token) — there is no way to reliably strip that without per-site,
hand-tuned scraping rules this module deliberately doesn't take on. A
human acknowledging a false-positive alert (noting "no real change") is
the intended mitigation, not silence. "rss" mode doesn't share this
failure mode — an item is either a genuinely new notification or it
isn't, since RBI's own feed (not this module) decides what counts as an
item.

Platform-level, not tenant-scoped, unlike every other table in this
service (models.py's tenancy note) — a regulatory source and the fact
that it changed is the same fact for every tenant; only its downstream
config impact is tenant-specific, and that's exactly the part left to a
human via the alert's `note`.
"""
from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RegulatoryWatchAlert, RegulatoryWatchSource

logger = logging.getLogger("dpdp.regulatory_watch")

_FETCH_TIMEOUT_SECONDS = 10.0
_USER_AGENT = "ConsentBridge-RegulatoryWatch/1.0 (+contact: dpo@finverge.example; best-effort page/feed change monitor)"
_RSS_ITEM_HISTORY_CAP = 200  # comfortably above any real feed's current item count (RBI's carries ~10)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _fetch(url: str) -> httpx.Response:
    with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT}) as client:
        resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp


def _parse_rss_items(content: bytes) -> list[dict]:
    """Standard RSS 2.0 <item> shape (title/description/link/pubDate) —
    ElementTree resolves CDATA transparently, no special-casing needed."""
    root = ET.fromstring(content)
    items = []
    for item_el in root.iter("item"):
        items.append({
            "title": (item_el.findtext("title") or "").strip(),
            "link": (item_el.findtext("link") or "").strip() or None,
            "pub_date": (item_el.findtext("pubDate") or "").strip() or None,
        })
    return items


def _item_identity(item: dict) -> str:
    """A stable per-item identifier to diff against: the item's own link
    when the feed provides one (RBI's always does, and it embeds a unique
    notification ID) — otherwise a hash of title+date, for any future RSS
    source whose feed omits <link>."""
    if item["link"]:
        return item["link"]
    return "title-hash:" + _hash(f"{item['title']}|{item['pub_date'] or ''}".encode())


def _check_page_hash_source(db: Session, source: RegulatoryWatchSource) -> list[RegulatoryWatchAlert]:
    try:
        resp = _fetch(source.url)
        new_hash = _hash(resp.content)
    except httpx.HTTPError as exc:
        source.last_status = "error"
        source.last_error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("Regulatory watch source %s (%s) failed to fetch: %s", source.name, source.url, exc)
        return []

    source.last_status = "ok"
    source.last_error = None
    previous_hash = source.last_content_hash
    source.last_content_hash = new_hash

    if previous_hash is None:
        return []  # first check ever — establishes the baseline only, silently
    if previous_hash == new_hash:
        return []

    alert = RegulatoryWatchAlert(
        source_id=source.id, source_name=source.name, url=source.url,
        previous_hash=previous_hash, new_hash=new_hash,
    )
    db.add(alert)
    return [alert]


def _check_rss_source(db: Session, source: RegulatoryWatchSource) -> list[RegulatoryWatchAlert]:
    try:
        resp = _fetch(source.url)
        items = _parse_rss_items(resp.content)
    except httpx.HTTPError as exc:
        source.last_status = "error"
        source.last_error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("Regulatory watch RSS source %s (%s) failed to fetch: %s", source.name, source.url, exc)
        return []
    except ET.ParseError as exc:
        source.last_status = "error"
        source.last_error = f"malformed RSS: {exc}"[:500]
        logger.warning("Regulatory watch RSS source %s (%s) returned unparsable XML: %s", source.name, source.url, exc)
        return []

    source.last_status = "ok"
    source.last_error = None
    source.last_content_hash = _hash(resp.content)  # not used for rss diffing, kept for debugging parity with page_hash sources

    current_ids = [_item_identity(it) for it in items]

    if source.last_seen_item_ids is None:
        # First check ever — establishes the baseline only, silently, same
        # discipline as _check_page_hash_source (no false "everything is new").
        source.last_seen_item_ids = current_ids[:_RSS_ITEM_HISTORY_CAP]
        return []

    seen = set(source.last_seen_item_ids)
    alerts = []
    for item, item_id in zip(items, current_ids):
        if item_id in seen:
            continue
        detail = item["title"]
        if item["pub_date"]:
            detail = f"{detail} ({item['pub_date']})"
        alert = RegulatoryWatchAlert(
            source_id=source.id, source_name=source.name, url=item["link"] or source.url,
            new_hash=_hash(item_id.encode()), detail=detail,
        )
        db.add(alert)
        alerts.append(alert)

    # Union of this check's ids with the prior history, newest-first, capped —
    # keeps recently-dropped-off-the-feed items in history briefly rather than
    # re-alerting on them if they reappear before the cap evicts them.
    merged = current_ids + [i for i in source.last_seen_item_ids if i not in set(current_ids)]
    source.last_seen_item_ids = merged[:_RSS_ITEM_HISTORY_CAP]
    return alerts


def check_source(db: Session, source: RegulatoryWatchSource) -> list[RegulatoryWatchAlert]:
    """Fetches source.url once and returns any new RegulatoryWatchAlert(s)
    detected — a "page_hash" source produces at most one (the page
    changed or it didn't); an "rss" source can produce several in one
    check (one per new feed item). Returns an empty list on a first-ever
    check (baseline only, no false alert), no change, or a fetch/parse
    failure. Mutates and leaves `source` ready to commit; does not commit
    itself — the caller does, same convention as app/webhooks.py."""
    source.last_checked_at = _utcnow()
    if source.source_kind == "rss":
        return _check_rss_source(db, source)
    return _check_page_hash_source(db, source)


def check_all_sources(db: Session, *, active_only: bool = True) -> dict:
    """Called by both the in-process background loop (main.py) and
    POST /regulatory-watch/check-all. Returns a summary, not the alerts
    themselves — callers list new alerts via GET /regulatory-watch/alerts."""
    query = select(RegulatoryWatchSource)
    if active_only:
        query = query.where(RegulatoryWatchSource.active.is_(True))
    sources = db.execute(query).scalars().all()

    checked = 0
    errors = 0
    new_alerts = 0
    for source in sources:
        alerts = check_source(db, source)
        checked += 1
        if source.last_status == "error":
            errors += 1
        new_alerts += len(alerts)
    db.commit()
    return {"checked": checked, "errors": errors, "new_alerts": new_alerts}
