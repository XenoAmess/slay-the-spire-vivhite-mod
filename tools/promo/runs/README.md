# Promo run storage

This directory is the project-owned runtime boundary for capture attempts. A
real recording creates a new `runs/<run-id>/` directory and keeps its raw
recording, per-stem audio, marks, evidence, logs, partial renders, and review
material together. Retries use a new run/attempt; they never overwrite an
earlier contract or deliverable.

The checked-in offline fixture lives under `fixtures/minimal_capture/` and is
not a playable recording. Do not commit real game media, credentials, or
temporary tool caches here unless a separately reviewed artifact policy allows
them.
