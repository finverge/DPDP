"""User Sentiment & Trust Scoring (BRD Sec. 6.11) — VADER lexicon/rule-
based sentiment over grievance ticket text, rolled into a documented
heuristic trust score. Same honest-scope discipline as the rest of the
Phase 3 layer (app/ai.py's module docstring): VADER (Hutto & Gilbert,
2014) is a real, widely-used, deterministic sentiment tool — a weighted
lexicon plus grammatical heuristics (negation, intensifiers, punctuation)
— not a neural or generative model, and not hand-rolled keyword counting
either. It runs entirely locally (no external API, no data leaves the
process), which also keeps it inside BRD Sec. 6.9's data-residency
constraint by construction rather than by policy.

Scored on a Data Principal's own words when they filed the grievance
(description) — that is the actual expression of how the experience felt,
not the tenant's own resolution_note, which would just measure how nicely
staff write responses.

trust_score() is a simple, documented, adjustable weighting of three real
signals this platform already has (sentiment, resolution rate, frivolous
rate) — same "heuristic, not trained model" discipline as
app/ai.py's breach_risk_score. It is not validated against any real
outcome (e.g. actual churn or regulator complaints), so it should be read
as a directional indicator for a compliance dashboard, not a certified
metric — stated here rather than left implicit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.models import Grievance, GrievanceStatus

_analyzer = SentimentIntensityAnalyzer()  # lexicon load is the expensive part; one instance for the process


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def score_grievance_sentiment(text: str) -> dict:
    """compound is VADER's normalized -1..+1 score; band is a documented
    cut (VADER's own published convention: >=0.05 positive, <=-0.05
    negative, otherwise neutral)."""
    compound = _analyzer.polarity_scores(text)["compound"]
    band = "positive" if compound >= 0.05 else "negative" if compound <= -0.05 else "neutral"
    return {"compound": round(compound, 4), "band": band}


def trust_score(db: Session, *, tenant_id: str, window_days: int = 90) -> dict:
    since = _utcnow() - timedelta(days=window_days)
    grievances = db.execute(
        select(Grievance).where(Grievance.tenant_id == tenant_id, Grievance.created_at >= since)
    ).scalars().all()

    if not grievances:
        return {
            "tenant_id": tenant_id, "window_days": window_days, "grievance_count": 0,
            "score": None, "band": None,
            "avg_sentiment": None, "resolution_rate": None, "frivolous_rate": None,
            "sentiment_by_grievance": [],
        }

    sentiments = [
        {"grievance_id": g.id, "subject": g.subject, **score_grievance_sentiment(g.description)}
        for g in grievances
    ]
    avg_sentiment = mean(s["compound"] for s in sentiments)
    resolved = sum(1 for g in grievances if g.status == GrievanceStatus.RESOLVED)
    resolution_rate = resolved / len(grievances)
    frivolous = sum(1 for g in grievances if g.is_frivolous)
    frivolous_rate = frivolous / len(grievances)

    # Documented weighting: start neutral at 50, sentiment swings it +-30,
    # a healthy resolution rate adds up to 20, a high frivolous rate (noise
    # in the channel, not necessarily distrust) trims up to 10. Clamped to
    # a valid 0-100 band.
    raw = 50 + (avg_sentiment * 30) + (resolution_rate * 20) - (frivolous_rate * 10)
    score = max(0, min(100, round(raw)))

    return {
        "tenant_id": tenant_id,
        "window_days": window_days,
        "grievance_count": len(grievances),
        "score": score,
        "band": "high" if score >= 70 else "medium" if score >= 40 else "low",
        "avg_sentiment": round(avg_sentiment, 4),
        "resolution_rate": round(resolution_rate, 4),
        "frivolous_rate": round(frivolous_rate, 4),
        "sentiment_by_grievance": sorted(sentiments, key=lambda s: s["compound"])[:10],  # most-negative first, capped
    }
