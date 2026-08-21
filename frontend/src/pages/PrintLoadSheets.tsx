import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import type { RostersResponse, TruckRoster, RosterTote } from '../api/types';
import { getLocalYMD } from '../utils/date';

/**
 * Printable per-truck load sheets (ADR-174) — the driver's physical manifest.
 *
 * Designed around the loading workflow, not the data model:
 *   1. STATION TRANSFERS up top — the exceptions, impossible to miss.
 *   2. OV PICKUP BY ZONE — one table row per OV staging zone so the driver
 *      visits each zone exactly once and can verify counts on the spot.
 *   3. BAG CHECKLIST grouped by dock aisle in walk order — dock tag is the
 *      big lookup key, one check box per bag.
 *   4. Signature line for load/verify accountability.
 *
 * Color rules: truck accent bar ties the sheet to the map color; OV zones get
 * fixed hues; everything is labeled so greyscale printers lose nothing.
 */

// Same stable palette + ordering rule as ZoneDensityMap: sorted truck ids.
const TRUCK_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#a855f7', '#ec4899', '#14b8a6'];

const OV_ZONE_COLORS: Record<string, string> = {
  'OV-1': '#2563eb',
  'OV-2': '#d97706',
  'OV-3': '#7c3aed',
  'OV-4': '#0d9488',
};
const ovZoneColor = (zone: string) => OV_ZONE_COLORS[zone] ?? '#525252';

const SIZE_ORDER = ['S', 'M', 'L', 'XL'];

const PRINT_STYLES = `
  @media print {
    body * { visibility: hidden; }
    #load-sheets, #load-sheets * { visibility: visible; }
    #load-sheets { position: absolute; left: 0; top: 0; width: 100%; }
    .sheet { page-break-after: always; }
    .no-print { display: none !important; }
    #load-sheets * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  }
  #load-sheets { font-family: ui-sans-serif, system-ui, sans-serif; color: #111; }
  #load-sheets table { width: 100%; border-collapse: collapse; }
  #load-sheets thead { display: table-header-group; }   /* headers repeat on every printed page */
  #load-sheets tr { page-break-inside: avoid; }
  #load-sheets .mono { font-family: ui-monospace, 'SF Mono', monospace; }
  #load-sheets .checkbox { width: 18px; height: 18px; border: 2px solid #333; border-radius: 3px; display: inline-block; }
  #load-sheets .stat { display: inline-block; border: 1.5px solid #ccc; border-radius: 6px; padding: 3px 10px; margin-right: 8px; font-size: 12px; }
  #load-sheets .stat b { font-size: 15px; }
  #load-sheets .zone-chip { display: inline-block; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 700; }
`;

