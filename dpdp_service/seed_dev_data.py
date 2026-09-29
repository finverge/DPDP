"""Seeds a working dev/demo state for the two tenants this codebase's
consumers actually integrate against today (BRD Sec. 12 Phase 1 dogfood):

  - "finverge-dlp-los" — DLP LOS diy-portal's native integration
    (frontend/diy-portal/src/lib/dpdpApi.ts + ConsentStep.tsx)
  - "acme-fintech-demo" — the SDK widget demo (../sdk/demo.html)

Each gets an approved English notice (so /consents/capture works
out of the box), a Hindi notice for diy-portal (proving the §5(3)/§6(3)
multi-language path is real, not just a UI toggle with nothing behind it),
and a published DPO contact (§8(9)-(10)). Run once, against whatever
DPDP_DATABASE_URL the service itself is using:

    python seed_dev_data.py
"""
from datetime import datetime, timezone

from app.db import Base, engine, SessionLocal, init_db
from app.models import Notice, NoticeStatus, DPOContact, MaskingPolicy

# Fraud360's real ICICI Bank tenant id (see the fraud360-react-console-*
# memory notes) — the Data Minimization Engine's first live consumer
# (services/analytics_service/app/dpdp_client.py, export_rows/drill).
# field_rules exactly mirror Fraud360's own privacy.py PII_FIELDS/
# mask_value today, so swapping the masking authority is byte-identical,
# not just equivalent-strength (see dpdp_service/tests/test_masking.py's
# parity test).
FRAUD360_TENANT_ID = "9111c4c1-5e9a-42c9-be2a-ec2bb855a532"

# Every non-PII column export_rows/drill can return, across all three
# entities the endpoint allows (alert | case | transaction) — the DPDP
# platform's engine is default-deny per field (dpdp_service/app/masking.py
# omits anything not named here), so these must be enumerated explicitly
# or the export would silently come back with only the PII fields masked
# and everything else stripped. Column lists copied from
# analytics_service/app/engine/postgres.py::PostgresEngine.rows()'s own
# per-entity SELECT lists (as of this integration) — a schema change there
# needs the same change made here, same as it would need a privacy.py
# PII_FIELDS update if a new column were ever PII.
_FRAUD360_NON_PII_FIELDS = [
    # alert
    "alert_id", "ts", "rule_family", "rule_id", "sub_rule_ref", "severity", "score",
    "matched_reason", "observed_value", "threshold_value", "observed_unit",
    "disposition", "case_id", "config_version", "rail", "amount_paise",
    # case (severity, case_id, rail already listed above)
    "opened_ts", "state", "fmr_category", "recovered_paise", "rfa_flag", "region",
    "assignee", "response_due_ts", "decision_ts", "fmr_due_ts", "fmr_filed_ts",
    # transaction (rail, amount_paise, region already listed above)
    "txn_id", "product", "customer_segment", "status",
]
FRAUD360_MASKING_RULES = {
    **{f: "allow" for f in _FRAUD360_NON_PII_FIELDS},
    # PII_FIELDS from analytics_service/app/privacy.py, same masking
    # strategy Fraud360's own _mask_tail/_mask_ip already apply — see
    # dpdp_service/tests/test_masking.py's parity test for the
    # byte-identical-output proof.
    "debtor_account": "mask_account",
    "creditor_account": "mask_account",
    "account": "mask_account",
    "device_id": "mask_device",
    "ip_addr": "mask_ip",
}

EN_NOTICE = (
    "Finverge Digital Lending Platform collects your PAN, address proof, and bank statement "
    "to verify your identity and assess your loan application, as required under RBI KYC "
    "and lending regulations. With your separate consent, we may also use your contact "
    "details to tell you about other products and offers.\n\n"
    "You can view, withdraw, or manage any of these permissions at any time from the "
    "Privacy Center. Withdrawing a permission will not affect an application already in "
    "progress on the basis of it. If you have a concern about how your data is used, you can "
    "raise it with our Grievance Officer, whose contact details are published in the Privacy "
    "Center, before approaching the Data Protection Board of India."
)

