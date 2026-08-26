/**
 * The walker's own route in workforce mode (ADR-297).
 *
 * Until this screen existed a walker in workforce mode saw NOTHING. Full mode's
 * MyRoute is served by the proprietary walker_routes router, registered under
 * `_full_mode`, so every one of its reads 404s here.
 *
 * THE TOTE IS THE UNIT OF WORK, NOT THE STOP.
 *
 * This is deliberately not full mode's screen with fields blanked out. Workforce
 * mode has no stop grain at all — `commit-sort` writes `stops=None` and
 * `normalised_addresses=[]` — so a stop list would be a shape whose every element
 * has no data behind it. The captain entered addresses per TOTE, the sort
 * consumed TOTES, and the thing the walker physically picks up is a TOTE.
 *
 * A LIST OF ADDRESSES WOULD BE A LIE. It would imply a delivery sequence we did
 * not compute and cannot honour. What the walker gets instead is: which totes are
 * theirs, what colour each one is, and which blocks those totes cover.
 *
 * The swatch follows ADR-296 exactly — the physical colour, theme-fixed, ringed —
 * because the walker is matching it against the same bag the captain was. A tote
 * that looks one way on the captain's screen and another here is two different
 * objects as far as the person holding it is concerned.
 *
 * NO PROGRESS BAR (ADR-297 D5c). A percentage needs a numerator, and nothing in
 * workforce mode counts a delivery as it happens. `flex_package_count` is shown
 * as a figure — the parcels the captain counted at scan — and an em-dash until
 * they record it. Never the bottom half of a fraction.
 *
 * VISUAL STRUCTURE BORROWED FROM FULL MODE'S MyRouteScreen.
 *
 * The DATA differs (totes, not stops) but the way a walker reads a route does
 * not, so the layout is deliberately the same shape:
 *
 *   HERO CARD      route identity + ONE phase-appropriate primary action. The
 *                  title changes with the lifecycle — "Ready to start" /
 *                  "Out on route" / "Back at the truck" — so the walker's next
 *                  move is the largest thing on screen.
 *   TERRITORY      collapsible block chips with a count, so the ground is
 *                  glanceable before departure and referenceable en route.
 *   WORK LIST      the unit of work, expanded.
 *
 * What is NOT borrowed, and why:
 *   - per-stop actions (complete / RTS / missing): no stop grain exists, and
 *     returns are recorded by the captain at the truck (ADR-292/300 D4).
 *   - "N stops remaining": there is no completion event to count down from.
 *   - effort_class chip: the workforce sort does not compute one.
 *
 * The lifecycle ACTIONS are captain-driven here (ADR-300 D1) — the captain
 * marks departure and closes the route at the truck — so the hero reports state
 * rather than offering a button. A walker tapping "Start Route" on a screen
 * whose endpoint is captain-gated would be a dead control, which is the exact
 * failure this rebuild replaced: full mode's screen was reachable in workforce
 * mode with every action 404ing behind it.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge, Card } from '@components/ui/primitives';
import { errorText } from '@api/errorText';
import { localYMD } from '@hooks/localDate';
import { formatBlockKey } from '@components/route/RouteStopsList';

// ── Types (mirror GET /workforce/my-route/{entry_date}) ───────────────────────

type RouteTote = {
  bag_id: string;
  /** Resolved hex from the sheet's colour word; null renders a neutral pill. */
  bag_color: string | null;
  /** The colour WORD, for the accessibility label. */
  bag_color_name: string | null;
  block_keys: string[];
  /** Human sentences where the address still parses, raw keys where ADR-219 has
   *  nulled it. Same length and order as block_keys. */
  block_descriptions: string[];
};

type MyRoute = {
  no_route_assigned: boolean;
  route_id: string | null;
  route_number: number | null;
  status: string | null;
  truck_name: string | null;
  totes: RouteTote[];
  block_keys: string[];
  /** The real parcel count (ADR-291 D11). NULL until the captain records it at
   *  scan time — an em-dash, never 0, which would mean "carried nothing". */
  flex_package_count: number | null;
  departed_at: string | null;
  returned_at: string | null;
};

type Props = {
  /** ISO date. Defaults to the device's today; the server is authoritative. */
  entryDate?: string;
};

// ── Screen ────────────────────────────────────────────────────────────────────

