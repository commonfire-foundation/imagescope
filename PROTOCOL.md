# Imagescope protocol 1

Both event envelopes and results are versioned independently. Initial versions:
`protocol_version: 1`, `schema_version: 1`. Consumers reject unsupported versions,
not guess at their meaning. Additive fields may be ignored within version 1;
required field removal or incompatible type/meaning changes require a new version.

## Discovery and requests

`imagescope info --json` returns program/version, protocol/schema versions,
default model, and the shipped profile's version and exact prompt. It does not
contact Ollama. Consumers may snapshot those fields for queued work.

One process handles one image request. Task is `describe` or `inspect`. File input
and `--stdin` are mutually exclusive. Settings: `--profile wallpaper`, `--model`,
`--preview-size` (256/512/768/1024), `--measurements`, `--timeout` (0 < seconds <=
3600), and `--keep-alive` (integer seconds 0..86400). The endpoint includes the
Ollama API path. Nonlocal endpoint configuration is explicit opt-in to remote use.

Process clients can pass `--protocol-version 1`, `--expect-profile-version`, and
`--expect-prompt-sha256` to reject changed task definitions before inference.
These snapshot guards are primarily for batch consumers. A model name is not a
content pin: the response reports the inventory's actual model identity/digest.

## Terminal result

Every terminal result has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer 1 |
| `status` | `ok` or `error` |
| `input` | `path` (absolute string or null for bytes); after decoding: SHA-256 of encoded bytes, oriented dimensions, aspect ratio, format, frame count, alpha presence |
| `measurements` | Object or null; luminance mean/std, palette, dHash64, 3×3 edge density |
| `predictions` | Wallpaper description object or null |
| `provenance` | Task; description results additionally record backend, model inventory entry/digest, Ollama version, profile/version/prompt, preprocessing and generation settings |
| `diagnostics` | Bounded diagnostics; backend timing and response termination details where available |
| `elapsed_seconds` | Nonnegative finite elapsed time; may be zero for preflight/client failures |
| `error` | null on success, otherwise `{ "code": "...", "message": "..." }` |

Preprocessing is versioned, and requested measurements record a measurements
version. No application/database/job IDs are part of this contract. Callers attach
their own correlation IDs to the process they launch.

Wallpaper predictions contain required fields: `caption`, `subjects`, `medium`,
`mood`, `lighting`, `composition`, `tags`, `text_present`, `watermark_present`.
Their schema and validation live in `imagescope/profiles/wallpaper.py`.

Measurements/input/provenance can remain populated after a model failure. A failed
request is still `status: error`: consumers must not mistake partial data for a
successful description or replace a good prior prediction with it. Diagnostics
may preserve pre-cleanup labels and at most 8192 characters of invalid final model
output. Internal model thinking text is never included.

## Event stream

`--events=jsonl` emits UTF-8 JSON, one record per line, flushed as stages change:

```json
{"protocol_version":1,"type":"hello","schema_version":1}
{"protocol_version":1,"type":"progress","stage":"checking","label":"Checking local model"}
{"protocol_version":1,"type":"progress","stage":"preparing","label":"Preparing image"}
{"protocol_version":1,"type":"progress","stage":"generating","label":"Generating image description"}
```

The final record has `type: "result"` and a `result` field containing the complete
terminal object above. Exactly one hello and terminal result are expected, and
nothing may follow the terminal result. Inspect omits model-related progress;
failures may end at any stage. Labels are human-readable and are not stable codes.
No percentages, token-content stream, or job-control commands are implied.

The desktop reader accepts at most 1 MiB per event and 2 MiB per request stream,
requires newline termination, and bounds captured diagnostic stderr. It fails the
job on malformed output, duplicate terminal results, missing hello/result,
incompatible versions, process crashes, or a success record with nonzero exit.
The desktop additionally verifies source path, requested model/profile/prompt,
and requested measurement presence before storage, and rechecks its own source
fingerprint before committing. Inference progress belongs to the launching job.

## Exit codes and errors

- `0`: successful request.
- `1`: input, backend, or inference failure.
- `2`: invalid invocation/request or incompatible requested protocol.
- `130`: cooperative cancellation.

Argument-parser errors print usage on stderr and may exit without a JSON result.
Hard crashes/kills may also lack a terminal record. Consumers must observe **both**
the terminal record and process exit, with their own deadline.

Initial error codes: `invalid_request`, `incompatible_protocol`, `analyzer_changed`,
`invalid_input`, `unsupported_image`, `input_too_large`, `image_too_large`,
`source_changed`, `model_missing`, `backend_unavailable`, `backend_error`,
`invalid_response`, `timeout`, `cancelled`, `analysis_failed`. New error codes may
be added; unknown codes must still be treated as failures. English messages can
change. Client-side malformed-result validation uses `protocol_error`.

The analyzer has no persistence, retry queue, hotkey, clipboard, screenshot, or
notification interface. Those policies belong to its consumers.
