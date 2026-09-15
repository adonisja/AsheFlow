/** Pulls a TBA and a delivery address out of OCR'd label text.
 *
 *  A DIRECT PORT of `backend/app/services/label_ingestor.py::parse_label_lines`,
 *  rules and all, so the tracker and the production intake agree about what a
 *  label says. Ported rather than called because this page makes no API
 *  requests — that isolation is why it needs no login — and an OCR endpoint
 *  would undo it. The parse is pure regex over text lines, so there is nothing
 *  server-side about it; only the OCR engine differs (Tesseract in the browser
 *  here, Textract there).
 *
 *  WHAT ADR-404 DID AND DID NOT SETTLE. It established that neither the Code
 *  128 barcode nor the QR code encodes a destination — a scan identifies a
 *  package, it cannot place it. That is about the SYMBOLS. Reading the printed
 *  address off the label image is a different question, and the backend already
 *  answers it in the affirmative: `parse_label_lines` extracts an address line
 *  today. So OCR for addresses is not foreclosed; it is the established path.
 *
 *  Everything here is a SUGGESTION, never a write. A creased label in a dim van
 *  is exactly where a misread becomes a delivery to the wrong street, which is
 *  why the backend requires confirmation and why this returns candidates for a
 *  human to accept.
 */

/** Amazon tracking numbers: TBA + 12-15 digits. Bounded rather than \d+ so a
 *  barcode's digit run underneath the label cannot be swallowed as one long
 *  TBA — the same bound the backend regex uses. */
const TBA_RE = /\bTBA\d{12,15}\b/i;

/** The same, but tolerant of the character confusions OCR actually makes on the
 *  three-letter prefix.
 *
 *  Measured on a real Amazon label photographed in the field: Tesseract read
 *  `TBA326446450396` as `1BA3264464 50396`. Two separate problems — the space
 *  (already handled by stripping whitespace) and `T` -> `1`. The strict regex
 *  rejected it outright, so a TBA that was fully present and correct in the
 *  image came back "not found".
 *
 *  Substitutions are limited to the glyph pairs that genuinely collide in this
 *  font: T/1/7/I/L, B/8, A/4. The DIGITS are left strict — a wrong digit is a
 *  wrong package, and the barcode tier exists for when that matters. This only
 *  rescues the prefix, then normalises it back to a canonical TBA.
 *
 *  US/CA/MX also issue TBM and TBC; the UK issues GBA (ADR-399). */
const TBA_FUZZY_RE = /\b[T17IL][B8][A4](\d{12,15})\b/i;
const TBM_FUZZY_RE = /\b[T17IL][B8]([MC])(\d{12,15})\b/i;

/** Pulls a TBA out of a line, tolerating OCR prefix damage. Returns the
 *  canonical form, or null. */
function findTba(text: string): string | null {
  const flat = text.replace(/\s+/g, '');
  const strict = TBA_RE.exec(flat);
  if (strict) return strict[0].toUpperCase();
  const m = TBM_FUZZY_RE.exec(flat);
  if (m) return `TB${m[1].toUpperCase()}${m[2]}`;
  const f = TBA_FUZZY_RE.exec(flat);
  if (f) return `TBA${f[1]}`;
  return null;
}

/** A street line starts with a house number. Requiring one keeps city/state and
 *  the "SHIP TO:" chrome out — those lines have no leading digit. */
const STREET_RE = /^\d+[A-Za-z]?\s+[A-Za-z0-9].*/;

/** Label furniture that can otherwise look like an address line. */
const NOISE_RE = /^(ship\s*to|from|return\s*to|deliver\s*to|attn|c\/o|tracking|order)\b[:\s]*/i;

export interface LabelRead {
  tba: string | null;
  addressLine: string | null;
  /** 0–1, mean confidence of the lines the fields came from. Null when nothing
   *  was found. */
  confidence: number | null;
  /** Every line read, so the UI can offer "none of these — type it" without
   *  re-running OCR. */
  lines: string[];
  warnings: string[];
  /** More than one street-looking line — the UI should ask rather than assume. */
  addressCandidates: string[];
}

/** Strips label furniture AND leading OCR debris.
 *
 *  Measured on a real label: Tesseract returned "~a'] 104 W MEADOW WIND LN".
 *  The address was read perfectly; the street test rejected it only because of
 *  four junk characters in front, so a correct read was thrown away.
 *
 *  Only NON-alphanumeric leading characters are dropped, and only up to the
 *  first digit — enough to clear OCR speckle without eating a house number or
 *  swallowing a real word. */
const LEADING_JUNK = /^[^A-Za-z0-9]{0,6}(?=\d)/;

