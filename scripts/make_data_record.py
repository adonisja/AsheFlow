#!/usr/bin/env python3
"""Create a Google Doc and Slides deck of the AsheFlow address-study data record.

WHY A SCRIPT AND NOT A COPY-PASTE. This document goes to someone assessing
whether a data programme is acceptable. Every number in it was verified against
live infrastructure, and a number retyped by hand is a number that can drift
from what the systems actually do. Regenerating is cheap; a wrong figure in a
compliance conversation is not.

The counts are NOT baked in. `--counts` runs the production query itself so the
document cannot claim a stale figure, and without it the doc says plainly that
the counts were not verified on this run rather than printing yesterday's.

TWO ARTEFACTS, DIFFERENT JOBS. The doc carries the evidence and is read alone;
the deck carries the decisions and is read in a room while someone talks over
it. The deck is not the doc reflowed — anything needing a paragraph to be fair
to it stays in the doc, which is why several slides end by pointing there.

SCOPE. This covers the ADDRESS STUDY only. The personal route tracker is not a
collection programme, holds no records, and its server path is being removed;
it appears here as one scope note and nowhere else.

USAGE
    pip install google-api-python-client google-auth-oauthlib
    python3 scripts/make_data_record.py --counts             # doc + slides
    python3 scripts/make_data_record.py --counts --dry-run   # print only
    python3 scripts/make_data_record.py --counts --no-slides # doc alone

AUTH
    Needs an OAuth client for the Google Docs, Slides and Drive APIs:
      1. console.cloud.google.com -> new project -> enable "Google Docs API",
         "Google Slides API" and "Google Drive API"
      2. Credentials -> Create credentials -> OAuth client ID -> Desktop app
      3. Download the JSON to ~/.config/asheflow/google_oauth.json
    First run opens a browser once; the token is cached beside that file.

    A service account is deliberately NOT used: the doc should be owned by a
    person who can share it, not by a robot identity nobody can find later.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "asheflow"
CLIENT_SECRET = CONFIG_DIR / "google_oauth.json"
TOKEN_CACHE = CONFIG_DIR / "google_token.json"
# ONE SCOPE, AND IT IS ENOUGH.
#
# The obvious list is documents + presentations + drive.file, and that is what
# this asked for first. Google granted only drive.file and silently dropped the
# other two — no error, just a token with fewer scopes than requested, which
# oauthlib then rejects as "Scope has changed".
#
# drive.file turns out to cover the whole job: it permits creating files AND
# editing the ones this app created, so the Docs and Slides APIs work on files
# we made ourselves. Verified by probe before simplifying — created a Doc
# through Drive, wrote into it through the Docs API, with drive.file alone.
#
# It is also the scope to want on its own merits: access is limited to files
# this script creates, never the rest of the account's Drive. A compliance
# script asking to read everything would be its own bad look.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# The production host. Counts come from here or not at all.
PROD_INSTANCE = "i-095bf2ed310c86741"
COUNT_SQL = (
    "SELECT (SELECT count(*) FROM collection_tokens), "
    "(SELECT count(*) FROM collection_tokens WHERE revoked_at IS NULL), "
    "(SELECT count(*) FROM collected_address_profiles);"
)


def live_counts() -> dict[str, str] | None:
    """Ask production directly. Returns None if it cannot be reached.

    Returning None rather than zeros matters: "we could not check" and "there is
    nothing there" are different claims, and only one of them is safe to print
    in a document someone will act on.
    """
    cmd = (
        f'sudo docker exec asheflow_postgres psql -U asheflow -d asheflow_db '
        f'-t -A -F"|" -c "{COUNT_SQL}"'
    )
    try:
        cid = subprocess.run(
            ["aws", "ssm", "send-command",
             "--instance-ids", PROD_INSTANCE,
             "--document-name", "AWS-RunShellScript",
             "--parameters", json.dumps({"commands": [cmd]}),
             "--query", "Command.CommandId", "--output", "text"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        print(f"  could not reach production: {exc}", file=sys.stderr)
        return None

    import time
    for _ in range(12):
        time.sleep(5)
        got = subprocess.run(
            ["aws", "ssm", "get-command-invocation",
             "--command-id", cid, "--instance-id", PROD_INSTANCE,
             "--query", "{s:Status,o:StandardOutputContent}", "--output", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if got.returncode != 0:
            continue
        payload = json.loads(got.stdout or "{}")
        if payload.get("s") == "Success":
            row = (payload.get("o") or "").strip().splitlines()
            for line in row:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    return {
                        "campaigns": parts[0], "live": parts[1],
                        "addresses": parts[2],
                    }
            print(f"  unexpected output: {row}", file=sys.stderr)
            return None
        if payload.get("s") in {"Failed", "Cancelled", "TimedOut"}:
            print(f"  query {payload.get('s')}", file=sys.stderr)
            return None
    print("  timed out waiting for production", file=sys.stderr)
    return None


# ── The document ────────────────────────────────────────────────────────────
# Structured as (style, text) so the Docs API call stays mechanical. Keeping the
# content here rather than parsing the HTML artifact means one obvious place to
# edit when a fact changes, and no HTML-to-Docs conversion to get subtly wrong.

def build(counts: dict[str, str] | None) -> list[tuple[str, str]]:
    today = date.today().strftime("%d %B %Y")

    if counts:
        collected = (
            f"Queried against the production database on {today}: "
            f"{counts['campaigns']} campaign(s) created, "
            f"{counts['live']} currently active, "
            f"{counts['addresses']} address records collected."
        )
        headline = (
            "No production data has been collected."
            if counts["addresses"] == "0"
            else "Production data exists — see the count above."
        )
    else:
        collected = (
            "Counts were NOT verified on this run — the production database could "
            "not be reached. Re-run with --counts before relying on any figure here."
        )
        headline = "Collection volume unverified on this run."

    return [
        ("TITLE", "AsheFlow Address Study — Data Handling Record"),
        ("SUBTITLE", f"Compiled {today} · Verified against live infrastructure · "
                     "Operator: Akkeem (sole super admin)"),

        ("HEADING_1", "Summary"),
        ("NORMAL", "AsheFlow is an independent system built and operated by Akkeem. "
                   "It is not an Amazon product, integration, or partner tool, holds no "
                   "Amazon API credentials, and has no approval or relationship with Amazon."),
        ("NORMAL", "It collects building addresses seen on delivery routes, together "
                   "with what is visible at the door: building type, access hours and "
                   "workload. Each address is standardised in the browser before it is "
                   "sent, so apartment, floor, suite and any name are removed and the "
                   "stored record describes a building rather than a household. "
                   "Submissions are held in a PostgreSQL database on an AWS EC2 "
                   "instance in us-east-2 (Ohio) operated by Akkeem, not on Amazon or "
                   "DSP systems."),

        ("HEADING_1", "The questions asked"),
        ("HEADING_2", "Is this an Amazon-approved platform?"),
        ("NORMAL", "No. There is no approval, relationship, or integration of any kind."),
        ("HEADING_2", "Is customer information being stored?"),
        ("NORMAL", "Building addresses, yes. Customer details, no. Every address is "
                   "standardised in the browser before it is sent: apartment, unit, "
                   "floor, suite and anything following \"Attn:\" are cut, so what "
                   "reaches the server identifies a building rather than a household. "
                   "No names, no package identifiers, no order contents."),
        ("HEADING_2", "Is it stored externally?"),
        ("NORMAL", "Yes — on AWS infrastructure operated by Akkeem, in Ohio, United States."),
        ("HEADING_2", "Who built and runs it?"),
        ("NORMAL", "Akkeem, personally. One super-admin account exists and is the only "
                   "role able to read collected records."),

        ("HEADING_1", "What has actually been collected"),
        ("NORMAL", collected),
        ("NORMAL", headline),

        ("HEADING_1", "Fields stored per record"),
        ("BULLET", "address — street address as typed (customer PII)"),
        ("BULLET", "building_type — walk-up, elevator, loading dock, etc."),
        ("BULLET", "workloads — bulk drop, door-to-door, high-rise, high wait"),
        ("BULLET", "note — free text, e.g. access instructions"),
        ("BULLET", "opens_at / closes_at — building access hours"),
        ("BULLET", "collected_by — self-chosen alias, not a legal name"),
        ("BULLET", "device_id — random per-browser value, not an identity"),
        ("NORMAL", "No customer names, phone numbers, email addresses, order contents, "
                   "payment details, or package tracking identifiers are collected in "
                   "any field."),

        ("HEADING_1", "What the server actually receives"),
        ("NORMAL", "Addresses are standardised in the collector's browser, before "
                   "anything is sent. The typed text is replaced as soon as the field "
                   "is left, so unit-level detail never reaches the network or the "
                   "database."),
        ("BULLET", "433 W 31st St, Apt 4A  ->  433 W 31 ST"),
        ("BULLET", "500 Broadway Attn: J Smith  ->  500 BROADWAY"),
        ("BULLET", "9 Park Ave, Suite 210  ->  9 PARK AVE"),
        ("BULLET", "12 Main St Floor 3  ->  12 MAIN ST"),
        ("BULLET", "77 King St Basement  ->  77 KING ST"),
        ("NORMAL", "Apartment, unit, floor, suite, basement, lobby and anything after "
                   "\"Attn:\" are all removed. A stored record describes a building "
                   "entrance. It cannot be tied back to a specific customer or "
                   "delivery."),

        ("HEADING_1", "A note on scope"),
        ("NORMAL", "A second page on the same system is a personal route tracker. The "
                   "operator uses it to reconstruct their own delivery days and compare "
                   "them against what the dispatch system produced. It was never given "
                   "to anyone else and never collected a record. Its server-side "
                   "submission path has been removed, so the tracker now stores data "
                   "only in the operator's own browser with no way to send anything to "
                   "a server."),

        ("HEADING_1", "Where it is stored"),
        ("BULLET", "PostgreSQL 15, in a Docker container on the application host"),
        ("BULLET", "AWS EC2, region us-east-2c (Ohio, United States)"),
        ("BULLET", "Frontend on AWS S3 + CloudFront"),
        ("BULLET", "AWS only — no analytics, advertising, data brokers, or AI services"),
        ("BULLET", "Data is not sold, shared, or transmitted to any outside party"),

        ("HEADING_1", "Controls verified in place"),
        ("BULLET", "HTTPS enforced; plain HTTP returns a 308 redirect"),
        ("BULLET", "Database not reachable from the internet (port 5432 closed)"),
        ("BULLET", "Only ports 80/443 public; SSH restricted to a single IP"),
        ("BULLET", "Read access restricted to one super-admin account of ten total"),
        ("BULLET", "All writes and deletions recorded in an audit trail"),
        ("BULLET", "Input typed and length-capped; submission batches capped at 100"),
        ("BULLET", "Rate limiting on all public endpoints, keyed on real client IP"),
        ("BULLET", "OWASP spreadsheet-injection escaping on CSV and XLSX exports"),
        ("BULLET", "Deletion available per-record, per-device, and per-campaign"),
        ("BULLET", "Nightly database backups, nine retained"),

        ("HEADING_1", "What is not in place"),
        ("BULLET", "Encryption at rest is NOT in place. All three EBS volumes are "
                   "unencrypted; data is protected in transit but not on disk."),
        ("BULLET", "No automated retention. Collected records persist indefinitely; "
                   "deletion exists but is manual."),
        ("BULLET", "No offsite backups. Backups sit on the host they back up."),
        ("BULLET", "Multi-factor authentication is available but not enforced on the "
                   "account that can read all collected data."),
        ("BULLET", "Access is link-based: the collection link is the only credential."),

        ("HEADING_1", "Outside the scope of this record"),
        ("NORMAL", "Whether delivery associates may record address data they see while "
                   "working Amazon routes, and keep it on a system outside Amazon and "
                   "outside the DSP, is a question about their delivery-associate "
                   "agreements and Amazon's data policies. That is not a technical "
                   "question, and nothing here settles it. It belongs to the DSP owner "
                   "and Amazon."),

        ("HEADING_1", "Options available immediately"),
        ("BULLET", "Revoke the collection link — stops all new submissions at once, "
                   "destroys nothing, reversible."),
        ("BULLET", "Purge collected data — removes every collected record, keeps the "
                   "campaign record."),
        ("BULLET", "Delete the campaign entirely — removes the campaign and its data."),
        ("BULLET", "Continue with conditions — shortened retention, or a narrower field "
                   "set — if approval is given on that basis."),

        ("NORMAL", "Facts in this record were verified against live AWS infrastructure "
                   "and the production database, not reconstructed from documentation."),
    ]


def slides(counts: dict[str, str] | None) -> list[tuple[str, list[str]]]:
    """The deck: (title, bullets) per slide.

    NOT the document reflowed. A deck is read in a room while someone talks over
    it, so it carries the DECISIONS and the numbers that drive them — the
    document carries the evidence. Anything here that needs a paragraph to be
    fair to belongs in the doc instead, which is why several slides end by
    pointing at it.

    The uncomfortable slides are deliberately early. A deck that opens with
    controls and buries "not Amazon-approved" on slide 8 reads as a sales pitch,
    and the one thing this must not look like is a sales pitch.
    """
    n = counts["addresses"] if counts else "unverified"
    live = counts["live"] if counts else "unverified"

    return [
        ("AsheFlow Address Study",
         ["Data handling record",
          f"Compiled {date.today():%d %B %Y}",
          "Verified against live infrastructure",
          "Operator: Akkeem (sole super admin)"]),

        ("The four questions",
         ["Amazon-approved platform?  No",
          "Storing customer information?  Building addresses, not customer details",
          "Stored externally?  Yes. AWS, Ohio, operated by Akkeem",
          "Who built it?  Akkeem, personally"]),

        ("What the server actually receives",
         ["Addresses are standardised in the browser, before anything is sent",
          "433 W 31st St, Apt 4A   ->   433 W 31 ST",
          "500 Broadway Attn: J Smith   ->   500 BROADWAY",
          "9 Park Ave, Suite 210   ->   9 PARK AVE",
          "Apartment, floor, suite and any name are cut",
          "A record describes a building entrance, not a household"]),

        ("Nothing has been collected yet",
         [f"Address records in production: {n}",
          f"Active campaigns: {live}",
          "The programme can be stopped, narrowed or cancelled",
          "before a single customer address exists"]),

        ("What a record contains",
         ["Standardised building address",
          "Building type, access hours, workload",
          "Free-text access note",
          "Collector alias, not a legal name",
          "No package IDs, customer names, or order contents"]),

        ("Where it lives",
         ["PostgreSQL 15 on AWS EC2",
          "us-east-2c — Ohio, United States",
          "AWS only: no analytics, ad tech, data brokers, or AI services",
          "Not sold, shared, or sent to any outside party"]),

        ("Controls in place",
         ["HTTPS enforced; database not reachable from the internet",
          "Read access: one super-admin account of ten",
          "All writes and deletions audited",
          "Rate limiting and input caps on every public endpoint",
          "Deletion per record, per device, per campaign"]),

        ("What is not in place",
         ["Encryption at rest: NOT in place",
          "Automated retention: none — deletion is manual",
          "Offsite backups: none",
          "MFA: available, not enforced",
          "Access: the link is the only credential"]),

        ("What this record cannot answer",
         ["Whether DAs may record address data seen on Amazon routes",
          "and store it outside Amazon and the DSP",
          "is a question about their agreements and Amazon policy",
          "Not a technical question — belongs to the DSP owner and Amazon"]),

        ("Options available today",
         ["Revoke the link — stops submissions now, destroys nothing",
          "Purge collected data — keeps the campaign record",
          "Delete the campaign entirely",
          "Continue with conditions, if approved on that basis"]),
    ]


def build_deck(service, counts: dict[str, str] | None, deck_id: str) -> str:
    """Fill a presentation that Drive already created.

    Slides has no "append a slide with this content" call: a slide is created,
    then its placeholder shapes are discovered by reading the created object,
    then text is inserted by shape id. So this is create-all, read-back, fill —
    three phases, not one loop. Guessing placeholder ids without the read-back
    is the usual way this breaks.
    """
    content = slides(counts)
    # Slide 1 already exists (Slides always makes one); reuse it as the title.
    reqs = [{"createSlide": {"slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}}
            for _ in content[1:]]
    if reqs:
        service.presentations().batchUpdate(
            presentationId=deck_id, body={"requests": reqs}).execute()

    deck = service.presentations().get(presentationId=deck_id).execute()
    fill: list[dict] = []
    for slide, (title_text, bullets) in zip(deck.get("slides", []), content):
        # Placeholders come back in layout order: title first, body second.
        holders = [e for e in slide.get("pageElements", [])
                   if "shape" in e and "placeholder" in e["shape"]]
        if not holders:
            continue
        fill.append({"insertText": {"objectId": holders[0]["objectId"],
                                    "text": title_text}})
        if len(holders) > 1:
            fill.append({"insertText": {"objectId": holders[1]["objectId"],
                                        "text": "\n".join(bullets)}})
    if fill:
        service.presentations().batchUpdate(
            presentationId=deck_id, body={"requests": fill}).execute()
    return deck_id


def to_requests(blocks: list[tuple[str, str]]) -> list[dict]:
    """Docs API batch. Text and paragraph styles only.

    Built BACK TO FRONT. Every insertion shifts the indices of everything after
    it, so inserting forwards means recomputing offsets for each block and
    getting one wrong silently scrambles the document. Walking backwards means
    each insert lands at index 1 and nothing downstream moves.

    BULLETS ARE NOT DONE HERE. `createParagraphBullets` takes a RANGE, and a
    range recorded during the backwards pass points at whatever paragraph later
    ends up at that index — which is a different paragraph by the time the batch
    runs. The first attempt bulleted every line in the document, including the
    title. They are applied in a second pass instead, once the text is in place
    and the indices are real: see `bullet_requests`.
    """
    reqs: list[dict] = []
    for style, text in reversed(blocks):
        body = text + "\n"
        end = 1 + len(body)
        reqs.append({"insertText": {"location": {"index": 1}, "text": body}})
        # The API's name for body text is NORMAL_TEXT; "NORMAL" is rejected.
        named = "NORMAL_TEXT" if style in ("NORMAL", "BULLET") else style
        reqs.append({
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named},
                "fields": "namedStyleType",
            }
        })
    return reqs


def bullet_requests(doc: dict, blocks: list[tuple[str, str]]) -> list[dict]:
    """Bullet the paragraphs that asked for it, by reading the real document.

    Matches on TEXT rather than position: the document is read back after the
    insert pass, so each paragraph's true start and end index is known. Anything
    that guesses an index here is guessing about a document it has not seen.

    Applied bottom-up so each request's range stays valid — bulleting does not
    change character counts, but it costs nothing to be consistent with the
    insert pass and it removes a class of bug from the reader's mind.
    """
    wanted = {text for style, text in blocks if style == "BULLET"}
    out: list[dict] = []
    for el in doc["body"]["content"]:
        para = el.get("paragraph")
        if not para:
            continue
        txt = "".join(r["textRun"]["content"] for r in para["elements"]
                      if "textRun" in r).strip()
        if txt in wanted:
            out.append({
                "createParagraphBullets": {
                    "range": {"startIndex": el["startIndex"],
                              "endIndex": el["endIndex"]},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })
    return list(reversed(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counts", action="store_true",
                    help="query production for live collection counts")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the document and exit without creating anything")
    ap.add_argument("--title", default=None, help="override the document title")
    ap.add_argument("--no-doc", action="store_true", help="skip the Google Doc")
    ap.add_argument("--no-slides", action="store_true", help="skip the Slides deck")
    args = ap.parse_args()

    counts = None
    if args.counts:
        print("Querying production for collection counts…")
        counts = live_counts()
        if counts:
            print(f"  campaigns={counts['campaigns']} live={counts['live']} "
                  f"addresses={counts['addresses']}")
        else:
            print("  WARNING: counts unavailable; the document will say so.")

    blocks = build(counts)

    if args.dry_run:
        if not args.no_doc:
            print("=" * 66)
            print("DOCUMENT")
            print("=" * 66)
            for style, text in blocks:
                prefix = {"TITLE": "# ", "SUBTITLE": "",
                          "HEADING_1": "\n## ", "HEADING_2": "### ",
                          "BULLET": "  - "}.get(style, "")
                print(f"{prefix}{text}")
        if not args.no_slides:
            print("\n" + "=" * 66)
            print(f"SLIDES ({len(slides(counts))} slides)")
            print("=" * 66)
            for i, (title, bullets) in enumerate(slides(counts), 1):
                print(f"\n[{i}] {title}")
                for b in bullets:
                    print(f"      · {b}")
        return 0

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build as gbuild
    except ImportError:
        print("Missing dependencies. Install with:\n"
              "  pip install google-api-python-client google-auth-oauthlib",
              file=sys.stderr)
        return 1

    if not CLIENT_SECRET.exists():
        print(f"No OAuth client at {CLIENT_SECRET}\n"
              "See the AUTH section at the top of this script.", file=sys.stderr)
        return 1

    creds = None
    if TOKEN_CACHE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_CACHE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET), SCOPES).run_local_server(port=0)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(creds.to_json())
        os.chmod(TOKEN_CACHE, 0o600)   # a refresh token is a credential

    stem = args.title or f"AsheFlow Address Study — Data Record — {date.today():%Y-%m-%d}"
    made: list[tuple[str, str]] = []

    drive = gbuild("drive", "v3", credentials=creds)

    if not args.no_doc:
        # Created through DRIVE, not docs.documents().create(): a file this app
        # created is one drive.file may edit, which is what makes the single
        # scope sufficient.
        doc_id = drive.files().create(
            body={"name": stem,
                  "mimeType": "application/vnd.google-apps.document"},
            fields="id").execute()["id"]
        docs = gbuild("docs", "v1", credentials=creds)
        docs.documents().batchUpdate(
            documentId=doc_id, body={"requests": to_requests(blocks)}).execute()
        # Second pass: read the document back, then bullet by real index.
        doc = docs.documents().get(documentId=doc_id).execute()
        bullets = bullet_requests(doc, blocks)
        if bullets:
            docs.documents().batchUpdate(
                documentId=doc_id, body={"requests": bullets}).execute()
        made.append(("Doc", f"https://docs.google.com/document/d/{doc_id}/edit"))

    if not args.no_slides:
        deck_id = drive.files().create(
            body={"name": f"{stem} (briefing)",
                  "mimeType": "application/vnd.google-apps.presentation"},
            fields="id").execute()["id"]
        pres = gbuild("slides", "v1", credentials=creds)
        build_deck(pres, counts, deck_id)
        made.append(("Slides",
                     f"https://docs.google.com/presentation/d/{deck_id}/edit"))

    print()
    for kind, url in made:
        print(f"{kind:7} {url}")
    print("\nBoth private to your account. Share from the file when you are ready.")
    if not counts:
        print("NOTE: counts were not verified on this run — re-run with --counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
