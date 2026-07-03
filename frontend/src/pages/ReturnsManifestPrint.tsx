import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import type { RemovalsResponse } from '../api/types';
import { getLocalYMD } from '../utils/date';

/**
 * Printable Returns Manifest (ADR-176) — the paper trail for handing
 * out-of-zone freight back to Amazon. One sheet: every removed/flagged unit
 * with TBAs, dock locator, counts, and signature lines.
 */

const STYLES = `
  @media print {
    body * { visibility: hidden; }
    #returns-manifest, #returns-manifest * { visibility: visible; }
    #returns-manifest { position: absolute; left: 0; top: 0; width: 100%; }
    .no-print { display: none !important; }
    #returns-manifest * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  }
  #returns-manifest { font-family: ui-sans-serif, system-ui, sans-serif; color: #111; padding: 24px 32px; }
  #returns-manifest table { width: 100%; border-collapse: collapse; font-size: 12px; }
  #returns-manifest th, #returns-manifest td { border: 1px solid #bbb; padding: 4px 6px; text-align: left; vertical-align: top; }
  #returns-manifest th { background: #f0f0f0; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  #returns-manifest .mono { font-family: ui-monospace, monospace; }
  #returns-manifest tr { page-break-inside: avoid; }
  #returns-manifest thead { display: table-header-group; }
`;

export default function ReturnsManifestPrint() {
  const [params] = useSearchParams();
  const date = params.get('date') ?? getLocalYMD();
  const [data, setData] = useState<RemovalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get<RemovalsResponse>(`/sort/${date}/removals`)
      .then(res => setData(res.data))
      .catch(() => setError('Could not load removals.'));
  }, [date]);

  if (error) return <p style={{ padding: 24 }}>{error}</p>;
  if (!data) return <p style={{ padding: 24 }}>Loading returns manifest…</p>;

  const totalPkgs = data.removals.reduce((n, r) => n + r.package_count, 0);
  const pending = data.flagged_count;
  const niceDate = new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });

  return (
    <div id="returns-manifest">
      <style>{STYLES}</style>
      <div className="no-print" style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <button
          onClick={() => window.print()}
          style={{ padding: '8px 20px', borderRadius: 8, background: '#4f46e5', color: '#fff', border: 'none', fontWeight: 600, cursor: 'pointer' }}
        >
          Print returns manifest
        </button>
        {pending > 0 && (
          <span style={{ fontSize: 13, color: '#b91c1c', fontWeight: 600 }}>
            ⚠ {pending} unit(s) not yet confirmed removed — manifest marks them PENDING
          </span>
        )}
      </div>

      <div style={{ borderLeft: '8px solid #dc2626', paddingLeft: 12, marginBottom: 14 }}>
        <h1 style={{ fontSize: 24, fontWeight: 900, margin: 0 }}>
          RETURNS MANIFEST
          <span style={{ fontSize: 13, fontWeight: 600, color: '#666', marginLeft: 10 }}>out-of-zone freight</span>
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: 13 }}>
          {niceDate} · {data.removals.length} unit{data.removals.length === 1 ? '' : 's'} ·{' '}
          <strong>{totalPkgs} package{totalPkgs === 1 ? '' : 's'}</strong> returned to station — not in our delivery area
        </p>
      </div>

      <table>
        <thead>
          <tr>
            <th style={{ width: 100 }}>Bag ID</th>
            <th style={{ width: 70 }}>Dock</th>
            <th style={{ width: 50 }}>Pkgs</th>
            <th>TBA number(s)</th>
            <th style={{ width: 130 }}>Removed by</th>
          </tr>
        </thead>
        <tbody>
          {data.removals.map(r => (
            <tr key={r.id}>
              <td className="mono" style={{ fontWeight: 700 }}>
                {r.bag_id}{r.whole_tote ? ' (whole tote)' : ''}
              </td>
              <td className="mono">{r.locator ?? '—'}</td>
              <td style={{ textAlign: 'right' }}>{r.package_count}</td>
              <td className="mono" style={{ fontSize: 11 }}>
                {r.whole_tote ? (r.tba_numbers ?? []).join(', ') : r.tba}
              </td>
              <td>
                {r.status === 'removed'
                  ? r.removed_by_name ?? '✓'
                  : <strong style={{ color: '#b91c1c' }}>PENDING</strong>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: 40, marginTop: 22, fontSize: 12 }}>
        <span>Released by (dispatch): ______________________</span>
        <span>Received by (station): ______________________</span>
        <span>Time: ____________</span>
      </div>
    </div>
  );
}
