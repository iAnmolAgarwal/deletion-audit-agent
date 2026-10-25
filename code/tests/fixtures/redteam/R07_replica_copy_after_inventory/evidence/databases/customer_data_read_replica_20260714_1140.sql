-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-07-14T11:40:00Z
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
INSERT INTO "customer_data_primary" VALUES('audit_record_9306102','security_service','security_audit_events','{"resource_id": "audit_record_9306102", "subject_reference": "user_930610", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "b514f3f561f69f860860df7bbc01f3b29ffb56acc2fd5bc48ce10d5f7383fe51"}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('audit_record_9306102','security_service','security_audit_events','{"resource_id": "audit_record_9306102", "subject_reference": "user_930610", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "b514f3f561f69f860860df7bbc01f3b29ffb56acc2fd5bc48ce10d5f7383fe51"}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('account_9306101','account_service','customer_profiles','{"resource_id": "account_9306101", "customer_reference": "user_930610", "full_name": "Saskia Brindlecombe", "email": "saskia.brindlecombe@example.org", "phone": "+44 7700 900957", "account_status": "ACTIVE", "signup_channel": "organic_search"}','2026-07-14T11:40:00Z');
COMMIT;
