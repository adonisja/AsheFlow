/**
 * Recent days — the per-day half of My Stats (ADR-268).
 *
 * Rendered INSIDE MyPerformanceCard, not as its own screen. MyAccountScreen
 * states the placement rule this follows: the tabs split by WHO SAYS IT — you
 * (Settings), us (My Stats), Amazon (Scorecard) — and surfaces reading from one
 * source do not get split apart. This reads the same DeliveryStop/RTS data the
 * tiles above already summarise.
 *
 * What it adds that the aggregates cannot:
 *   - which truck, and who was on it
 *   - the route's effort_class
 *   - therefore a DIFFICULTY-NORMALISED rate
 *
 * That last one is the point. Raw RTS rate is confounded — 2.10% on easy routes
 * vs 10.81% on heavy, measured — so lifetime totals silently penalise whoever
 * drew the hard work. Per day, with effort_class in hand, it can be corrected.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

const LOOKBACK_DAYS = 30;

type CrewMember = { name: string; role: string };
type RTSDetail = {
  tba_number: string;
  rts_type: string;
  rts_explanation: string;
  is_reattemptable: boolean;
  normalised_address: string | null;
};
type AssignmentDay = {
  route_date: string;
  truck_name: string | null;
  slot_role: string;
  crew: CrewMember[];
  route_numbers: number[];
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  effort_class: string | null;
  rts_rate: number | null;
  /** rts_rate / the company rate for the SAME effort_class. 1.0 = typical.
   *  Always prefer this over rts_rate when judging a day. */
  rts_rate_vs_class: number | null;
  rts_details: RTSDetail[];
  address_detail: 'street' | 'block';
  /** 'truck' = driver/captain (whole load); 'own' = walker/trainer/trainee
   *  (only their stops). Must be labelled — a walker's 142 and a driver's
   *  2,865 are different measurements. */
  counts_scope: 'truck' | 'own';
  /** Trainees the caller was PAIRED with that day (ADR-269). Empty for every
   *  role but a trainer who was actually paired — the pairing is the
   *  authorisation, so this is never a filtered view of a longer list. */
  supervised: SupervisedDay[];
};

/** A paired trainee's day, as their trainer sees it (ADR-269).
 *  Same shape the trainee sees for themselves: during training the trainer
 *  answers for items on this record, so it carries full RTS detail. */
type SupervisedDay = {
  employee_id: string;
  name: string;
  stops_total: number;
  packages_total: number;
  packages_delivered: number;
  rts_count: number;
  missing_count: number;
  rts_rate: number | null;
  rts_rate_vs_class: number | null;
  rts_details: RTSDetail[];
};

const RTS_LABEL: Record<string, string> = {
  no_access: 'No access',
  business_closed: 'Business closed',
  package_damaged: 'Damaged',
  inclement_weather: 'Weather',
  customer_requested_future_delivery: 'Customer rescheduled',
  customer_cancelled_order: 'Customer cancelled',
};

function ymd(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() - offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function prettyDate(iso: string): string {
  // Rebuilt as LOCAL: new Date('2026-08-07') is midnight UTC and renders as the
  // 6th in any timezone behind it.
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
  });
}