const clean = (line: string): string =>
  line
    .replace(NOISE_RE, '')
    .replace(/^[\s,.]+|[\s,.]+$/g, '')
    // Second pass: "~a'] 104 W ..." -> junk, one stray letter, then the number.
    .replace(/^[^A-Za-z0-9]*[A-Za-z]{0,2}[^A-Za-z0-9]*(?=\d)/, '')
    .replace(LEADING_JUNK, '')
    .trim();

/** `lines` is [text, confidence 0–100], the shape both Textract and Tesseract
 *  report. Pure, so the rules are testable without an engine or a fixture. */
export function parseLabelLines(lines: [string, number][]): LabelRead {
  const read: LabelRead = {
    tba: null, addressLine: null, confidence: null,
    lines: lines.map(([t]) => t), warnings: [], addressCandidates: [],
  };

  const fieldConfs: number[] = [];

  for (const [text, conf] of lines) {
    // Spaces stripped inside findTba: OCR routinely reads
    // "TBA 326446450396" with a gap the printed label does not have.
    const found = findTba(text);
    if (found) { read.tba = found; fieldConfs.push(conf); break; }
  }

  const candidates: [string, number][] = [];
  for (const [text, conf] of lines) {
    const c = clean(text);
    if (!c || findTba(c) !== null) continue;
    if (STREET_RE.test(c)) candidates.push([c, conf]);
  }

  if (candidates.length > 0) {
    // FIRST street-looking line, not the longest or highest-confidence one:
    // shipping labels put the delivery address above the return address, so
    // first-wins matches the physical layout.
    read.addressLine = candidates[0][0];
    fieldConfs.push(candidates[0][1]);
    read.addressCandidates = candidates.map(([t]) => t);
    if (candidates.length > 1) read.warnings.push('more_than_one_address_line');
  }

  if (read.tba === null) read.warnings.push('no_tba_found');
  if (read.addressLine === null) read.warnings.push('no_address_found');

  if (fieldConfs.length > 0) {
    read.confidence = Math.round(
      (fieldConfs.reduce((a, b) => a + b, 0) / fieldConfs.length / 100) * 1000,
    ) / 1000;
  }
  return read;
}

export const needsManualEntry = (r: LabelRead): boolean =>
  r.tba === null || r.addressLine === null;

/** How much to trust a read, 0-3.
 *
 *  Written to choose between auto-rotations; that sweep is gone (the crop
 *  dialog frames and orients the label instead), but this is kept as the single
 *  definition of "was this read any good", which the UI still needs.
 *
 *
 *  NOT Tesseract's own confidence, which is unreliable here: measured on a real
 *  label, the rotation that found BOTH fields scored 42% while a rotation that
 *  found neither scored 49%. Confidence measures glyph certainty, not whether
 *  the glyphs formed the thing you wanted.
 *
 *  An address must look like a real street line to count. Without this a
 *  rotation reading pure noise ("7 7 Sh WN TR HV Aled Ed 2") scored as a
 *  successful address and stopped the search on the WRONG orientation. */
export function readScore(r: LabelRead): number {
  let n = 0;
  if (r.tba) n += 2;                              // checksummable, hard to fake
  if (r.addressLine && looksLikeStreet(r.addressLine)) n += 1;
  return n;
}

/** Does this look like a real street line, as opposed to OCR noise?
 *
 *  A first attempt ("house number + one word of 3+ letters") was useless: it
 *  passed "7 7 Sh WN TR HV Aled Ed 2" and REJECTED "221 W 28TH ST", because
 *  noise is full of short capitalised fragments while a real address's words
 *  are often short too (W, ST, LN).
 *
 *  What actually separates them is the ratio of clean alphabetic content to
 *  junk. A real line is nearly all letters, digits and single spaces; noise
 *  carries stray punctuation, lone letters, and mixed case mid-word. */
export function looksLikeStreet(line: string): boolean {
  const t = line.trim();
  if (!/^\d{1,6}[A-Za-z]?\s/.test(t)) return false;   // must start with a house number
  if (t.length < 8 || t.length > 60) return false;

  const words = t.split(/\s+/).slice(1);
  if (words.length === 0 || words.length > 8) return false;

  // Noise signature: lone letters scattered through the line. A real address
  // has at most one ("104 W MEADOW WIND LN" has W).
  const singles = words.filter((w) => /^[A-Za-z]$/.test(w)).length;
  if (singles > 1) return false;

  // Every word should be a clean token — letters, or letters+digits like 28TH.
  const clean = words.filter((w) => /^[A-Za-z]+$/.test(w) || /^\d+[A-Za-z]{1,2}$/.test(w));
  if (clean.length !== words.length) return false;

  // And at least one substantial word: MEADOW, BROADWAY, 28TH.
  return words.some((w) => /^[A-Za-z]{3,}$/.test(w) || /^\d+[A-Za-z]{2}$/.test(w));
}
