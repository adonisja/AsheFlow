"""Read a TBA and an address off a package label (ADR-246).

A walker photographs the label instead of typing it. Textract returns the words
on it; this pulls out the two fields intake needs and hands them back for the
walker to CONFIRM.

Confirmation is not optional. OCR on a creased label in a dim van is exactly
where a misread becomes a phantom package or a delivery to the wrong street,
and both are worse than the walker retyping ten characters. Nothing here
writes, and `confidence` exists so the UI can flag a shaky read rather than
present it as fact.

### Third instance of an established pattern

`ImageManifestIngestor` and `ScorecardIngestor` already do injectable-client
Textract work. This follows their shape deliberately: a real client resolved
lazily, a stub injected in tests, and a pure static parser so the extraction
logic is testable without AWS.

It uses **DetectDocumentText**, not AnalyzeDocument(TABLES): a shipping label is
free-form text, not a grid. That is also the cheaper call (~$0.0015/page vs
~$0.015), which matters when it fires once per found package rather than once
per manifest.

### Why normalisation is not done here

The address normaliser lives in the sort pipeline, which is proprietary and
would pull the whole module in — the same reason `load_company_boundary` was
duplicated rather than imported. This returns the raw line; the intake endpoint
normalises and geocodes it, and a geocode failure already has a defined path
(escalate to dispatch, ADR-246).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Amazon tracking numbers: TBA + 12-15 digits. Bounded rather than \d+ so a
# barcode's digit run underneath the label cannot be swallowed as one long TBA.
_TBA_RE = re.compile(r"\bTBA\d{12,15}\b", re.IGNORECASE)

# A street line starts with a house number. Requiring one keeps city/state and
# the "SHIP TO:" chrome out — those lines have no leading digit.
_STREET_RE = re.compile(r"^\d+[A-Za-z]?\s+[A-Za-z0-9].*")

# Label furniture that can otherwise look like an address line.
_NOISE = re.compile(
    r"^(ship\s*to|from|return\s*to|deliver\s*to|attn|c/o|tracking|order)\b[:\s]*",
    re.IGNORECASE,
)


@dataclass
class LabelRead:
    """What we think is on the label. Always confirmed by a human before use."""
    tba: Optional[str] = None
    address_line: Optional[str] = None
    # 0.0–1.0, the mean Textract confidence of the lines the fields came from.
    # None when nothing was found.
    confidence: Optional[float] = None
    # Every line read, so the UI can offer "none of these — type it" without a
    # second Textract call.
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_manual_entry(self) -> bool:
        """True when the read is too incomplete to present as a suggestion."""
        return self.tba is None or self.address_line is None


def _clean(line: str) -> str:
    return _NOISE.sub("", line).strip(" ,.")


def parse_label_lines(lines: list[tuple[str, float]]) -> LabelRead:
    """Pull the TBA and street line out of OCR'd text lines.

    `lines` is (text, confidence) as Textract returns it. Pure and static so
    the extraction rules are testable without AWS or a fixture image.

    Picks the FIRST street-looking line rather than the longest or the
    highest-confidence one: shipping labels put the delivery address above the
    return address, so first-wins matches the physical layout. A label with two
    candidates records a warning so the UI can ask rather than silently choose.
    """
    read = LabelRead(lines=[t for t, _ in lines])

    # Confidence of every line a returned field came from — the mean is what
    # the UI thresholds on, so a shaky address must drag the score down even
    # when the TBA read cleanly.
    field_confs: list[float] = []
    for text, conf in lines:
        m = _TBA_RE.search(text.replace(" ", ""))
        if m and read.tba is None:
            read.tba = m.group(0).upper()
            field_confs.append(conf)
            break

    street_candidates: list[tuple[str, float]] = []
    for text, conf in lines:
        cleaned = _clean(text)
        if not cleaned or _TBA_RE.search(cleaned.replace(" ", "")):
            continue
        if _STREET_RE.match(cleaned):
            street_candidates.append((cleaned, conf))

    if street_candidates:
        read.address_line, addr_conf = street_candidates[0]
        field_confs.append(addr_conf)
        if len(street_candidates) > 1:
            read.warnings.append(
                "more_than_one_address_line"  # UI should ask which
            )

    if read.tba is None:
        read.warnings.append("no_tba_found")
    if read.address_line is None:
        read.warnings.append("no_address_found")

    if field_confs:
        read.confidence = round(sum(field_confs) / len(field_confs) / 100.0, 3)

    return read


class LabelIngestor:
    """Textract-backed label reader.

    Production: a lazily-resolved boto3 client. Tests: inject `_textract_client`
    and the AWS call is never made — the same contract ImageManifestIngestor
    uses, so the stub shape is already familiar.
    """

    def __init__(self, image_bytes: bytes, _textract_client=None):
        self.image_bytes = image_bytes
        self._client = _textract_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            from app.core.config import settings

            # `region_name` is REQUIRED. The container sets AWS_REGION, but boto3 only
            # reads AWS_DEFAULT_REGION from the environment — so a bare
            # boto3.client("textract") raises NoRegionError, which the caller's
            # broad `except` then reports as "could not read the label".
            # Every other AWS client in the app already passes it (adp.py, email.py).
            return boto3.client("textract", region_name=settings.aws_region)
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for LabelIngestor in production. "
                "Install it with: pip install boto3"
            ) from exc

    @staticmethod
    def extract_lines(response: dict) -> list[tuple[str, float]]:
        """LINE blocks from a DetectDocumentText response, in reading order."""
        return [
            (b.get("Text", ""), float(b.get("Confidence", 0.0)))
            for b in response.get("Blocks", [])
            if b.get("BlockType") == "LINE" and b.get("Text")
        ]

    def read(self) -> LabelRead:
        client = self._get_client()
        response = client.detect_document_text(
            Document={"Bytes": self.image_bytes}
        )
        return parse_label_lines(self.extract_lines(response))