function DayRow({ day }: { day: AssignmentDay }) {
  const c = useColors();
  const s = styles(c);
  const [open, setOpen] = useState(false);
  const vs = day.rts_rate_vs_class;
  const hasWork = day.packages_total > 0;

  const vsColor = vs === null ? c.mutedForeground
    : vs < 0.95 ? c.success
    : vs > 1.15 ? c.gold
    : c.mutedForeground;

  return (
    <View style={[s.row, { borderColor: c.border, backgroundColor: c.background }]}>
      <View style={s.rowTop}>
        <View style={s.rowLeft}>
          <View style={s.titleLine}>
            <Text style={[s.date, { color: c.foreground }]}>{prettyDate(day.route_date)}</Text>
            {!!day.truck_name && (
              <Text style={[s.meta, { color: c.mutedForeground }]}>· {day.truck_name}</Text>
            )}
            {!!day.effort_class && day.effort_class !== 'standard' && (
              /* Only exceptions get a chip — 'standard' on every row is noise
                 that hides the heavy days. */
              <Text style={[s.chip, {
                color: day.effort_class === 'heavy' ? c.gold : c.info,
                backgroundColor: (day.effort_class === 'heavy' ? c.gold : c.info) + '22',
              }]}>
                {day.effort_class}
              </Text>
            )}
          </View>
          {day.crew.length > 0 && (
            <Text numberOfLines={1} style={[s.meta, { color: c.mutedForeground }]}>
              {day.crew.map(m => m.name).join(', ')}
            </Text>
          )}
        </View>

        {hasWork && (
          <View style={s.rowRight}>
            <Text style={[s.count, { color: c.foreground }]}>
              {day.packages_delivered}
              <Text style={{ color: c.mutedForeground, fontWeight: fontWeight.regular }}>
                /{day.packages_total}
              </Text>
            </Text>
            {/* WHOSE numbers — see counts_scope. Rendering a walker's own
                stops identically to a driver's whole load was the bug. */}
            <Text style={[s.vs, { color: c.mutedForeground }]}>
              {day.counts_scope === 'truck' ? 'whole truck' : 'your stops'}
            </Text>
            {vs !== null ? (
              <Text style={[s.vs, { color: vsColor }]}>{vs.toFixed(2)}× typical</Text>
            ) : day.rts_count > 0 ? (
              <Text style={[s.vs, { color: c.mutedForeground }]}>{day.rts_count} returned</Text>
            ) : null}
          </View>
        )}
      </View>

      {day.rts_details.length > 0 && (
        <>
          <TouchableOpacity onPress={() => setOpen(o => !o)} style={s.toggle}>
            <Text style={[s.toggleText, { color: c.mutedForeground }]}>
              {open ? '▾' : '▸'} {day.rts_details.length} came back
            </Text>
          </TouchableOpacity>
          {open && (
            <View style={s.details}>
              {day.address_detail === 'block' && (
                /* Gone by POLICY (ADR-219), not by failure — without this the
                   blank reads as lost data. */
                <Text style={[s.policy, { color: c.mutedForeground }]}>
                  Street addresses are removed 48h after the route.
                </Text>
              )}
              {day.rts_details.map(r => (
                <View key={r.tba_number}>
                  <Text style={[s.detail, { color: c.mutedForeground }]}>
                    <Text style={{ color: c.foreground }}>
                      {RTS_LABEL[r.rts_type] ?? r.rts_type}
                    </Text>
                    {r.normalised_address ? ` · ${r.normalised_address}` : ''}
                    {r.is_reattemptable ? '  · retryable' : ''}
                  </Text>
                  {/* The walker's own words. rts_type is a dropdown value; this
                      is what they actually wrote, and it is the part that
                      explains the day to them a week later. */}
                  {!!r.rts_explanation && (
                    <Text style={[s.explanation, { color: c.mutedForeground }]}>
                      {r.rts_explanation}
                    </Text>
                  )}
                </View>
              ))}
            </View>
          )}
        </>
      )}

      {/* Supervised trainees (ADR-269). Visually SEPARATE from the counts
          above, never merged into them: the numbers above are the trainer's
          own executed stops, these are the trainee's. Merging them is the
          ADR-244 attribution bug and makes both unreadable. */}
      {day.supervised.map(sup => (
        <View key={sup.employee_id} style={[s.supervised, { borderLeftColor: c.primary }]}>
          <Text style={[s.supervisedName, { color: c.foreground }]}>
            {sup.name}
            <Text style={[s.supervisedRole, { color: c.mutedForeground }]}> · you supervised</Text>
          </Text>
          <Text style={[s.supervisedLine, { color: c.mutedForeground }]}>
            {sup.packages_delivered}/{sup.packages_total} delivered
            {sup.rts_count > 0 ? ` · ${sup.rts_count} back` : ''}
            {/* vs_class, not the raw rate: a trainee on a heavy route is not
                worse than one on an easy route at the same raw number. */}
            {sup.rts_rate_vs_class != null ? ` · ${sup.rts_rate_vs_class}× typical` : ''}
          </Text>
          {sup.rts_details.map(r => (
            <View key={r.tba_number}>
              <Text style={[s.detail, { color: c.mutedForeground }]}>
                <Text style={{ color: c.foreground }}>
                  {RTS_LABEL[r.rts_type] ?? r.rts_type}
                </Text>
                {r.normalised_address ? ` · ${r.normalised_address}` : ''}
                {r.is_reattemptable ? '  · retryable' : ''}
              </Text>
              {!!r.rts_explanation && (
                <Text style={[s.explanation, { color: c.mutedForeground }]}>
                  {r.rts_explanation}
                </Text>
              )}
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}

export default function RecentDaysSection() {
  const c = useColors();
  const s = styles(c);
  const [days, setDays] = useState<AssignmentDay[] | null>(null);

  useEffect(() => {
    apiClient
      .get('/assignment-history/me', {
        params: { start_date: ymd(LOOKBACK_DAYS), end_date: ymd(0) },
      })
      .then(({ data }) => setDays(data.days ?? []))
      // Silent, matching MyPerformanceCard: a stats section must not error the
      // account screen around it.
      .catch(() => setDays([]));
  }, []);

  if (!days || days.length === 0) return null;

  return (
    <View style={[s.wrap, { borderTopColor: c.border }]}>
      <View style={s.head}>
        <Text style={[s.headTitle, { color: c.foreground }]}>Recent days</Text>
        <Text style={[s.headHint, { color: c.mutedForeground }]}>last {LOOKBACK_DAYS} days</Text>
      </View>
      {days.map(d => (
        <DayRow key={`${d.route_date}-${d.truck_name ?? ''}`} day={d} />
      ))}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  wrap:      { marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1 },
  head:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: spacing.xs },
  headTitle: { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  headHint:  { fontSize: 10 },
  row:       { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, marginBottom: spacing.xs },
  rowTop:    { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm },
  rowLeft:   { flex: 1, minWidth: 0 },
  rowRight:  { alignItems: 'flex-end' },
  titleLine: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 4 },
  date:      { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  meta:      { fontSize: 11 },
  chip:      { fontSize: 9, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.5, paddingHorizontal: 5, paddingVertical: 1, borderRadius: radius.sm, overflow: 'hidden' },
  count:     { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  vs:        { fontSize: 10, marginTop: 1 },
  toggle:    { marginTop: 4 },
  toggleText:{ fontSize: 11 },
  details:   { marginTop: 4, gap: 2 },
  policy:    { fontSize: 10, fontStyle: 'italic' },
  detail:    { fontSize: 11 },
  explanation: { fontSize: 11, fontStyle: 'italic', marginLeft: spacing.xs, marginBottom: 2 },
  // Indented + left rule so a trainee's numbers read as SOMEONE ELSE'S at a
  // glance. Without the offset they sit in the same visual column as the
  // trainer's own counts and invite being read as one total.
  supervised:     { marginTop: spacing.sm, paddingLeft: spacing.sm, borderLeftWidth: 2 },
  supervisedName: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  supervisedRole: { fontSize: 11, fontWeight: fontWeight.regular },
  supervisedLine: { fontSize: 11, marginBottom: 2 },
});
