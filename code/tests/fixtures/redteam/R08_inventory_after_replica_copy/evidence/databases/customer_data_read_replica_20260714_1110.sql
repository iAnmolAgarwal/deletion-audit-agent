-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-07-14T11:10:00Z
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
INSERT INTO "customer_data_primary" VALUES('audit_record_9307103','security_service','security_audit_events','{"resource_id": "audit_record_9307103", "subject_reference": "user_930710", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "0b0ddd8fdfe377ea97e84558be3d6c809cbb2c59d79155c5463e97f85f12d027"}','2026-07-14T11:10:00Z');
INSERT INTO "customer_data_read_replica" VALUES('audit_record_9307103','security_service','security_audit_events','{"resource_id": "audit_record_9307103", "subject_reference": "user_930710", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "0b0ddd8fdfe377ea97e84558be3d6c809cbb2c59d79155c5463e97f85f12d027"}','2026-07-14T11:10:00Z');
INSERT INTO "customer_data_read_replica" VALUES('account_9307101','account_service','customer_profiles','{"resource_id": "account_9307101", "customer_reference": "user_930710", "full_name": "Ottilie Grisewood", "email": "ottilie.grisewood@example.com", "phone": "+44 7700 900958", "account_status": "ACTIVE", "signup_channel": "organic_search"}','2026-07-14T11:10:00Z');
COMMIT;
