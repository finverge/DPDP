"""DPDP Compliance Platform — Phase 1 core service.

Implements the Consent Management Engine (P360-01/02/03), the Grievance +
DPO-contact module (P360-11), and the notice-approval gate that every other
BRD Sec. 6 AI capability drafts into, never writes past directly (BRD Sec.
6, HLD Sec. 6). See Finverge_DPDP_BRD_v1.0.docx, FSD v1.0, HLD v1.0
(D:\\Finverge\\Docs\\Products\\DPDP\\).

Standalone by design, same convention as the sibling AML360 service
(D:\\Finverge\\Docs\\Products\\AML\\aml_service): zero external setup,
SQLite by default, Postgres via DATABASE_URL for anything beyond a laptop.
"""
