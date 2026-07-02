import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import type { RostersResponse, TruckRoster } from '../api/types';
import { getLocalYMD } from '../utils/date';

/**
 * Printable per-truck load sheets (ADR-174).
 *
 * One page per truck: header (truck, driver, date, totals), rows in dock-tag
 * order — bag id, dock tag, package count, OV summary with OV dock zones,
 * transfer annotations, and a pen check-off box. Client-side print via
 * @media print CSS; renders from the same rosters endpoint as the screens.
 */

const PRINT_STYLES = `
  @media print {
    body * { visibility: hidden; }
    #load-sheets, #load-sheets * { visibility: visible; }
    #load-sheets { position: absolute; left: 0; top: 0; width: 100%; }
    .sheet { page-break-after: always; }
    .no-print { display: none !important; }
  }
  #load-sheets { font-family: ui-sans-serif, system-ui, sans-serif; color: #111; }
  #load-sheets table { width: 100%; border-collapse: collapse; font-size: 12px; }
  #load-sheets th, #load-sheets td { border: 1px solid #bbb; padding: 4px 6px; text-align: left; }
  #load-sheets th { background: #f0f0f0; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  #load-sheets .mono { font-family: ui-monospace, monospace; }
  #load-sheets .checkbox { width: 16px; height: 16px; border: 1.5px solid #444; display: inline-block; }
`;

function Sheet({ roster, date }: { roster: TruckRoster; date: string }) {
  const totalPkgs = roster.totes.reduce((n, t) => n + t.package_count, 0);
  const totalOvs = roster.totes.reduce((n, t) => n + t.ov_count, 0);
  return (
    <div className="sheet" style={{ padding: '24px 32px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>{roster.zone_label}</h1>
        <span style={{ fontSize: 13 }}>{date}</span>
      </div>
      <p style={{ margin: '2px 0 12px', fontSize: 13 }}>
        Driver: <strong>{roster.driver_name ?? '____________________'}</strong>
        {'   ·   '}{roster.totes.length} totes · {totalPkgs.toLocaleString()} packages · {totalOvs} OVs
      </p>

      {(roster.incoming.length > 0 || roster.outgoing.length > 0) && (
        <div style={{ margin: '0 0 10px', fontSize: 12, border: '1.5px solid #444', padding: '6px 8px' }}>
          <strong>Station transfers:</strong>
          {roster.incoming.map(t => (
            <div key={t.id}>
              ⬅ RECEIVE <span className="mono">{t.bag_id}</span> ({t.package_count ?? '?'} pkgs) from{' '}
              <strong>{t.from_truck_name}</strong>{t.from_driver_name ? ` — ${t.from_driver_name}` : ''}
            </div>
          ))}
          {roster.outgoing.map(t => (
            <div key={t.id}>
              ➡ HAND OFF <span className="mono">{t.bag_id}</span> ({t.package_count ?? '?'} pkgs) to{' '}
              <strong>{t.to_truck_name}</strong>{t.to_driver_name ? ` — ${t.to_driver_name}` : ''}
            </div>
          ))}
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th style={{ width: 30 }}>✓</th>
            <th>Bag ID</th>
            <th>Dock</th>
            <th style={{ width: 50 }}>Pkgs</th>
            <th>OVs (size @ OV zone)</th>
            <th>Transfer</th>
          </tr>
        </thead>
        <tbody>
          {roster.totes.map(t => (
            <tr key={t.bag_id}>
              <td><span className="checkbox" /></td>
              <td className="mono" style={{ fontWeight: 700 }}>{t.bag_id}</td>
              <td className="mono">{t.dock_tags.join(', ')}</td>
              <td style={{ textAlign: 'right' }}>{t.package_count}</td>
              <td>
                {t.ov_count > 0
                  ? `${t.ov_count} — ${t.ov_sizes.map(s => s.replace('OV_', '')).join(', ')}`
                    + (t.ov_dock_tags.length ? ` @ ${t.ov_dock_tags.join(', ')}` : '')
                  : ''}
              </td>
              <td>
                {t.transfer
                  ? t.transfer.to_truck_id === roster.truck_id
                    ? `⬅ from ${t.transfer.from_truck_name}`
                    : `➡ to ${t.transfer.to_truck_name}`
                  : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PrintLoadSheets() {
  const [params] = useSearchParams();
  const date = params.get('date') ?? getLocalYMD();
  const [data, setData] = useState<RostersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get<RostersResponse>(`/sort/${date}/rosters`)
      .then(res => setData(res.data))
      .catch(() => setError('Could not load rosters for printing.'));
  }, [date]);

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
          {date} · one page per truck, totes in dock order
          {!data.loading_finalized && ' · ⚠ loading not finalized — sheets reflect current assignment'}
        </span>
      </div>
      {data.rosters.map(r => <Sheet key={r.zone_id} roster={r} date={date} />)}
    </div>
  );
}
