import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/**
 * Renders a role guide body as React Native elements (ADR-494 D4).
 *
 * The web twin is `frontend/src/components/roleGuide/GuideBody.tsx` and the
 * parsing rules are deliberately identical, because the content is one row in
 * one table — an admin edits it once and both surfaces must show the same
 * thing. Two renderers that disagree about `**bold**` would make the PATCH
 * preview on web a lie about what a walker sees.
 *
 * ## Why no markdown library
 *
 * On web the reason is injection: the body is tenant-authored through
 * `PATCH /my-role/{role}`, so it is collected text and must never reach
 * `dangerouslySetInnerHTML`. React Native has no innerHTML at all, so that
 * specific risk is absent here — but the agreement requirement is not, and a
 * second library with its own dialect is how the two surfaces drift. Three
 * constructs, parsed the same way, in both places.
 *
 * Supported, matching the web twin exactly:
 *   `**bold**`   -> bold Text span
 *   `- item`     -> bullet row
 *   blank line   -> paragraph break
 *
 * Everything else renders as literal text. A link in a role guide is a place an
 * admin could send a whole crew, and that is a different feature with a
 * different review.
 */

/** Splits on `**...**`, bolding the odd segments.
 *
 *  Index parity does the work: "a **b** c" splits to ["a ", "b", " c"], so
 *  every odd index was inside the markers. An unclosed `**` leaves an even
 *  count and the trailing text stays plain — the right failure, since a
 *  half-typed marker should not bold the rest of the page.
 */
function Inline({ text, c }: { text: string; c: ThemeColors }) {
  const s = styles(c);
  return (
    <>
      {text.split('**').map((seg, i) =>
        i % 2 === 1
          ? <Text key={i} style={s.bold}>{seg}</Text>
          : <Text key={i}>{seg}</Text>,
      )}
    </>
  );
}

export default function GuideBody({ body }: { body: string }) {
  const c = useColors();
  const s = styles(c);

  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  let para: string[] = [];

  const flushBullets = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <View key={`ul-${blocks.length}`} style={s.list}>
        {items.map((item, i) => (
          <View key={i} style={s.listRow}>
            <View style={s.dot} />
            <Text style={s.body}><Inline text={item} c={c} /></Text>
          </View>
        ))}
      </View>,
    );
  };

  const flushPara = () => {
    if (!para.length) return;
    const text = para.join(' ');
    para = [];
    blocks.push(
      <Text key={`p-${blocks.length}`} style={[s.body, s.para]}>
        <Inline text={text} c={c} />
      </Text>,
    );
  };

  for (const line of body.split('\n')) {
    const t = line.trim();
    if (t.startsWith('- ')) {
      // A list interrupts a paragraph, so the paragraph closes first —
      // otherwise the bullets render above the prose introducing them.
      flushPara();
      bullets.push(t.slice(2));
    } else if (t === '') {
      flushPara();
      flushBullets();
    } else {
      flushBullets();
      para.push(t);
    }
  }
  flushPara();
  flushBullets();

  return <View>{blocks}</View>;
}

const styles = (c: ThemeColors) => StyleSheet.create({
  body: {
    fontSize: fontSize.base,
    lineHeight: fontSize.base * 1.55,
    color: c.foreground,
  },
  para: { marginVertical: spacing.sm },
  bold: { fontWeight: fontWeight.semibold, color: c.foreground },
  list: { marginVertical: spacing.sm, gap: spacing.sm },
  listRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  dot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: c.mutedForeground,
    // Aligns the dot with the first line's optical centre rather than its top.
    marginTop: fontSize.base * 0.6,
  },
});
