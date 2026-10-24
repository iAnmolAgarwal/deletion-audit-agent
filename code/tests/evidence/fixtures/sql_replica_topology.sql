-- fixture point-in-time database snapshot
BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_primary" VALUES('analytics_6006','analytics_platform','customer_analytics_reports','{"resource_id":"analytics_6006","user_id":"user_9001","email":"ada.lovelace@example.test","metrics":{"sessions_30d":3}}','2026-05-13T10:00:00Z');
CREATE TABLE customer_data_read_replica (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_read_replica" VALUES('tombstone_9009','identity_service','deleted_customer_references','{"resource_id":"tombstone_9009","subject_reference":"user_9001","email":null}','2026-05-13T10:00:01Z');
COMMIT;