export default function MyWorkforceRouteScreen({ entryDate }: Props) {
  const c = useColors();
  const s = styles(c);

  // Local, not UTC. toISOString() rolls over at 8 PM Eastern and would ask the
  // API for tomorrow — see hooks/localDate.ts.
  const day = entryDate ?? localYMD();

  const [data, setData] = useState<MyRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const res = await apiClient.get<MyRoute>(`/workforce/my-route/${day}`);
      setData(res.data);
      setError(null);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not load your route.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [day]);

  useEffect(() => { load(); }, [load]);

  // ADR-300's lifecycle, read back. departed set + returned null IS "out".
  const phase = !data || data.no_route_assigned ? null
    : data.returned_at ? 'done'
    : data.departed_at ? 'out'
    : 'ready';

  return (
    <ScreenShell
      title="My Route"
      subtitle={data?.truck_name ?? undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load(true)}
    >
      {error ? <Text style={s.error}>{error}</Text> : null}

      {/* Not an error state. A walker with no route yet is a normal part of a
          normal morning — they are on a truck, waiting to be assigned — which
          is why the API returns a flag rather than a 404 (ADR-297 D6). */}
      {data?.no_route_assigned ? (
        <Card style={s.empty}>
          <Text style={s.emptyTitle}>No route yet</Text>
          <Text style={s.emptyBody}>
            Your captain assigns routes once the truck is sorted. Pull down to
            refresh.
          </Text>
        </Card>
      ) : null}

      {data && !data.no_route_assigned ? (
        <>
          <Card style={s.header}>
            {/* HERO — identity, then the lifecycle state as the largest line on
                screen. Full mode puts a primary ACTION here; in workforce mode
                the captain drives the lifecycle (ADR-300 D1), so this reports
                rather than acts. A button the walker cannot press is worse than
                no button. */}
            <View style={s.headerRow}>
              <View style={s.headerLeft}>
                <Text style={s.heroLabel}>ROUTE {data.route_number}</Text>
                <Text style={s.heroTitle}>
                  {phase === 'ready' ? 'Ready to start'
                    : phase === 'out' ? 'Out on route'
                    : 'Back at the truck'}
                </Text>
                <Text style={s.heroSub}>
                  {phase === 'ready'
                    ? 'Your captain records the departure when you leave.'
                    : phase === 'out'
                    ? 'Your captain closes the route when you return.'
                    : 'Returns are recorded with your captain.'}
                </Text>
              </View>
              {phase === 'out' ? <Badge tone="primary">Out</Badge> : null}
              {phase === 'done' ? <Badge tone="success">Done</Badge> : null}
              {phase === 'ready' ? <Badge tone="muted">Ready</Badge> : null}
            </View>

            <View style={s.figures}>
              <Figure
                label="Totes"
                value={String(data.totes.length)}
                styles={s}
              />
              <Figure
                label="Packages"
                // Em-dash, never 0 — the captain has not counted yet, which is
                // a different fact from "this route carried nothing".
                value={data.flex_package_count === null
                  ? '—'
                  : String(data.flex_package_count)}
                hint={data.flex_package_count === null ? 'Not counted yet' : undefined}
                styles={s}
              />
              <Figure
                label="Blocks"
                // Derived from the SAME grouping the body renders, not from
                // Route.block_keys. Those two disagreed: the sort's stored keys
                // said 1 while the totes' addresses covered 2, so the hero
                // contradicted the sections directly beneath it. One source.
                value={String(groupByBlock(data.totes).length)}
                styles={s}
              />
            </View>
          </Card>

          {/* The TERRITORY chip row that used to sit here is gone. It listed the
              same blocks as the section headings six pixels below it — pure
              repetition — and it read `Route.block_keys` (the sort's stored
              output) while the sections derive from the totes' actual
              addresses, so the two could DISAGREE. They did: the header said
              one block while the body showed two. One source, stated once. */}
          {/* GROUPED BY BLOCK, not a flat tote list.
              The block is the WALKABLE unit — a walker works one block, then
              moves to the next — so the block is the heading and the totes are
              what they carry for it. A flat list makes them re-derive that
              grouping in their head every time.

              A tote spanning two blocks appears under BOTH (ADR-291 D4: the
              captain entered addresses that disagreed). That repetition is
              honest — the bag really is needed in both places — and the flat
              list hid it. */}
          {groupByBlock(data.totes).map(g => (
            <Card key={g.blockKey} style={s.blockCard}>
              {/* Same treatment as full mode's RouteStopsList: a small tinted
                  pill carrying the HUMAN label. `W_36_St_400` is a machine key
                  — formatBlockKey turns it into "WEST 36 ST · 400 BLOCK", which
                  is what a walker would say out loud. */}
              <View style={s.blockPill}>
                <Text style={s.blockPillText}>{formatBlockKey(g.blockKey)}</Text>
              </View>
              <Text style={s.blockDesc}>{g.description}</Text>

              <View style={s.bagRow}>
                {g.totes.map(t => (
                  <BagChip
                    key={`${g.blockKey}-${t.bag_id}`}
                    tote={t}
                    styles={s}
                    c={c}
                  />
                ))}
              </View>
            </Card>
          ))}

          {/* A tote whose address never parsed has no block to sit under, so it
              would silently vanish from the grouping above. ADR-291 D5's
              no-silent-drops rule applies to rendering too. */}
          {data.totes.filter(t => t.block_keys.length === 0).length > 0 ? (
            <Card style={s.blockCard}>
              <View style={[s.blockPill, s.blockPillWarn]}>
                <Text style={[s.blockPillText, s.blockPillWarnText]}>NO BLOCK</Text>
              </View>
              <Text style={s.blockDesc}>
                No address recorded — check with your captain.
              </Text>
              <View style={s.bagRow}>
                {data.totes.filter(t => t.block_keys.length === 0).map(t => (
                  <BagChip key={`nb-${t.bag_id}`} tote={t} styles={s} c={c} />
                ))}
              </View>
            </Card>
          ) : null}

          {data.totes.length === 0 ? (
            <Card style={s.empty}>
              <Text style={s.emptyBody}>
                This route has no totes listed. Check with your captain.
              </Text>
            </Card>
          ) : null}
        </>
      ) : null}
    </ScreenShell>
  );
}

