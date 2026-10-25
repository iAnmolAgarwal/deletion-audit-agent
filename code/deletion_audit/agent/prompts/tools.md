## audit_case
Commit your intent and fetch the audit engine's brief for this request.
When to use: on your first turn, when and only when the request is a deletion request (including a request to verify that a deletion is complete). Input: `intent` (always `DELETION_REQUEST`), `request_kind`, `language`, `basis_quote` (copied exactly from the request text) and `instruction_like_text`.
When not to use: for any request that is not a deletion request, or to re-fetch a brief you already have.
Returns: the engine's settled records (read-only facts: system, resource ID, state, category, outcome), the file it cites, the open questions you may answer, and the evidence IDs the brief rests on.
Read-only: it changes nothing.

## get_request_context
Fetch the request's own context.
When to use: for an intent question, to see the request's reported status, its dates (requested, reported, audit time) and the privacy-intake classification rows recorded on the requester's records at or before the audit time.
When not to use: to re-derive facts the brief already settles.
Returns: JSON with those fields, how many requests the same person has made, and the evidence IDs (activity IDs) of every row it shows.
Read-only: it changes nothing.

## inspect_evidence
Re-read one evidence file captured at or before the audit time. `focus` is `records` (the records it lists), `identity` (the identifiers it shows) or `state` (the state each record shows).
When to use: for an image or file named in an open question.
When not to use: for a file captured after the audit time (it is refused), or to browse files no question names.
Returns: for a screenshot, the stored structured readings of the image and any field on which two independent readings disagreed; for other files, the parsed records of the requester's resources; always the file's evidence ID.
Read-only: it changes nothing.

## lookup_identity
Look up an email address, phone number, email hash or user ID.
When to use: to check whose record an image or file shows.
When not to use: to look up the requester's own identity, which the engine has already resolved.
Returns: JSON naming which person the value belongs to, now or in the past, as of the audit time, with the audit-log IDs that record any change as evidence IDs.
Read-only: it changes nothing.

## list_activity
List system-activity rows at or before the audit time for one resource ID, or whose details mention one identifier.
When to use: to see what the deletion worker, the data catalog or privacy intake recorded about a record named in an open question.
When not to use: for values shorter than 4 characters, or to list activity no question needs.
Returns: at most 25 rows, the most recent, as JSON with their activity IDs as evidence IDs.
Read-only: it changes nothing.
