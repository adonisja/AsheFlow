import * as XLSX from 'xlsx';
import type { Seed, SeedBag, SeedStop } from './walkerLogSeed';

/** Reads a dispatch workbook in the browser and returns one manifest per BTR.
 *
 *  A workbook is the day's WHOLE FLEET — one worksheet per truck (ADR-411) —
 *  so this returns every sheet it can parse rather than asking which one to
 *  read. Which BTR you work is a separate choice, made after import.
 *
 *  The sheet layout is fixed by the dispatch export:
 *
 *    row 1   Route | Service Type | DSP | Dispatch Time | Anchor Point | ...
 *    row 2   BTR31 | Box Truck ...              | 40.75603  -73.99675
 *    row 3   Stops for this Route                        | Pick List
 *    row 4   Dispatch Time | Duration | Name | Package Count | Bag Count |
 *            OV Count | OV Sort Zones | Bag Labels | Bag Sort Zones
 *    row 5+  one row per BAG; the stop columns are filled only on the FIRST
 *            row of each stop and blank on continuation rows.
 *
 *  That last detail is the whole parsing problem: a stop with three bags
 *  occupies three rows, and rows two and three carry nothing but a bag label.
 *  Reading each row independently would invent stops with null package counts.
 */

export interface ParsedSheet {
  btr: string;
  anchor: string;
  stops: SeedStop[];
  bags: SeedBag[];
  /** Declared-vs-found bag mismatches. Surfaced, never silently corrected —
   *  a sheet that disagrees with itself is worth a human looking at it. */
  warnings: string[];
}

type Cell = string | number | null | undefined;
const str = (v: Cell): string => (v === null || v === undefined ? '' : String(v).trim());
const num = (v: Cell): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

function parseSheet(name: string, rows: Cell[][]): ParsedSheet | null {
  // Row 2 carries the BTR label and the anchor point.
  const meta = rows[1] ?? [];
  const btr = str(meta[0]) || name;
  const anchor = str(meta[4]);
  if (!/^BTR/i.test(btr)) return null;          // not a truck sheet

  const stops: SeedStop[] = [];
  const bags: SeedBag[] = [];
  const warnings: string[] = [];
  let cur: { stop: SeedStop; declared: number | null; bags: SeedBag[] } | null = null;

  const flush = () => {
    if (!cur) return;
    // Backfill each bag with its stop's totals — the sort compares a route's
    // load against these, and they live on the stop, not the bag.
    for (const b of cur.bags) b.stop_bag_count = cur.bags.length;
    if (cur.declared !== null && cur.declared !== cur.bags.length) {
      warnings.push(`${cur.stop.stop}: sheet says ${cur.declared} bags, found ${cur.bags.length}`);
    }
    cur.stop.bag_ids = cur.bags.map((b) => b.bag_id);
    stops.push(cur.stop);
    bags.push(...cur.bags);
  };

  for (const r of rows.slice(4)) {
    const stopName = str(r[2]);
    if (stopName) {
      flush();
      cur = {
        stop: {
          stop: stopName,
          dispatch_time: str(r[0]) || null,
          duration: str(r[1]) || null,
          package_count: num(r[3]),
          ov_count: num(r[5]),
          ov_zones: str(r[6]).replace(/_x000D_\n/g, ' / ').trim(),
          bag_ids: [],
        },
        declared: num(r[4]),
        bags: [],
      };
    }
    const label = str(r[7]);
    if (label && cur) {
      cur.bags.push({
        bag_id: label,
        sort_zone: str(r[8]),
        stop: cur.stop.stop,
        stop_package_count: cur.stop.package_count ?? 0,
        stop_ov_count: cur.stop.ov_count ?? 0,
        stop_bag_count: 0,                       // set in flush()
      });
    }
  }
  flush();

  if (stops.length === 0) return null;

  const ids = bags.map((b) => b.bag_id);
  const dupes = [...new Set(ids.filter((x, i) => ids.indexOf(x) !== i))];
  if (dupes.length) warnings.push(`duplicate bag labels: ${dupes.join(', ')}`);

  return { btr, anchor, stops, bags, warnings };
}

export interface WorkbookResult {
  sheets: ParsedSheet[];
  /** Sheets that were present but held no truck data. */
  skipped: string[];
}

export async function parseWorkbook(file: Blob): Promise<WorkbookResult> {
  const wb = XLSX.read(await file.arrayBuffer(), { type: 'array' });
  const sheets: ParsedSheet[] = [];
  const skipped: string[] = [];
  for (const name of wb.SheetNames) {
    const rows = XLSX.utils.sheet_to_json<Cell[]>(wb.Sheets[name], {
      header: 1, blankrows: true, defval: null,
    });
    const parsed = parseSheet(name, rows);
    if (parsed) sheets.push(parsed); else skipped.push(name);
  }
  return { sheets, skipped };
}

/** A parsed sheet as the Seed shape the page already consumes. */
export const toSeed = (date: string, s: ParsedSheet): Seed => ({
  btr: s.btr, date, anchor: s.anchor, stops: s.stops, bags: s.bags,
});
