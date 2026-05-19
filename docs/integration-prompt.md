# Integrating with the video-detection service

*Hand this whole document to whoever — a developer or a coding agent — is
integrating an upstream app with the video-detection service. It is written to
be self-contained; no other context is needed.*

---

## Your task

You are integrating an app with the **video-detection service**: a self-hosted
system that takes a video clip and returns what (and *who*) is in it — object
detections plus recognised named people/animals.

Your app submits a video; the service processes it asynchronously and returns
the detections, either by calling a webhook you provide or in response to a
status poll. Implement that integration.

## How videos are passed: by path, not upload

Your app and the video-detection service run on the **same host** and share a
filesystem. Videos are **not** uploaded over HTTP — instead:

1. Your app writes the video file into the shared **intake directory**.
2. Your app calls `POST /api/jobs` with the *path* to that file.

**Prerequisite — agree the intake path with the video-detection operator.**
The service validates the submitted path against its configured
`VD_INTAKE_DIR` (default `/data/videos/intake`). The simplest setup: bind-mount
the shared intake directory into your container at that **same path**
(`/data/videos/intake`), so a path you write is a path the service accepts
verbatim. The path you send in `video_path` must be the absolute path **as the
video-detection service sees it**.

Do not write into the service's *watched* `inbox/` directory — that is for
manual drops and would create an uncorrelated duplicate. Use the intake
directory and the API.

## Base URL

The API is reachable on the LAN at `http://<video-detection-host>:10801` (port
is configurable — confirm with the operator). All paths below are under `/api`.
There is no authentication (single-user LAN service).

---

## Step 1 — Write the video

Write the clip into the shared intake directory and **fully close the file**
before the next step. Common containers (`.mp4`, `.mkv`, `.mov`) all work.
Use a unique filename so concurrent jobs do not collide.

## Step 2 — Submit the job

```
POST /api/jobs
Content-Type: application/json

{
  "source":       "unifi-protect",
  "video_path":   "/data/videos/intake/evt_8842.mp4",
  "external_id":  "evt_8842",
  "callback_url": "http://my-app:9000/hooks/video-detection",
  "metadata":     { "trigger": "person", "zone": "driveway" }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `source` | yes | Stable identifier for your app, 1–64 chars. Agree the value with the operator (e.g. `unifi-protect`, `family-archive`). |
| `video_path` | yes | Absolute path of the file, inside the intake directory, as the service sees it. |
| `external_id` | no | Your own record ID for this video, ≤255 chars. Strongly recommended — it is the correlation key and the idempotency key. |
| `callback_url` | no | `http(s)` URL the result is POSTed to when processing finishes. Omit if you will poll instead. |
| `metadata` | no | Arbitrary JSON object. Stored and echoed back; never interpreted. Put your app's own data here (see app-specific notes). |

**Response — `202 Accepted`:**

```json
{ "job_id": "0192f3a1-...-uuid", "status": "pending" }
```

`job_id` identifies the job for status polling. Processing has **not**
finished — it runs asynchronously (seconds to a few minutes).

**Idempotency.** Submitting again with the same `(source, external_id)` returns
the existing job (same `job_id`) instead of creating a duplicate. Safe to retry
on network failure.

**Errors — `422 Unprocessable Entity`:** the `video_path` does not exist, is
not inside the intake directory, or is not a file; or the body is malformed.
The response body has an `error`/`detail` describing the problem.

## Step 3 — Receive the result

Two ways — use whichever suits your app. The payload is identical either way.

### Option A — Webhook (recommended)

If you passed `callback_url`, the service sends:

```
POST <your callback_url>
Content-Type: application/json

<result payload — see below>
```

- Respond `2xx` promptly. A non-2xx or a timeout is retried with exponential
  backoff (default: up to 5 attempts), after which the delivery is abandoned —
  the result is still retrievable via Option B.
- Make your handler **idempotent**, keyed on `job_id` / `external_id`.
- Fired once per job, on completion **or** failure.

### Option B — Poll

```
GET /api/jobs/{job_id}
```

Poll every few seconds until `status` is terminal (`done` or `failed`). While
processing, the response carries only the status fields:

```json
{ "job_id": "...", "clip_id": "...", "source": "unifi-protect",
  "external_id": "evt_8842", "status": "detecting" }
