import * as XLSX from 'xlsx';
import {
  durationMin,
  type Cell, type LogRoute, type LogTote, type UnclaimedForExport, type WalkerDay,
} from './walkerLogDb';

/** Workbook export for the walker log.
 *
 *  CSV is the interchange format; this is the one you actually open. It exists
 *  because the analysis is done in a spreadsheet and CSV loses the two things
 *  that matter there:
 *
 *    1. TYPES. Every CSV cell is text, so `route_minutes` arrives as a string
 *       and AVERAGE() over the column returns nothing. Here numbers stay
 *       numbers, so the columns are immediately chartable.
 *    2. STRUCTURE. A workbook holds several sheets, so the per-address detail
 *       does not have to be crushed into a pipe-joined cell on the route row.
 *
 *  ONE sheet, one row per address, with walker -> route -> tote -> address on
 *  every row. See chainRows below for why it is denormalised rather than split
 *  by grain.
 */

/** Column widths, in characters. A default-width sheet shows "12 Main St, A…"
 *  and a wall of truncated addresses is unreadable, so the wide text columns
 *  get real room and the numeric ones stay narrow. */
const WIDTHS = [
  11,  // date
  20,  // walker
  8,   // route_id
  8,   // route_start
  8,   // route_end
  8,   // route_minutes
  10,  // difficulty
  6,   // unit
  16,  // bag_id
  8,   // ov_size
  9,   // stop
  11,  // sort_zone
  52,  // address
  10,  // stop_packages
  8,   // stop_ovs
  8,   // stop_bags
  8,   // arrival_time
  9,   // departure_time
  8,   // day_minutes
  40,  // rts
  40,  // notes
];

const HEADER = [
  'date', 'walker', 'route_id', 'route_start', 'route_end', 'route_minutes',
  // 'unit' distinguishes a tote row from an OV row. Without it an OV's address
  // is indistinguishable from a tote's, and counting deliveries per bag would
  // silently fold loose oversized packages into whichever bag sorted nearby.
  'difficulty', 'unit', 'bag_id', 'ov_size', 'stop', 'sort_zone', 'address',
  'stop_packages', 'stop_ovs', 'stop_bags',
  'arrival_time', 'departure_time', 'day_minutes', 'rts', 'notes',
];

/** ONE SHEET, one row per ADDRESS, carrying the whole chain on every row:
 *  walker -> route -> tote -> address.
 *
 *  The first cut had three sheets (Routes, Addresses, Totes) and that was the
 *  wrong instinct. Splitting by grain means the relationship you actually want
 *  to see — which addresses this walker carried, in which bag, on which route —
 *  is spread across three tables that must be joined by hand before they say
 *  anything. A spreadsheet is not a database; the join has to be done already.
 *
 *  So the chain is denormalised onto every row. Sorting or filtering by walker
 *  gives their whole day, bag by bag and address by address, in order.
 *
 *  WHAT THIS COSTS, AND WHY IT IS STILL RIGHT: route-level values (minutes,
 *  difficulty, day_minutes) REPEAT down a route's rows, so summing
 *  `route_minutes` over the sheet multiplies by the address count. That is the
 *  known trade of a denormalised table. The defence is that the repeated values
 *  are constant per route_id, so a pivot on route_id with MAX or AVERAGE — not
 *  SUM — recovers the true per-route figure, and the header comment below says
 *  so in the file itself.
 *
 *  Rows with no addresses still appear (blank address cell): a tote whose
 *  addresses were never filled in, or a route that carried none, is a fact
 *  about the day rather than something to hide.
 */
function chainRows(days: WalkerDay[], unclaimed: UnclaimedForExport): Cell[][] {
  const out: Cell[][] = [];

  const push = (date: string, walker: string, arrival: string, departure: string, routes: LogRoute[]) => {
    const dayMin = durationMin(arrival, departure);
    for (const r of routes) {
      const routeMin = durationMin(r.route_start, r.route_end);
      // RTS belongs to the route, not to a bag, so it rides on the route's
      // first row only — repeating it beside every address would read as one
      // RTS per address.
      let rtsCell: Cell = r.rts.map((x) => `${x.tba}:${x.code}:${x.reason}`).join(' | ');
      let notesCell: Cell = r.notes;

      const emit = (
        unit: string, t: LogTote | null, address: string,
        ovId = '', ovSize = '', ovZone = '',
      ) => {
        out.push([
          date, walker, r.route_id, r.route_start, r.route_end, routeMin,
          r.difficulty,
          unit, unit === 'OV' ? ovId : (t?.bag_id ?? ''), ovSize,
          t?.stop ?? '', unit === 'OV' ? ovZone : (t?.sort_zone ?? ''), address,
          t?.stop_package_count ?? null, t?.stop_ov_count ?? null, t?.stop_bag_count ?? null,
          arrival, departure, dayMin,
          rtsCell, notesCell,
        ]);
        rtsCell = '';
        notesCell = '';
      };

      const ovs = r.ovs ?? [];
      if (r.totes.length === 0 && ovs.length === 0) { emit('', null, ''); continue; }
      for (const t of r.totes) {
        if (t.addresses.length === 0) { emit('tote', t, ''); continue; }
        for (const a of t.addresses) emit('tote', t, a);
      }
      // OVs after the totes, so a route reads bags-then-loose-freight.
      for (const o of ovs) emit('OV', null, o.address, o.ov_id, o.size, o.sort_zone);
    }
  };

  for (const d of days) push(d.date, d.name, d.arrival_time, d.departure_time, d.routes);
  // An unclaimed route has no walker — the empty cell is the point, and filters
  // on walker == "" isolate work nobody picked up.
  if (unclaimed && unclaimed.routes.length > 0) {
    push(unclaimed.date, '', '', '', unclaimed.routes);
  }
  return out;
}

/** Builds the workbook and hands back the bytes. The caller downloads them —
 *  this module does no DOM work, so it stays testable. */
export function buildWorkbook(
  sections: { days: WalkerDay[]; unclaimed: UnclaimedForExport }[],
): Blob {
  const rows = sections.flatMap((s) => chainRows(s.days, s.unclaimed));

  const ws = XLSX.utils.aoa_to_sheet([HEADER, ...rows]);
  ws['!cols'] = WIDTHS.map((w) => ({ wch: w }));
  // NO FREEZE PANES. `!freeze` and `!views` are both inert in the community
  // build of xlsx 0.18.5 — verified by unzipping the output and finding no
  // <pane> element for any spelling — so writing one would be a line that
  // silently does nothing. The autofilter below is what the build DOES honour,
  // and it gives the header row dropdowns, which is the part that matters.
  if (rows.length > 0) {
    ws['!autofilter'] = {
      ref: XLSX.utils.encode_range({
        s: { r: 0, c: 0 }, e: { r: rows.length, c: HEADER.length - 1 },
      }),
    };
  }

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Walker log');

  const out = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer;
  return new Blob([out], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}
