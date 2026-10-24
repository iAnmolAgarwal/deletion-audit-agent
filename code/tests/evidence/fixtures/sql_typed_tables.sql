-- fixture snapshot
BEGIN TRANSACTION;
CREATE TABLE search_documents_primary (resource_id TEXT PRIMARY KEY, display_name TEXT, email TEXT, source_resource_id TEXT, indexed_at TEXT);
INSERT INTO "search_documents_primary" VALUES('search_2002','Ada Lovelace','ada.lovelace@example.test','account_1001','2026-05-14T22:12:00Z');
COMMIT;
