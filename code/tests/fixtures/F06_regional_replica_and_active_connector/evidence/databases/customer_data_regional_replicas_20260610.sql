-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-06-10T11:40:00Z
-- Database topology: regional_replicas
-- Compare the primary and any replica tables for replication drift.

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
CREATE TABLE customer_data_replica_ap_south (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
CREATE TABLE customer_data_replica_eu_west (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        );
INSERT INTO "customer_data_primary" VALUES('search_900602','search_service','customer_search_documents','{"resource_id": "search_900602", "index_name": "customer_directory_v3", "document": {"display_name": "Odile Brand", "email": "odile.brand@example.com", "customer_reference": "user_900601"}}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_primary" VALUES('data_flow_900603','integration_service','connector_configurations','{"resource_id": "data_flow_900603", "connector_name": "crm_profile_sync_connector", "destination": "partner_crm_workspace", "subject_selector": "odile.brand@example.com", "enabled": true, "mode": "continuous_sync"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_primary" VALUES('audit_record_900604','security_service','security_audit_events','{"resource_id": "audit_record_900604", "subject_reference": "user_900601", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "8494f94517d23495290f2129c410b709a7752daf5506b6200aa97225ca2745db"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_ap_south" VALUES('search_900602','search_service','customer_search_documents','{"resource_id": "search_900602", "index_name": "customer_directory_v3", "document": {"display_name": "Odile Brand", "email": "odile.brand@example.com", "customer_reference": "user_900601"}}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_ap_south" VALUES('data_flow_900603','integration_service','connector_configurations','{"resource_id": "data_flow_900603", "connector_name": "crm_profile_sync_connector", "destination": "partner_crm_workspace", "subject_selector": "odile.brand@example.com", "enabled": true, "mode": "continuous_sync"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_ap_south" VALUES('audit_record_900604','security_service','security_audit_events','{"resource_id": "audit_record_900604", "subject_reference": "user_900601", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "8494f94517d23495290f2129c410b709a7752daf5506b6200aa97225ca2745db"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_eu_west" VALUES('search_900602','search_service','customer_search_documents','{"resource_id": "search_900602", "index_name": "customer_directory_v3", "document": {"display_name": "Odile Brand", "email": "odile.brand@example.com", "customer_reference": "user_900601"}}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_eu_west" VALUES('data_flow_900603','integration_service','connector_configurations','{"resource_id": "data_flow_900603", "connector_name": "crm_profile_sync_connector", "destination": "partner_crm_workspace", "subject_selector": "odile.brand@example.com", "enabled": true, "mode": "continuous_sync"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_eu_west" VALUES('audit_record_900604','security_service','security_audit_events','{"resource_id": "audit_record_900604", "subject_reference": "user_900601", "event_name": "account_deletion_reviewed", "actor_type": "automated_privacy_workflow", "integrity_seal": "8494f94517d23495290f2129c410b709a7752daf5506b6200aa97225ca2745db"}','2026-06-10T11:40:00Z');
INSERT INTO "customer_data_replica_eu_west" VALUES('account_900605','account_service','customer_profiles','{"resource_id": "account_900605", "customer_reference": "user_900601", "full_name": "Odile Brand", "email": "odile.brand@example.com", "phone": "+44 7700 900601", "account_status": "ACTIVE", "signup_channel": "organic_search"}','2026-06-10T11:40:00Z');
COMMIT;
