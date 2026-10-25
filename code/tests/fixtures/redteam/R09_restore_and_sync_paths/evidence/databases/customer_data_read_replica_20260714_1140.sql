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
INSERT INTO "customer_data_primary" VALUES('data_flow_9308203','integration_service','connector_configurations','{"resource_id": "data_flow_9308203", "connector_name": "loyalty_partner_feed", "destination": "partner_loyalty_workspace", "subject_selector": "+44 7700 900961", "enabled": true, "mode": "continuous_sync"}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_primary" VALUES('audit_record_9308204','security_service','security_audit_events','{"resource_id": "audit_record_9308204", "subject_reference": "user_930820", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "eda79b92b23ccf3e5b700278dd8aff431afe5f0d0374f584e772512a5c7ab42a"}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('data_flow_9308203','integration_service','connector_configurations','{"resource_id": "data_flow_9308203", "connector_name": "loyalty_partner_feed", "destination": "partner_loyalty_workspace", "subject_selector": "+44 7700 900961", "enabled": true, "mode": "continuous_sync"}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('audit_record_9308204','security_service','security_audit_events','{"resource_id": "audit_record_9308204", "subject_reference": "user_930820", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "eda79b92b23ccf3e5b700278dd8aff431afe5f0d0374f584e772512a5c7ab42a"}','2026-07-14T11:40:00Z');
COMMIT;