/** ov_details → { zone → { size → count } }, zones sorted. */
function ovByZone(totes: RosterTote[]): Map<string, Record<string, number>> {
  const zones = new Map<string, Record<string, number>>();
  totes.forEach(t => (t.ov_details ?? []).forEach(d => {
    const zone = d.zone ?? '?';
    const size = d.size.replace('OV_', '');
    const bucket = zones.get(zone) ?? {};
    bucket[size] = (bucket[size] ?? 0) + 1;
    zones.set(zone, bucket);
  }));
  return new Map([...zones.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

/** Compact per-bag OV cell: one chip per zone + size counts ("2L 1S"). */
function BagOvCell({ tote }: { tote: RosterTote }) {
  const zones = ovByZone([tote]);
  if (zones.size === 0) return null;
  return (
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
      {[...zones.entries()].map(([zone, sizes]) => (
        <span key={zone} style={{ whiteSpace: 'nowrap' }}>
          <span className="zone-chip" style={{ background: ovZoneColor(zone) }}>{zone}</span>
          <span style={{ fontSize: 11, marginLeft: 3 }}>
            {SIZE_ORDER.filter(s => sizes[s]).map(s => `${sizes[s]}${s}`).join(' ')}
          </span>
        </span>
      ))}
    </span>
  );
}

function Sheet({ roster, date, accent, finalized }: {
  roster: TruckRoster; date: string; accent: string; finalized: boolean;
}) {
  const totalPkgs = roster.totes.reduce((n, t) => n + t.package_count, 0);
  const totalOvs = roster.totes.reduce((n, t) => n + t.ov_count, 0);
  const ovZones = ovByZone(roster.totes);

  // Group bags by dock aisle (tag prefix before the dash), preserving the
  // dock-walk order the roster already has.
  const aisles: { aisle: string; totes: RosterTote[] }[] = [];
  roster.totes.forEach(t => {
    const aisle = t.dock_tags[0]?.split('-')[0] ?? '—';
    const last = aisles[aisles.length - 1];
    if (last && last.aisle === aisle) last.totes.push(t);
    else aisles.push({ aisle, totes: [t] });
  });

  const niceDate = new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });

  return (
    <div className="sheet" style={{ padding: '20px 28px' }}>
      {/* Header: truck identity, tied to the map color */}
      <div style={{ borderLeft: `8px solid ${accent}`, paddingLeft: 12, marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <h1 style={{ fontSize: 26, fontWeight: 900, margin: 0, letterSpacing: '0.02em' }}>
            {roster.zone_label}
            <span style={{ fontSize: 13, fontWeight: 600, color: '#666', marginLeft: 10 }}>LOAD SHEET</span>
          </h1>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{niceDate}</span>
        </div>
        <div style={{ fontSize: 14, margin: '2px 0 8px' }}>
          Driver: <strong>{roster.driver_name ?? '____________________'}</strong>
          {!finalized && (
            <span style={{ color: '#b91c1c', fontWeight: 700, fontSize: 11, marginLeft: 12 }}>
              ⚠ PRELIMINARY — loading not finalized when printed
            </span>
          )}
        </div>
        <div>
          <span className="stat"><b>{roster.totes.length}</b> totes</span>
          <span className="stat"><b>{totalPkgs.toLocaleString()}</b> packages</span>
          <span className="stat"><b>{totalOvs}</b> OVs</span>
          {(roster.incoming.length + roster.outgoing.length) > 0 && (
            <span className="stat" style={{ borderColor: '#d97706', color: '#92400e' }}>
              <b>{roster.incoming.length + roster.outgoing.length}</b> transfers
            </span>
          )}
        </div>
      </div>

      {/* 1. Station transfers — the exceptions come first */}
      {(roster.incoming.length > 0 || roster.outgoing.length > 0) && (
        <div style={{ margin: '0 0 12px', border: '2px solid #d97706', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ background: '#fef3c7', padding: '4px 10px', fontSize: 12, fontWeight: 800, letterSpacing: '0.05em' }}>
            ⇄ STATION TRANSFERS — complete before departure
          </div>
          <div style={{ padding: '6px 10px', fontSize: 13 }}>
            {roster.incoming.map(t => (
              <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', color: '#166534' }}>
                <span className="checkbox" style={{ borderColor: '#166534' }} />
                <b>RECEIVE</b> <span className="mono" style={{ fontWeight: 700 }}>{t.bag_id}</span>
                ({t.package_count ?? '?'} pkgs) from <b>{t.from_truck_name}</b>
                {t.from_driver_name ? ` — ${t.from_driver_name}` : ''}
              </div>
            ))}
            {roster.outgoing.map(t => (
              <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', color: '#b91c1c' }}>
                <span className="checkbox" style={{ borderColor: '#b91c1c' }} />
                <b>HAND OFF</b> <span className="mono" style={{ fontWeight: 700 }}>{t.bag_id}</span>
                ({t.package_count ?? '?'} pkgs) to <b>{t.to_truck_name}</b>
                {t.to_driver_name ? ` — ${t.to_driver_name}` : ''}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2. OV pickup by zone — one visit per zone, verify counts on the spot */}
      {ovZones.size > 0 && (
        <div style={{ margin: '0 0 12px' }}>
          <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.05em', marginBottom: 4 }}>
            OV PICKUP BY ZONE <span style={{ fontWeight: 400, color: '#666' }}>— collect at each zone, then match to bags below</span>
          </div>
          <table style={{ maxWidth: 460 }}>
            <thead>
              <tr style={{ fontSize: 10 }}>
                <th style={{ border: '1px solid #bbb', padding: '3px 8px', background: '#f3f4f6' }}>Zone</th>
                {SIZE_ORDER.map(s => (
                  <th key={s} style={{ border: '1px solid #bbb', padding: '3px 8px', background: '#f3f4f6', textAlign: 'center', width: 44 }}>{s}</th>
                ))}
                <th style={{ border: '1px solid #bbb', padding: '3px 8px', background: '#f3f4f6', textAlign: 'center', width: 54 }}>Total</th>
                <th style={{ border: '1px solid #bbb', padding: '3px 8px', background: '#f3f4f6', width: 40 }}>✓</th>
              </tr>
            </thead>
            <tbody>
              {[...ovZones.entries()].map(([zone, sizes]) => {
                const total = Object.values(sizes).reduce((a, b) => a + b, 0);
                return (
                  <tr key={zone} style={{ fontSize: 12 }}>
                    <td style={{ border: '1px solid #bbb', padding: '3px 8px' }}>
                      <span className="zone-chip" style={{ background: ovZoneColor(zone) }}>{zone}</span>
                    </td>
                    {SIZE_ORDER.map(s => (
                      <td key={s} style={{ border: '1px solid #bbb', padding: '3px 8px', textAlign: 'center', fontWeight: sizes[s] ? 700 : 400, color: sizes[s] ? '#111' : '#bbb' }}>
                        {sizes[s] ?? '—'}
                      </td>
                    ))}
                    <td style={{ border: '1px solid #bbb', padding: '3px 8px', textAlign: 'center', fontWeight: 800 }}>{total}</td>
                    <td style={{ border: '1px solid #bbb', padding: '3px 8px', textAlign: 'center' }}><span className="checkbox" style={{ width: 14, height: 14 }} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 3. Bag checklist, aisle by aisle in dock-walk order */}
      <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.05em', marginBottom: 4 }}>
        BAG CHECKLIST <span style={{ fontWeight: 400, color: '#666' }}>— walk the dock in order</span>
      </div>
      <table>
        <thead>
          <tr style={{ fontSize: 10 }}>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6', width: 34 }}>✓</th>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6', width: 70 }}>Dock</th>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6', width: 110 }}>Bag ID</th>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6', width: 50, textAlign: 'right' }}>Pkgs</th>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6' }}>OV pickup</th>
            <th style={{ border: '1px solid #bbb', padding: '3px 6px', background: '#f3f4f6', width: 150 }}>Transfer</th>
          </tr>
        </thead>
        {aisles.map(group => (
          <tbody key={group.aisle + group.totes[0]?.bag_id}>
            <tr>
              <td colSpan={6} style={{ background: '#e5e7eb', borderLeft: `6px solid ${accent}`, padding: '3px 8px', fontSize: 11, fontWeight: 800, letterSpacing: '0.06em' }}>
                AISLE {group.aisle} · {group.totes.length} tote{group.totes.length === 1 ? '' : 's'}
              </td>
            </tr>
            {group.totes.map((t, i) => {
              const incoming = t.transfer && t.transfer.to_truck_id === roster.truck_id;
              const outgoing = t.transfer && t.transfer.to_truck_id !== roster.truck_id;
              return (
                <tr key={t.bag_id} style={{
                  fontSize: 12,
                  background: outgoing ? '#fee2e2' : incoming ? '#dcfce7' : i % 2 ? '#fafafa' : '#fff',
                }}>
                  <td style={{ border: '1px solid #bbb', padding: '4px 6px', textAlign: 'center' }}><span className="checkbox" /></td>
                  <td className="mono" style={{ border: '1px solid #bbb', padding: '4px 6px', fontSize: 15, fontWeight: 900 }}>
                    {t.dock_tags[0] ?? '—'}
                  </td>
                  <td className="mono" style={{ border: '1px solid #bbb', padding: '4px 6px', fontWeight: 700 }}>{t.bag_id}</td>
                  <td style={{ border: '1px solid #bbb', padding: '4px 6px', textAlign: 'right', fontWeight: 700 }}>{t.package_count}</td>
                  <td style={{ border: '1px solid #bbb', padding: '4px 6px' }}><BagOvCell tote={t} /></td>
                  <td style={{ border: '1px solid #bbb', padding: '4px 6px', fontSize: 11, fontWeight: 700, color: outgoing ? '#b91c1c' : incoming ? '#166534' : '#111' }}>
                    {t.transfer && (incoming
                      ? `⬅ from ${t.transfer.from_truck_name}`
                      : `➡ to ${t.transfer!.to_truck_name} — DO NOT LOAD`)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>

      {/* 4. Accountability footer */}
      <div style={{ display: 'flex', gap: 40, marginTop: 18, fontSize: 12 }}>
        <span>Loaded by: ______________________</span>
        <span>Verified by: ______________________</span>
        <span>Time: ____________</span>
      </div>
    </div>
  );
}

export default function PrintLoadSheets() {
  const [params] = useSearchParams();
  const date = params.get('date') ?? getLocalYMD();
  const truckFilter = params.get('truck');
  const [data, setData] = useState<RostersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get<RostersResponse>(`/sort/${date}/rosters`)
      .then(res => setData(res.data))
      .catch(() => setError('Could not load rosters for printing.'));
  }, [date]);

  // Stable truck→accent mapping: sorted truck ids, same rule as the map.
  const accents = useMemo(() => {
    const ids = [...new Set((data?.rosters ?? []).map(r => r.truck_id))].sort();
    return new Map(ids.map((id, i) => [id, TRUCK_COLORS[i % TRUCK_COLORS.length]]));
  }, [data]);

  if (error) return <p style={{ padding: 24 }}>{error}</p>;
  if (!data) return <p style={{ padding: 24 }}>Loading load sheets…</p>;

  return (
    <div id="load-sheets">
      <style>{PRINT_STYLES}</style>
      <div className="no-print" style={{ padding: '16px 32px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <button
          onClick={() => window.print()}
          style={{ padding: '8px 20px', borderRadius: 8, background: '#4f46e5', color: '#fff', border: 'none', fontWeight: 600, cursor: 'pointer' }}
        >
          Print {data.rosters.length} sheet{data.rosters.length === 1 ? '' : 's'}
        </button>
        <span style={{ fontSize: 13, color: '#666' }}>
          {date} · one sheet per truck · transfers → OV zones → aisle-by-aisle checklist
          {!data.loading_finalized && ' · ⚠ loading not finalized — sheets are marked PRELIMINARY'}
        </span>
      </div>
      {data.rosters.filter(r => !truckFilter || r.truck_id === truckFilter).map(r => (
        <Sheet
          key={r.zone_id}
          roster={r}
          date={date}
          accent={accents.get(r.truck_id) ?? '#6366f1'}
          finalized={data.loading_finalized}
        />
      ))}
    </div>
  );
}