```

`status` progresses `pending → extracting → detecting → done` (or `failed`).
`404` means the `job_id` is unknown.

---

## The result payload

Delivered to the webhook and returned by `GET /api/jobs/{job_id}` once terminal.

```json
{
  "job_id":      "0192f3a1-...-uuid",
  "clip_id":     "0192f3a1-...-uuid",
  "source":      "unifi-protect",
  "external_id": "evt_8842",
  "status":      "done",
  "clip":   { "duration_sec": 8.0, "width": 1920, "height": 1080 },
  "detections": [
    {
      "class":               "person",
      "subclass":            "Mallory",
      "confidence_class":     0.93,
      "confidence_subclass":  0.81,
      "frame_index":          4,
      "timestamp_sec":        4.0,
      "bbox": { "x": 0.10, "y": 0.20, "w": 0.20, "h": 0.50 }
    }
  ],
  "summary": {
    "classes":    [ { "class": "person", "frames": 7 } ],
    "subclasses": [ { "class": "person", "subclass": "Mallory",
                      "frames": 6, "best_confidence": 0.91 } ]
  }
}
```

| Field | Meaning |
|-------|---------|
| `status` | `done` — fields below are present. `failed` — an `error` string is present instead and `clip`/`detections`/`summary` are omitted. |
| `clip` | Source video properties. |
| `detections` | One entry per detected object, per sampled frame (the video is sampled at 1 frame/second). |
| `detections[].class` | Object category — `person`, `car`, `dog`, `bear`, or an operator-defined custom class. |
| `detections[].subclass` | The recognised named individual (e.g. a specific person or pet), or `null` if not recognised. |
| `detections[].confidence_class` / `confidence_subclass` | 0–1 confidence. `confidence_subclass` is `null` when there is no subclass. |
| `detections[].frame_index` | 1-based index of the sampled frame. |
| `detections[].timestamp_sec` | Offset of that frame into the clip. |
| `detections[].bbox` | Bounding box, **normalised 0–1**, top-left origin: `x,y` = corner, `w,h` = size. Multiply by `clip.width`/`height` for pixels. |
| `summary.classes` | Per class: number of distinct frames it appeared in. |
| `summary.subclasses` | Per recognised individual: frame count + best confidence. The "who/what appeared in this clip" roll-up. |

The result reflects the **current** labels. If a human later corrects the
clip in the review UI, a subsequent `GET /api/jobs/{job_id}` reflects the
correction; the webhook payload is the snapshot at completion time.

---

## App-specific notes

**Motion / security-event archiver (UniFi Protect, etc.)** — you want the
per-detection `detections` array (which objects, when, where). If you already
ran your own object detection, pass those results in `metadata`; the service
stores them for reference but runs its own pipeline — its value-add is the
named-individual recognition in `subclass`.

**Family-video archiver** — you mostly want `summary.subclasses`: the list of
recognised people/pets in the clip, for tagging. `summary.classes` tells you
what kinds of things appear; `detections` is available if you need per-frame
detail.

---

## End-to-end example

```bash
# 1. Your app has written /data/videos/intake/evt_8842.mp4 (file fully closed).

# 2. Submit.
curl -sS -X POST http://video-detection-host:10801/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
        "source": "unifi-protect",
        "external_id": "evt_8842",
        "video_path": "/data/videos/intake/evt_8842.mp4",
        "callback_url": "http://my-app:9000/hooks/video-detection",
        "metadata": { "trigger": "person", "zone": "driveway" }
      }'
# → {"job_id":"0192f3a1-...","status":"pending"}

# 3a. Receive the result at http://my-app:9000/hooks/video-detection — or:

# 3b. Poll.
curl -sS http://video-detection-host:10801/api/jobs/0192f3a1-...
# → {... "status":"done", "detections":[...], "summary":{...}}
```

## Checklist

- [ ] Intake directory mounted; the path you send matches what the service sees.
- [ ] Video file fully written and closed before `POST /api/jobs`.
- [ ] `source` value agreed with the operator; `external_id` set per video.
- [ ] Either a webhook receiver (idempotent, returns `2xx`) **or** a poll loop.
- [ ] Handle `status: "failed"` (read `error`) as well as `done`.
- [ ] Retry `POST /api/jobs` on transport failure — it is idempotent.