// ── pieces ────────────────────────────────────────────────────────────────────

/** One figure. Deliberately a FIGURE and never a fraction: workforce mode has no
 *  delivery events, so there is no numerator to put over anything (D5c). */
function Figure({
  label, value, hint, styles: s,
}: {
  label: string;
  value: string;
  hint?: string;
  styles: ReturnType<typeof styles>;
}) {
  return (
    <View style={s.figure}>
      <Text style={s.figureValue}>{value}</Text>
      <Text style={s.figureLabel}>{label}</Text>
      {hint ? <Text style={s.figureHint}>{hint}</Text> : null}
    </View>
  );
}

/** A tote as a colour-tinted chip, matching full mode's BagPill.
 *
 * The whole pill wears the bag's colour — `tint + '22'` fill, `tint + '66'`
 * border, coloured text — rather than a grey pill with a separate dot. A walker
 * scanning a truck sees COLOUR first and the number second, so the colour
 * should be the pill, not an ornament on it.
 *
 * Falls back to a neutral tint when the sheet carried no colour word, which is
 * what full mode does and what ADR-296 requires (never invent a colour).
 */
function BagChip({
  tote, styles: s, c,
}: {
  tote: RouteTote;
  styles: ReturnType<typeof styles>;
  c: ThemeColors;
}) {
  const tint = tote.bag_color || c.mutedForeground;
  return (
    <View
      style={[
        s.bagChip,
        { backgroundColor: tint + '22', borderColor: tint + '66' },
      ]}
    >
      <Text
        style={[s.bagChipText, { color: tint }]}
        accessibilityLabel={
          tote.bag_color_name
            ? `${titleCase(tote.bag_color_name)} bag ${tote.bag_id}`
            : `Bag ${tote.bag_id}`
        }
      >
        {tote.bag_id}
      </Text>
    </View>
  );
}

type BlockGroup = { blockKey: string; description: string; totes: RouteTote[] };

/** Totes regrouped under the block they serve.
 *
 * The API returns tote -> blocks; the walker works block -> totes. This inverts
 * it, which is a many-to-many flip rather than a partition: a tote whose
 * addresses disagreed (ADR-291 D4) serves more than one block and appears under
 * each. That duplication is the truth — the bag is genuinely needed in both
 * places — and a partition would have to silently pick one.
 *
 * `block_keys` and `block_descriptions` are parallel arrays built together by
 * the endpoint, so zipping them is safe; the description falls back to the raw
 * key server-side when ADR-219 has nulled the address.
 */
function groupByBlock(totes: RouteTote[]): BlockGroup[] {
  const out = new Map<string, BlockGroup>();
  for (const t of totes) {
    t.block_keys.forEach((key, i) => {
      const g = out.get(key)
        ?? { blockKey: key, description: t.block_descriptions[i] ?? key, totes: [] };
      g.totes.push(t);
      out.set(key, g);
    });
  }
  // Stable order: the same route reads the same way on every refresh.
  for (const g of out.values()) g.totes.sort((a, b) => a.bag_id.localeCompare(b.bag_id));
  return [...out.values()].sort((a, b) => a.blockKey.localeCompare(b.blockKey));
}

