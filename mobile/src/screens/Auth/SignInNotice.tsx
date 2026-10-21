/**
 * The one notice the sign-in card shows (ADR-556 D5).
 *
 * Three things used to arrive three ways: a reset request's result in a heavy
 * green box that repeated its own title, a setup-closed refusal in a yellow
 * box, and a forced sign-out as a native Alert over the form. Now each is this:
 * an icon, a title that says what happened, and a body that says what to do.
 *
 * Meaning never rides on colour alone (WCAG 1.4.1): every tone has its own icon
 * and the title carries the message. Success and info announce politely; a
 * warning is an alert (WCAG 4.1.3 status messages).
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

export type NoticeTone = 'success' | 'warning' | 'info';

function toneColor(tone: NoticeTone, c: ThemeColors): string {
  return tone === 'success' ? c.success : tone === 'warning' ? c.warning : c.primary;
}

/** 16px stroke glyphs, drawn rather than pulled from an icon font. */
function Glyph({ tone, color }: { tone: NoticeTone; color: string }) {
  const stroke = { stroke: color, strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, fill: 'none' };
  return (
    <Svg width={16} height={16} viewBox="0 0 24 24">
      {tone === 'success' && <Path d="M5 12.5l4.5 4.5L19 7.5" {...stroke} />}
      {tone === 'warning' && (
        <>
          <Path d="M12 3.5L2.5 20h19L12 3.5z" {...stroke} />
          <Path d="M12 10v4.5M12 17.5v.01" {...stroke} />
        </>
      )}
      {tone === 'info' && (
        <>
          <Circle cx={12} cy={12} r={9} {...stroke} />
          <Path d="M12 11v5.5M12 7.5v.01" {...stroke} />
        </>
      )}
    </Svg>
  );
}

type Props = {
  tone: NoticeTone;
  title: string;
  children: React.ReactNode;
};

export default function SignInNotice({ tone, title, children }: Props) {
  const c = useColors();
  const s = styles(c);
  const color = toneColor(tone, c);
  return (
    <View
      accessibilityRole={tone === 'warning' ? 'alert' : 'summary'}
      accessibilityLiveRegion={tone === 'warning' ? 'assertive' : 'polite'}
      style={[s.box, { backgroundColor: color + '0F', borderColor: color + '2E' }]}
    >
      <View style={[s.disc, { backgroundColor: color + '1F' }]}>
        <Glyph tone={tone} color={color} />
      </View>
      <View style={s.text}>
        <Text style={s.title}>{title}</Text>
        {typeof children === 'string' ? <Text style={s.body}>{children}</Text> : children}
      </View>
    </View>
  );
}

/** Body text for callers that need more than one paragraph. */
export function NoticeText({ children, strong }: { children: React.ReactNode; strong?: string }) {
  const c = useColors();
  const s = styles(c);
  return (
    <Text style={s.body}>
      {strong ? <Text style={s.strong}>{strong} </Text> : null}
      {children}
    </Text>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  box:    { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm + 4,
            borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm + 4,
            paddingHorizontal: spacing.md, marginBottom: spacing.md },
  disc:   { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  text:   { flex: 1, gap: 2, paddingTop: 3 },
  title:  { fontSize: fontSize.sm + 1, fontWeight: fontWeight.semibold, color: c.foreground },
  body:   { fontSize: fontSize.sm, lineHeight: 20, color: c.mutedForeground },
  strong: { color: c.foreground, fontWeight: fontWeight.semibold },
});
