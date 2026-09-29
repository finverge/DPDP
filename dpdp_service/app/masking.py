"""Data Minimization Engine — the actual field-transform logic behind
POST /masking/apply (FSD Sec. 4.2). Kept separate from routes.py so it's
independently testable and so a future strategy (e.g. a date-window
truncation for "last 6 months of transactions") is a function added here,
not routing logic.
"""

_MASK_CHAR = "•"


def _mask_tail(value, keep_prefix: int, keep_tail: int) -> str:
    s = str(value) if value is not None else ""
    if not s or len(s) <= keep_prefix + keep_tail:
        return _MASK_CHAR * len(s)
    return f"{s[:keep_prefix]}{_MASK_CHAR * (len(s) - keep_prefix - keep_tail)}{s[-keep_tail:]}"


def _mask_last4(value) -> str:
    return _mask_tail(value, keep_prefix=0, keep_tail=4)


def _mask_account(value) -> str:
    """keep_prefix=2, keep_tail=4 — matches Fraud360's own
    analytics_service/app/privacy.py::_mask_tail default exactly, so a
    tenant migrating its account-field masking onto this engine gets
    byte-identical output, not just an equivalent-strength one."""
    return _mask_tail(value, keep_prefix=2, keep_tail=4)


def _mask_device(value) -> str:
    """keep_prefix=1, keep_tail=3 — matches Fraud360's device_id masking exactly."""
    return _mask_tail(value, keep_prefix=1, keep_tail=3)


def _mask_ip(value) -> str:
    """Matches Fraud360's privacy.py::_mask_ip exactly: keep the first two
    octets, mask the last two."""
    s = str(value) if value is not None else ""
    parts = s.split(".")
    return ".".join(parts[:2] + [_MASK_CHAR, _MASK_CHAR]) if len(parts) == 4 else _MASK_CHAR * 3


def _redact(_value) -> str:
    return "***REDACTED***"


_STRATEGIES = {
    "allow": lambda v: v,
    "redact": _redact,
    "mask_last4": _mask_last4,
    "mask_account": _mask_account,
    "mask_device": _mask_device,
    "mask_ip": _mask_ip,
}


def apply_policy(record: dict, field_rules: dict[str, str]) -> dict:
    """Applies field_rules to one flat record. Default-deny: any field not
    named in field_rules is omitted from the output, never passed through
    unmasked by accident (FSD Sec. 4.2's minimization-by-default rule)."""
    out: dict = {}
    for field, value in record.items():
        strategy = field_rules.get(field, "omit")
        if strategy == "omit":
            continue
        out[field] = _STRATEGIES[strategy](value)
    return out
