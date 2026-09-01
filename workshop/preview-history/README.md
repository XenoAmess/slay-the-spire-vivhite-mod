# Workshop preview history

This directory is a tracked, append-only audit trail for `workshop/preview.jpg`.
The preview generator copies the previous image before replacing it. Each image
uses the deterministic name
`preview-v<version>-sha256-<full-lowercase-sha256>.jpg` and has an adjacent JSON
sidecar containing the version, full SHA-256, byte count, source hashes, and UTC
archive time. Existing history is never pruned or overwritten; a hash/name
collision fails closed.

`workshop/workshop-item.json` is the authority for the current preview version
and digest. Publishing always compares that record with the actual file, so
`-SkipPreview` cannot publish a stale or untracked image.
