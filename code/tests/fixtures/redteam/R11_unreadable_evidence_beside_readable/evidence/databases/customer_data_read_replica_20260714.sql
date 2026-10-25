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
INSERT INTO "customer_data_primary" VALUES('support_9310203','support_platform','support_conversations','{"resource_id": "support_9310203", "ticket_id": "CS-9310203", "subject_reference": "user_931020", "requester_name": "Bettany Crewe", "requester_email": "bettany.crewe@example.org", "channel": "email", "message_text": "Customer asked for a refund on a late order."}','2026-07-14T11:40:00Z');
INSERT INTO "customer_data_read_replica" VALUES('support_9310203','support_platform','support_conversations','{"resource_id": "support_9310203", "ticket_id": "CS-93
