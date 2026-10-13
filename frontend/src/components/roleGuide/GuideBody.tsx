import React from 'react';

/** Renders a role guide body as React elements — never as HTML.
 *
 *  ## Why this exists instead of react-markdown
 *
 *  The body is TENANT-AUTHORED: an admin PATCHes it through
 *  `/api/v1/my-role/{role}`. That makes it collected text, and CLAUDE.md's
 *  Dimension 10 is explicit that collected text never reaches
 *  `dangerouslySetInnerHTML`. A markdown library that emits HTML would put the
 *  decision about which tags are safe inside a dependency, where our audit
 *  cannot see it, for a body that only ever needs three constructs.
 *
 *  So this parses the three it needs and renders elements. React escapes every
 *  text node it places, so a body containing `<script>` or `<img onerror=...>`
 *  renders as those characters — visible, inert, and obviously a mistake by
 *  whoever typed it.
 *
 *  ## What it supports, and what it deliberately drops
 *
 *    `**bold**`      -> <strong>      (used for the section headings)
 *    `- item`        -> <li>          (used for the "what you do" lists)
 *    blank line      -> paragraph break
 *
 *  Anything else — links, images, headings, code — renders as literal text.
 *  That is the intended behaviour, not a gap to fill later: a link in a role
 *  guide is a place an admin could send their whole crew, and that is a
 *  different feature with a different review.
 */

/** Splits on `**...**` and emits <strong> for the odd segments.
 *
 *  Index parity does the work: splitting "a **b** c" on the delimiter yields
 *  ["a ", "b", " c"], so every odd index was inside the markers. An unclosed
 *  `**` leaves an even number of segments and the trailing text stays plain,
 *  which is the right failure — a half-typed marker should not bold the rest
 *  of the page.
 */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  return text.split('**').map((segment, i) =>
    i % 2 === 1
      ? <strong key={`${keyPrefix}-b${i}`} className="font-semibold text-foreground">{segment}</strong>
      : <React.Fragment key={`${keyPrefix}-t${i}`}>{segment}</React.Fragment>,
  );
}

export default function GuideBody({ body }: { body: string }) {
  const lines = body.split('\n');
  const blocks: React.ReactNode[] = [];

  // Consecutive `- ` lines accumulate here so they become ONE <ul>. Rendering
  // each as its own list would give every bullet its own list semantics, which
  // a screen reader announces as "list, 1 item" five times over.
  let bullets: string[] = [];
  let paragraph: string[] = [];

  const flushBullets = () => {
    if (bullets.length === 0) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-3 space-y-2 pl-1">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2.5 text-foreground">
            <span aria-hidden="true" className="mt-[0.45rem] h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground" />
            <span>{renderInline(item, `li${i}`)}</span>
          </li>
        ))}
      </ul>,
    );
  };

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(' ');
    paragraph = [];
    blocks.push(
      <p key={`p-${blocks.length}`} className="my-3 leading-relaxed text-foreground">
        {renderInline(text, `p${blocks.length}`)}
      </p>,
    );
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('- ')) {
      // A list interrupts a paragraph, so the paragraph closes first —
      // otherwise the bullets render above the prose that introduced them.
      flushParagraph();
      bullets.push(trimmed.slice(2));
      continue;
    }

    if (trimmed === '') {
      flushParagraph();
      flushBullets();
      continue;
    }

    flushBullets();
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushBullets();

  return <div className="text-[0.9375rem]">{blocks}</div>;
}
