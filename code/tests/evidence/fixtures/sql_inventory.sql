PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES ('account_service', '2026-05-12T07:43:27Z');
INSERT INTO snapshot_scope VALUES ('search_service', '2026-05-12T07:43:27Z');
INSERT INTO customer_search_documents VALUES ('search_2002', 'user_9001', 'Ada Lovelace', 'ada.lovelace@example.test', '+44 20 7946 0001', NULL, 'customer_directory_v3', '2026-05-12T06:34:26Z');
COMMIT;
