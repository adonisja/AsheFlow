# ADR-008: Field Operations Data Model and Mobile Camera Compatibility

## Status
Accepted

## Context

Three new operational features were added to the Field Operations page: employee check-in (with photo), departure (with itinerary photo), and driver ratings of walkers (with star rating + comment). These features require photo capture in the browser today, but the project intends to ship a mobile app in the future using the same backend. Two architectural decisions needed to be made:

1. **How to store photos** captured by employees in the field (check-in selfie, itinerary photo).
2. **How to implement camera capture** in a way that doesn't lock out a future React Native / Expo build sharing this codebase.

---

## Considered Options

### Photo Storage

**Option A: Store as base64 data-URI strings in Postgres (`Text` column)**
- Photos are encoded client-side via `FileReader.readAsDataURL()` and stored directly in the DB row.
- Simple — no external services, no additional infrastructure.
- Works identically from web and mobile.

**Option B: Upload to S3 / object storage, store the URL**
- Photos are sent to an S3 bucket, the DB stores the resulting URL string.
- Scales to large files and many employees without bloating the DB.
- Requires AWS credentials, presigned URL logic, and additional infrastructure.

**Option C: Store photos on the server filesystem via multipart upload**
- FastAPI receives a `multipart/form-data` file upload and writes it to disk.
- Avoids S3 costs but creates a statefulness problem — photos are tied to a single server instance, incompatible with horizontal scaling or Docker volume changes.

### Camera Input on Web

**Option A: `<input type="file" accept="image/*" capture="environment" />`**
- On mobile browsers, opens the rear camera directly.
- On mobile, completely bypasses the photo library — user cannot select an existing photo.
- On desktop, opens the file picker.

**Option B: `<input type="file" accept="image/*" />` (no `capture` attribute)**
- On mobile browsers, presents a system action sheet: camera or photo library.
- On desktop, opens the file picker.
- Works correctly on both platforms and does not restrict user choice.

---

## Trade-offs

| | Option A (base64 Postgres) | Option B (S3) | Option C (filesystem) |
|---|---|---|---|
| Complexity | Low | High | Medium |
| Infrastructure | None | AWS S3 | Server disk |
| Scalability | Poor for large files | Excellent | Poor |
| MVP fit | ✅ | Overkill | ❌ |
| Mobile compatible | ✅ | ✅ | ✅ |

The `photo_url` column is typed as `Text` (nullable), so a future migration to S3 URLs requires no schema change — only the upload logic changes.

---

## Decision

**Photo storage:** Option A — base64 data-URI stored as `Text` in Postgres, for MVP. The column is named `photo_url` / `itinerary_photo_url` to signal future intent: the value will eventually be a real URL pointing to S3, not a data-URI. No schema migration will be needed when that switch happens.

**Camera input:** Option B — no `capture` attribute. Mobile users get camera-or-library choice; desktop users get the file picker. This is the least restrictive and most portable approach.

---

## Consequences

- **Tech debt:** Base64 images stored in Postgres will cause row bloat at scale. Before production, these should be migrated to S3 presigned uploads. The column name `photo_url` signals this intent.
- **Mobile (React Native / Expo):** The `<input>` element won't exist in a native context. Replace with `expo-image-picker` or `expo-camera` for the capture UI. All downstream code — base64 encoding, `axiosClient` calls, backend endpoints — is reusable without modification.
- **No new AWS infrastructure required for MVP** — check-in and departure photos are operational immediately without S3 setup.

---

## Learnings & Growth

- Naming a column `photo_url` even when storing a data-URI enforces the right mental model and prevents future devs from treating it as a permanent format.
- The `capture` HTML attribute is a footgun on mobile: it feels like the "correct" thing to do for a camera feature, but it removes user agency. Always prefer the no-`capture` default unless you have a specific reason to force camera-only.
- A shared web/mobile codebase is viable here because the architecture separates concerns cleanly: auth context, API client, and backend endpoints are all platform-agnostic. Only the view layer (camera UI) needs to change for native.
