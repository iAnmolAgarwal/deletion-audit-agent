-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-06-10T11:40:00Z
-- Database topology: read_replica
-- Compare the primary and any replica tables for replication drift.

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
CREATE TABLE customer_data_read_replica (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_primary" VALUES('legal_hold_901010','legal_service','retained_order_records','{"resource_id": "legal_hold_901010", "subject_reference": "user_901001", "order_reference": "ORD-901010", "retention_reason": "payment_dispute_and_tax_record", "retained_until": "2033-12-31T23:59:59Z"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_primary" VALUES('support_901011','support_platform','ticket_attachments','{"resource_id": "support_901011", "ticket_id": "CS-91011", "file_name": "delivery_photo_901011.pdf", "uploaded_by": "wen.halloran@example.com", "storage_class": "ticket_attachment"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_primary" VALUES('audit_record_901012','security_service','security_audit_events','{"resource_id": "audit_record_901012", "subject_reference": "user_901001", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "76f3ce9f6c84f797e778d1bb954b608e348bae0882644d5dba34f80a9cc781d1"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('legal_hold_901010','legal_service','retained_order_records','{"resource_id": "legal_hold_901010", "subject_reference": "user_901001", "order_reference": "ORD-901010", "retention_reason": "payment_dispute_and_tax_record", "retained_until": "2033-12-31T23:59:59Z"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('support_901011','support_platform','ticket_attachments','{"resource_id": "support_901011", "ticket_id": "CS-91011", "file_name": "delivery_photo_901011.pdf", "uploaded_by": "wen.halloran@example.com", "storage_class": "ticket_attachment"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('audit_record_901012','security_service','security_audit_events','{"resource_id": "audit_record_901012", "subject_reference": "user_901001", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "76f3ce9f6c84f797e778d1bb954b608e348bae0882644d5dba34f80a9cc781d1"}','2026-06-10T11:40:00Z');
COMMIT;