HI_NOTICE = (
    "Finverge डिजिटल लेंडिंग प्लेटफ़ॉर्म आपकी पहचान सत्यापित करने और ऋण आवेदन का मूल्यांकन करने के लिए, "
    "RBI KYC और लेंडिंग नियमों के अनुसार, आपका PAN, पता प्रमाण और बैंक स्टेटमेंट एकत्र करता है। आपकी "
    "अलग सहमति से, हम आपके संपर्क विवरण का उपयोग अन्य उत्पादों और ऑफ़र के बारे में बताने के लिए भी कर "
    "सकते हैं।\n\n"
    "आप किसी भी समय Privacy Center से इनमें से कोई भी अनुमति देख, वापस ले या प्रबंधित कर सकते हैं। किसी "
    "अनुमति को वापस लेने से पहले से चल रहे आवेदन पर कोई असर नहीं पड़ेगा। यदि आपको अपने डेटा के उपयोग को "
    "लेकर कोई चिंता है, तो आप Data Protection Board of India से संपर्क करने से पहले हमारे Grievance "
    "Officer से संपर्क कर सकते हैं, जिनका विवरण Privacy Center में प्रकाशित है।"
)

DEMO_NOTICE = (
    "Acme Fintech (demo tenant) collects your PAN and address proof to process your personal "
    "loan application. With your separate consent, we may also use your contact details for "
    "marketing and partner offers. You can withdraw either permission independently at any time."
)


def _approve(db, tenant_id: str, language: str, content: str, approved_by: str = "seed_script") -> None:
    existing = db.query(Notice).filter(
        Notice.tenant_id == tenant_id, Notice.language == language, Notice.status == NoticeStatus.APPROVED,
    ).first()
    if existing is not None:
        print(f"  already approved: {tenant_id} / {language} (v{existing.version})")
        return
    last = db.query(Notice).filter(
        Notice.tenant_id == tenant_id, Notice.language == language,
    ).order_by(Notice.version.desc()).first()
    notice = Notice(
        tenant_id=tenant_id, language=language, content=content,
        version=(last.version + 1) if last else 1,
        status=NoticeStatus.APPROVED, approved_by=approved_by, approved_at=datetime.now(timezone.utc),
    )
    db.add(notice)
    db.commit()
    print(f"  approved: {tenant_id} / {language} (v{notice.version})")


def _upsert_masking_policy(db, tenant_id: str, purpose: str, field_rules: dict[str, str], created_by: str) -> None:
    existing = db.query(MaskingPolicy).filter(
        MaskingPolicy.tenant_id == tenant_id, MaskingPolicy.purpose == purpose,
    ).first()
    if existing is not None:
        existing.field_rules = field_rules
        existing.created_by = created_by
        db.commit()
        print(f"  masking policy updated: {tenant_id} / {purpose} ({len(field_rules)} fields)")
        return
    db.add(MaskingPolicy(tenant_id=tenant_id, purpose=purpose, field_rules=field_rules, created_by=created_by))
    db.commit()
    print(f"  masking policy created: {tenant_id} / {purpose} ({len(field_rules)} fields)")


def _upsert_dpo(db, tenant_id: str, name: str, email: str, phone: str | None = None) -> None:
    existing = db.get(DPOContact, tenant_id)
    if existing is not None:
        print(f"  DPO contact already set: {tenant_id}")
        return
    db.add(DPOContact(tenant_id=tenant_id, name=name, email=email, phone=phone))
    db.commit()
    print(f"  DPO contact published: {tenant_id}")


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        print("finverge-dlp-los:")
        _approve(db, "finverge-dlp-los", "English", EN_NOTICE)
        _approve(db, "finverge-dlp-los", "Hindi", HI_NOTICE)
        _upsert_dpo(db, "finverge-dlp-los", "Grievance & DPO Desk", "privacy@finverge.example", "+91-80-4000-1234")

        print("acme-fintech-demo:")
        _approve(db, "acme-fintech-demo", "English", DEMO_NOTICE)
        _upsert_dpo(db, "acme-fintech-demo", "Acme Privacy Desk", "privacy@acme-fintech.example")

        print(f"{FRAUD360_TENANT_ID} (Fraud360 / ICICI Bank tenant):")
        _upsert_masking_policy(
            db, FRAUD360_TENANT_ID, "fraud360_analytics_export", FRAUD360_MASKING_RULES,
            created_by="seed_script",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
