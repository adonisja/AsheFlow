/**
 * The survey register: start a walk (ADR-504, ADR-513).
 *
 * Phone first: this is used standing on a sidewalk. The order of the page is
 * the order of the work:
 *   1. three confirmations (ADR-504 D2), which the server also enforces;
 *   2. your claimed blocks: start, continue, or give one back;
 *   3. the open survey areas, where blocks are claimed (ADR-513 D3);
 *   4. the owner only: scout a block outside every area (ADR-513 D5).
 *
 * The owner also sees the most recent observations at the bottom.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronDown, ChevronRight, LocateFixed, Loader2, MapPin, Play, Search, Undo2 } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import SectionHeader from '../../components/ui/SectionHeader';
import { formatDate } from '../../utils/date';
import { errorText } from '../../utils/errorText';
import { useAuth } from '../../contexts/AuthContext';
import { buildingTypeLabel } from '../../utils/addressProfile';
import type {
  SurveyArea, SurveyBlock, SurveyClaim, SurveyObservation, SurveyStartWalk, SurveyWalk,
} from '../../api/types';
import { ProgressBar, timeLeft } from './surveyUi';

const CONFIRMATIONS = [
  { key: 'attest_off_shift', label: "I'm off-shift. I'm not on any route or block for any carrier." },
  { key: 'attest_unbranded', label: 'No branded van, uniform, work phone or delivery app.' },
  { key: 'attest_as_self', label: "I'm asking as myself, not as a delivery driver." },
] as const;

type ConfirmKey = typeof CONFIRMATIONS[number]['key'];

const SOURCE_LABEL: Record<string, string> = {
  observed: 'seen', front_desk: 'front desk', mailroom: 'mailroom', security: 'security',
};

export default function SurveyStart() {
  const navigate = useNavigate();
  const { groups } = useAuth();
  const isOwner = groups.includes('super_admin');

  const [confirmed, setConfirmed] = useState<Record<ConfirmKey, boolean>>({
    attest_off_shift: false, attest_unbranded: false, attest_as_self: false,
  });
  const allConfirmed = Object.values(confirmed).every(Boolean);

  const [claims, setClaims] = useState<SurveyClaim[] | null>(null);
  const [areas, setAreas] = useState<SurveyArea[] | null>(null);
  const [openWalks, setOpenWalks] = useState<SurveyWalk[]>([]);
  const [recent, setRecent] = useState<SurveyObservation[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Owner scouting (ADR-513 D5): the old find-a-block-near-you path.
  const [scouting, setScouting] = useState(false);
  const [point, setPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [typed, setTyped] = useState('');
  const [blocks, setBlocks] = useState<SurveyBlock[] | null>(null);

  const load = useCallback(() => {
    axiosClient.get<SurveyClaim[]>('/survey/claims').then(r => setClaims(r.data))
      .catch(e => { setClaims([]); setError(errorText(e, "Couldn't load your blocks.")); });
    axiosClient.get<SurveyArea[]>('/survey/areas').then(r => setAreas(r.data))
      .catch(e => { setAreas([]); setError(errorText(e, "Couldn't load the survey areas.")); });
    axiosClient.get<SurveyWalk[]>('/survey/walks', { params: { limit: 10 } })
      .then(r => setOpenWalks(r.data.filter(w => !w.closed_at)))
      .catch(() => { /* the rest of the page works without the list */ });
    if (isOwner) {
      axiosClient.get<SurveyObservation[]>('/survey/observations', { params: { limit: 20 } })
        .then(r => setRecent(r.data)).catch(() => {});
    }
  }, [isOwner]);
  useEffect(() => { load(); }, [load]);

  const startClaimed = async (c: SurveyClaim) => {
    setBusy(c.id);
    setError(null);
    try {
      const { data } = await axiosClient.post<SurveyWalk>(`/survey/claims/${c.id}/walk`, confirmed);
      navigate(`/survey/walk/${data.id}`);
    } catch (e) {
      setError(errorText(e, "Couldn't start the walk."));
      setBusy(null);
    }
  };

  const release = async (c: SurveyClaim) => {
    setBusy(c.id);
    setError(null);
    try {
      await axiosClient.post(`/survey/claims/${c.id}/release`);
      load();
    } catch (e) {
      setError(errorText(e, "Couldn't give the block back."));
    } finally {
      setBusy(null);
    }
  };

  const loadBlocks = async (p: { lat: number; lng: number }) => {
    setPoint(p);
    setBusy('blocks');
    setError(null);
    try {
      const { data } = await axiosClient.get<SurveyBlock[]>('/survey/blocks', { params: { ...p, radius_m: 150 } });
      setBlocks(data);
    } catch (e) {
      setError(errorText(e, "Couldn't load the city's address list."));
    } finally {
      setBusy(null);
    }
  };

  const useLocation = () => {
    if (!('geolocation' in navigator)) {
      setError('This browser has no location. Type an address instead.');
      return;
    }
    setBusy('locate');
    navigator.geolocation.getCurrentPosition(
      pos => { void loadBlocks({ lat: pos.coords.latitude, lng: pos.coords.longitude }); },
      () => { setBusy(null); setError('Location was refused or unavailable. Type an address instead.'); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  };

  const locateTyped = async () => {
    setBusy('locate');
    setError(null);
    try {
      const { data } = await axiosClient.get<{ lat: number; lng: number }>('/survey/locate', { params: { address: typed.trim() } });
      await loadBlocks(data);
    } catch (e) {
      setBusy(null);
      setError(errorText(e, "Couldn't find that address."));
    }
  };

  const scout = async (block: SurveyBlock) => {
    if (!point) return;
    setBusy(block.block_key);
    setError(null);
    try {
      const body: SurveyStartWalk = { ...point, radius_m: 150, block_key: block.block_key, ...confirmed };
      const { data } = await axiosClient.post<SurveyWalk>('/survey/walks', body);
      navigate(`/survey/walk/${data.id}`);
    } catch (e) {
      setError(errorText(e, "Couldn't start the walk."));
      setBusy(null);
    }
  };

  // A claimed block's open walk is shown on its claim, not twice.
  const claimedWalks = new Set((claims ?? []).map(c => c.walk_id).filter(Boolean));
  const otherWalks = openWalks.filter(w => !claimedWalks.has(w.id));

  return (
    <main className="mx-auto max-w-xl px-4 py-6 space-y-5">
      <SectionHeader eyebrow="Survey register" title="Walk a block"
        description="Doors come from the city's own address list. Record only what you can see, or what building staff tell you when you ask as yourself." />

      <ErrorBanner message={error} />

      <section className="card p-4 space-y-3" aria-labelledby="confirm-h">
        <h2 id="confirm-h" className="text-sm font-semibold">1. Before you start</h2>
        {CONFIRMATIONS.map(c => (
          <label key={c.key} className="flex min-h-11 items-start gap-3 rounded-lg border border-border p-3 text-sm">
            <input type="checkbox" className="mt-0.5 h-5 w-5 accent-primary"
              checked={confirmed[c.key]}
              onChange={e => setConfirmed(prev => ({ ...prev, [c.key]: e.target.checked }))} />
            <span>{c.label}</span>
          </label>
        ))}
      </section>

      <section className="card p-4 space-y-3" aria-labelledby="mine-h">
        <h2 id="mine-h" className="text-sm font-semibold">2. Your blocks</h2>
        {claims === null ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : claims.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            You haven't claimed a block. Pick one from a survey area below. A claim holds it for you for 48 hours.
          </p>
        ) : claims.map(c => (
          <div key={c.id} className="space-y-3 rounded-lg border border-border p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium">{c.description}</p>
                <p className="text-xs text-muted-foreground">{c.area_name} · {timeLeft(c.expires_at)}</p>
              </div>
            </div>
            <ProgressBar done={c.doors_done} total={c.doors_total} label="doors done" />
            <div className="flex gap-2">
              {c.walk_open && c.walk_id ? (
                <button type="button" onClick={() => navigate(`/survey/walk/${c.walk_id}`)}
                  className="btn-primary min-h-11 flex-1 text-sm inline-flex items-center justify-center gap-2">
                  <Play className="h-4 w-4" /> Continue walk
                </button>
              ) : (
                <button type="button" onClick={() => void startClaimed(c)} disabled={!allConfirmed || busy !== null}
                  className="btn-primary min-h-11 flex-1 text-sm inline-flex items-center justify-center gap-2">
                  {busy === c.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  Start walk
                </button>
              )}
              <button type="button" onClick={() => void release(c)} disabled={busy !== null}
                className="btn-secondary min-h-11 px-3 text-sm inline-flex items-center gap-1">
                <Undo2 className="h-4 w-4" /> Give back
              </button>
            </div>
            {!allConfirmed && !c.walk_open && (
              <p className="text-xs text-muted-foreground" role="status">Tick the three confirmations above to start.</p>
            )}
          </div>
        ))}
      </section>

      {otherWalks.length > 0 && (
        <section className="card p-4 space-y-2">
          <h2 className="text-sm font-semibold">Walks in progress</h2>
          {otherWalks.map(w => (
            <button key={w.id} type="button" onClick={() => navigate(`/survey/walk/${w.id}`)}
              className="flex min-h-11 w-full items-center justify-between rounded-lg border border-border px-3 py-3 text-left text-sm hover:bg-muted">
              <span>{w.street}</span>
              <span className="text-xs text-muted-foreground">{w.recorded.length} of {w.addresses.length}</span>
            </button>
          ))}
        </section>
      )}

      <section className="card p-4 space-y-3" aria-labelledby="areas-h">
        <h2 id="areas-h" className="text-sm font-semibold">3. Survey areas</h2>
        {areas === null ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : areas.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No survey areas are open yet.{' '}
            {isOwner
              ? <Link to="/superadmin/surveyors" className="text-primary underline">Open one from the Surveyors page.</Link>
              : 'The owner opens them. Check back soon.'}
          </p>
        ) : areas.map(a => (
          <Link key={a.id} to={`/survey/areas/${a.id}`}
            className="block space-y-2 rounded-lg border border-border p-3 hover:bg-muted">
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{a.name}</span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </span>
            <ProgressBar done={a.blocks_done} total={a.blocks_total} label="blocks done" />
            {a.blocks_in_progress > 0 && (
              <span className="block text-xs text-warning">{a.blocks_in_progress} in progress</span>
            )}
          </Link>
        ))}
      </section>

      {isOwner && (
        <section className="card p-4 space-y-3" aria-labelledby="scout-h">
          <button type="button" onClick={() => setScouting(v => !v)} aria-expanded={scouting}
            className="flex min-h-11 w-full items-center justify-between text-left">
            <span>
              <span id="scout-h" className="block text-sm font-semibold">Scout outside an area</span>
              <span className="block text-xs text-muted-foreground">Owner only. A block inside an open area is claimed there instead.</span>
            </span>
            <ChevronDown className={`h-4 w-4 shrink-0 transition-transform motion-reduce:transition-none ${scouting ? 'rotate-180' : ''}`} />
          </button>
          {scouting && (<>
            <button type="button" onClick={useLocation} disabled={!allConfirmed || busy !== null}
              className="btn-primary min-h-11 w-full text-sm inline-flex items-center justify-center gap-2">
              {busy === 'locate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <LocateFixed className="h-4 w-4" />}
              Use my location
            </button>
            <div className="flex gap-2">
              <input type="text" value={typed} onChange={e => setTyped(e.target.value)} maxLength={200}
                disabled={!allConfirmed} placeholder="Or type an address, e.g. 433 W 32 St"
                aria-label="Address near the block"
                className="min-h-11 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 py-2.5 text-sm"
                onKeyDown={e => { if (e.key === 'Enter' && typed.trim().length >= 3 && busy === null) void locateTyped(); }}
                enterKeyHint="search" />
              <button type="button" onClick={() => void locateTyped()}
                disabled={!allConfirmed || typed.trim().length < 3 || busy !== null}
                className="btn-secondary inline-flex min-h-11 min-w-11 items-center justify-center text-sm" aria-label="Find blocks near this address">
                <Search className="h-4 w-4" />
              </button>
            </div>
            {!allConfirmed && <p className="text-xs text-muted-foreground">Tick the three confirmations above first.</p>}
            {blocks && (blocks.length === 0 ? (
              <p className="text-sm text-muted-foreground">The city lists no addresses within 150 m of this point.</p>
            ) : blocks.map(b => (
              <button key={b.block_key} type="button" onClick={() => void scout(b)}
                disabled={busy !== null}
                className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-border px-3 py-3 text-left hover:bg-muted">
                <span className="flex items-center gap-2 text-sm">
                  <MapPin className="h-4 w-4 shrink-0 text-muted-foreground" />
                  {b.description}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {busy === b.block_key ? <Loader2 className="h-4 w-4 animate-spin" /> : `${b.addresses.length} doors`}
                </span>
              </button>
            )))}
          </>)}
        </section>
      )}

      {isOwner && recent.length > 0 && (
        <section className="card p-4 space-y-2" aria-labelledby="recent-h">
          <h2 id="recent-h" className="text-sm font-semibold">Recent observations</h2>
          <ul className="divide-y divide-border text-sm">
            {recent.map(o => (
              <li key={o.id} className="py-2">
                <span className="font-medium">{o.address}</span>
                <span className="block text-xs text-muted-foreground">
                  {o.not_a_delivery_point ? 'Not a delivery point' : buildingTypeLabel(o.building_type)}
                  {' · '}{SOURCE_LABEL[o.source] ?? o.source} · {formatDate(o.observed_on)}
                  {o.mine ? '' : ' · contributor'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
