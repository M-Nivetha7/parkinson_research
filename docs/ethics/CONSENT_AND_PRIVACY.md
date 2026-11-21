# Consent and privacy (what is implemented)

Implemented and tested: pseudonymous participant codes; no names/emails in research records; consent required before
a session or upload; clinical groups require an active protocol AND consent matching the protocol's consent version;
withdrawal blocks further collection; clinical metadata readable/writable only by `research_admin` and audited;
participants only see their own records (others return 404); label changes and sensitive reads are audit-logged;
passwords hashed with scrypt; JWT with a required 32+ character secret from the environment.

NOT implemented (do not claim): encryption at rest, TLS configuration, secure backups, token revocation,
rate limiting, data retention enforcement, deletion on withdrawal, secure object storage, separate identity-store
service. The contact-details table exists but nothing writes to it.

Ethics: no ethics approval exists in this project. Do not enter fabricated approval details. Pilot mode is labelled
"Nonclinical testing only - not clinical validation". ParkiScribe makes no diagnosis and assigns no severity.
