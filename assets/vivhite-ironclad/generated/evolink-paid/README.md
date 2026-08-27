# EvoLink paid-generation archive

This directory is append-only. Every EvoLink generation attempt must retain:

- the raw model output PNG;
- the exact prompt sent to the model;
- the non-secret request parameters actually sent to the API.

Attempts remain here even when rejected or unused. Never overwrite or delete a
prior attempt. API keys, authorization headers, temporary signed result URLs,
and other credentials must never be stored here.

Each attempt uses its own dated, numbered directory. Accepted art may be copied
to an active authoring path after Alpha and visual review; the archived raw
output remains unchanged.
