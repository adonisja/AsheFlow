/** Pulls walker names off a screenshot of a dispatch assignment card.
 *
 *  The card is a vertical list of `Role — Name` rows, e.g.
 *
 *      Driver — Alex Driver
 *      Walker — Sam Walker
 *      Walker — Jordan Walker Jr
 *      9 assigned · DispatchOS · Today at 7:51AM
 *
 *  (Placeholder names. The original example used a real crew, which is not
 *  ours to publish — the parser does not care, and a reader learns the shape
 *  just as well from invented ones.)
 *
 *  WHY PARSE THE ROLE, NOT JUST THE NAME. A driver is assigned to the truck,
 *  not to a walking route, so they would only ever be an empty row in this log.
 *  The role is right there in the text — reading it means the driver arrives
 *  pre-unticked instead of being something the user has to notice and remove.
 *
 *  Everything here is a SUGGESTION. OCR on a phone screenshot will mangle a
 *  surname eventually, and a mangled name silently creates a second person in
 *  the crew list. So the caller confirms every row before anything is saved.
 */

export interface CrewCandidate {
  /** The name as read, editable before it is accepted. */
  name: string;
  /** 'walker' | 'driver' | '' when the row carried no recognisable role. */
  role: string;
  /** Pre-ticked in the review list. Drivers are not. */
  include: boolean;
  /** The raw OCR line, so a user can see what it came from. */
  source: string;
}

/** Roles the card actually prints. Anything else is treated as unknown rather
 *  than guessed at. */
const ROLE_RE = /^\s*(walker|driver|trainer|trainee|dispatch|captain)\s*[—–\-:|]+\s*(.+)$/i;

/** Card chrome that is not a person: the footer, timestamps, headings. */
const CHROME_RE = new RegExp(
  [
    '^\\d+\\s*assigned',
    'dispatchos',
    '^today\\b',
    '^\\d{1,2}:\\d{2}\\s*(am|pm)',
    '^first\\s+anchor',
    'assignments?\\s*[—–-]',
    '^\\s*$',
  ].join('|'),
  'i',
);

/** OCR debris: a "name" that is mostly punctuation, or a single character. */
function plausibleName(n: string): boolean {
  const t = n.trim();
  if (t.length < 3 || t.length > 48) return false;
  const words = t.split(/\s+/);
  if (words.length < 2 || words.length > 5) return false;   // first + last, at least
  // Each word should be alphabetic — allowing an apostrophe, hyphen, or a
  // trailing "Jr"/"II" style suffix.
  return words.every((w) => /^[A-Za-z][A-Za-z'’\-.]*$/.test(w));
}

/** Title-cases a name OCR shouted or lower-cased, without touching a name that
 *  already looks deliberate (McDonald, DeLuca). */
function tidy(n: string): string {
  const t = n.replace(/\s+/g, ' ').trim().replace(/[.,;:]+$/, '');
  if (t === t.toUpperCase() || t === t.toLowerCase()) {
    return t.split(' ').map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
  }
  return t;
}

export function parseCrewLines(lines: string[]): CrewCandidate[] {
  const out: CrewCandidate[] = [];
  const seen = new Set<string>();

  for (const raw of lines) {
    const line = raw.trim();
    if (!line || CHROME_RE.test(line)) continue;

    const m = ROLE_RE.exec(line);
    // A row without a recognisable role is only taken if it reads as a name on
    // its own — the card is a list of people, so a bare "Sam Walker" is
    // probably a row whose role OCR dropped.
    const role = m ? m[1].toLowerCase() : '';
    const candidate = tidy(m ? m[2] : line);

    if (!plausibleName(candidate)) continue;

    const key = candidate.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    out.push({
      name: candidate,
      role,
      // A driver walks no routes, so it starts unticked. An unknown role is
      // ticked — the card is a crew list, and the cost of an extra name the
      // user unticks is far lower than a missing walker they must retype.
      include: role !== 'driver',
      source: line,
    });
  }
  return out;
}
