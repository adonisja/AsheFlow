// ADR-519 D5: what "Driver Needs Help" opens: that one help request.
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Copy, LifeBuoy, Phone, Truck } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import { formatDate, formatDateTime } from '../utils/date';
import type { HelpRequest } from '../api/types';

export default function HelpRequestPage() {
  const { id } = useParams<{ id: string }>();
  const [req, setReq] = useState<HelpRequest | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!id) return;
    axiosClient.get<HelpRequest>(`/shift-ops/help-requests/${id}`)
      .then(r => setReq(r.data))
      .catch(e => setError(errorText(e, 'This help request is no longer available.')));
  }, [id]);

  const copyPhone = async () => {
    if (!req?.driver.phone) return;
    try {
      await navigator.clipboard.writeText(req.driver.phone);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch { /* the number stays visible to select */ }
  };

  return (
    <div className="space-y-6 animate-slide-up max-w-2xl">
      <Link to="/dispatch" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="w-4 h-4" /> Dispatch
      </Link>
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-danger/10">
          <LifeBuoy className="w-5 h-5 text-danger" />
        </div>
        <h1 className="page-title">Help requested</h1>
      </div>

      {error && <div className="card text-sm text-muted-foreground">{error}</div>}
      {!req && !error && <div className="card text-sm text-muted-foreground">Loading…</div>}

      {req && (
        <div className="card space-y-4">
          <div>
            <p className="text-lg font-semibold text-foreground">{req.driver.name ?? 'Driver'}</p>
            <p className="text-sm text-muted-foreground">
              {req.truck ? `${req.truck.name} · ` : ''}{formatDate(req.date)}
              {req.submitted_at && ` · asked ${formatDateTime(req.submitted_at)}`}
            </p>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            {[
              ['Check-in', `#${req.check_in_number}`],
              ['Routes left', String(req.routes_remaining)],
              ['Crew working', String(req.working_crew_count)],
              ['No-shows', String(req.ncns_count)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl border border-border p-3">
                <dt className="text-xs text-muted-foreground">{k}</dt>
                <dd className="text-base font-semibold text-foreground tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap items-center gap-2">
            {req.driver.phone ? (
              <>
                <span className="text-sm font-medium text-foreground tabular-nums select-all">{req.driver.phone}</span>
                <a href={`tel:${req.driver.phone}`} className="btn-primary text-sm min-h-[44px] inline-flex items-center gap-1.5">
                  <Phone className="w-4 h-4" /> Call driver
                </a>
                <button type="button" onClick={copyPhone} className="btn-secondary text-sm min-h-[44px] inline-flex items-center gap-1.5">
                  <Copy className="w-4 h-4" /> {copied ? 'Copied' : 'Copy number'}
                </button>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">Phone not shown</span>
            )}
            {req.truck && (
              <Link to={`/anchor-points?id=${req.truck.id}&date=${req.date}`}
                className="btn-secondary text-sm min-h-[44px] inline-flex items-center gap-1.5">
                <Truck className="w-4 h-4" /> Open truck
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