/** "orange" -> "Orange". The API returns lowercase colour words. */
function titleCase(v: string): string {
  return v.charAt(0).toUpperCase() + v.slice(1);
}

// ── styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  // Matches the errorBox pattern used elsewhere in the app — dangerLight fill,
  // danger border, foreground text. There is no `dangerForeground` token.
  error: {
    color: c.foreground,
    backgroundColor: c.dangerLight,
    borderWidth: 1,
    borderColor: c.danger,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },

  header: { gap: spacing.md },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  headerLeft: { flex: 1, gap: 2 },
  // Full mode's hero hierarchy: a small eyebrow, then the state as the biggest
  // thing on screen, then one line of context.
  // Centred: the hero is the walker's own status, and centring reads as being
  // ABOUT them rather than as a row in a report.
  heroLabel: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    color: c.mutedForeground,
    letterSpacing: 0.5,
    textAlign: 'center',
  },
  heroTitle: {
    fontSize: fontSize.xl,
    fontWeight: fontWeight.bold,
    color: c.foreground,
    textAlign: 'center',
  },
  heroSub: {
    fontSize: fontSize.sm,
    color: c.mutedForeground,
    fontStyle: 'italic',
    textAlign: 'center',
  },

  territory: {
    marginTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: c.border,
    paddingTop: spacing.sm,
  },
  territoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  territoryLabel: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    color: c.mutedForeground,
    marginRight: 4,
  },
  chip: {
    backgroundColor: c.primaryLight,
    borderRadius: radius.xs,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  chipText: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.bold,
    color: c.primary,
  },
  chipMore: { fontSize: fontSize.xs, color: c.mutedForeground },

  figures: { flexDirection: 'row', gap: spacing.lg },
  figure: { flex: 1 },
  figureValue: {
    fontSize: fontSize.xl,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  figureLabel: { fontSize: fontSize.sm, color: c.mutedForeground },
  figureHint: { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },

  sectionTitle: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
    marginTop: spacing.lg,
  },
  sectionHint: {
    fontSize: fontSize.sm,
    color: c.mutedForeground,
    marginBottom: spacing.sm,
  },

  // Each block is its OWN CARD. Research on content-rich grouped lists is
  // consistent: subtle headers stop working once sections carry real content,
  // and a solid container is what makes "this block and these bags are one
  // thing" readable without the eye inferring it from whitespace.
  blockCard: { marginTop: spacing.sm, gap: 2 },
  blockPill: {
    backgroundColor: c.primaryLight,
    borderRadius: radius.xs,
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.xs + 2,
    paddingVertical: 2,
    marginBottom: 2,
  },
  blockPillText: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.bold,
    color: c.primary,
    letterSpacing: 0.4,
  },
  // An unaddressed tote is a problem to raise, not a place to walk — warning
  // tint so it does not read as just another block.
  blockPillWarn: { backgroundColor: c.warningLight },
  blockPillWarnText: { color: c.warning },
  blockDesc: {
    fontSize: fontSize.sm,
    color: c.mutedForeground,
    fontStyle: 'italic',
  },
  bagRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  // Full mode's BagPill tinting, but a true pill rather than a rounded box: a
  // tote number is a label on a physical bag, and the fully-rounded shape reads
  // as one. Extra horizontal padding keeps the capsule from pinching the digits.
  bagChip: {
    borderRadius: radius.full,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  bagChipText: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    fontVariant: ['tabular-nums'],
    letterSpacing: 0.3,
  },

  tote: { gap: spacing.xs, marginBottom: spacing.sm },
  toteHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  // ADR-296 D1: fixed across themes — the bag does not change colour when the
  // phone does. The ring is what keeps #000000 visible on a dark surface.
  swatch: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: c.swatchRing,
  },
  swatchEmpty: { borderStyle: 'dashed' },
  bagId: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  blockLine: { fontSize: fontSize.sm, color: c.foreground, marginLeft: spacing.lg },
  blockEmpty: {
    fontSize: fontSize.sm,
    color: c.mutedForeground,
    marginLeft: spacing.lg,
    fontStyle: 'italic',
  },

  empty: { gap: spacing.xs },
  emptyTitle: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
  },
  emptyBody: { fontSize: fontSize.sm, color: c.mutedForeground },
});
