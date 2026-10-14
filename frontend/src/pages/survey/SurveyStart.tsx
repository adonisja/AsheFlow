/**
 * The survey register: start a walk (ADR-504).
 *
 * Phone first: this is used standing on a sidewalk. The order of the page is
 * the order of the rules:
 *   1. three confirmations (D2), which the server also enforces;
 *   2. find the city's blocks around you (D3): your location, or a typed address;
 *   3. pick one block and start. The server fetches that block's list itself.
 *
 * The owner also sees the most recent observations at the bottom.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LocateFixed, Loader2, MapPin, Search } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { errorText } from '../../utils/errorText';
import { useAuth } from '../../contexts/AuthContext';
import { buildingTypeLabel } from '../../utils/addressProfile';
import type { SurveyBlock, SurveyObservation, SurveyStartWalk, SurveyWalk } from '../../api/types';

const CONFIRMATIONS = [
  { key: 'attest_off_shift', label: "I'm off-shift. I'm not on any route or block for any carrier." },
  { key: 'attest_unbranded', label: 'No branded van, uniform, work phone or delivery app.' },
  { key: 'attest_as_self', label: "I'm asking as myself, not as a delivery driver." },
] as const;

type ConfirmKey = typeof CONFIRMATIONS[number]['key'];

export default function SurveyStart() {
  const navigate = useNavigate();
  const { groups } = useAuth();
  const isOwner = groups.includes('super_admin');

  const [confirmed, setConfirmed] = useState<Record<ConfirmKey, boolean>>({
    attest_off_shift: false, attest_unbranded: false, attest_as_self: false,
  });
  const allConfirmed = Object.values(confirmed).every(Boolean);

  const [point, setPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [typed, setTyped] = useState('');
  const [blocks, setBlocks] = useState<SurveyBlock[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openWalks, setOpenWalks] = useState<SurveyWalk[]>([]);
  const [recent, setRecent] = useState<SurveyObservation[]>([]);

  useEffect(() => {
    axiosClient.get<SurveyWalk[]>('/survey/walks', { params: { limit: 10 } })
      .then(r => setOpenWalks(r.data.filter(w => !w.closed_at)))
      .catch(() => { /* the start flow still works without the list */ });
    if (isOwner) {
      axiosClient.get<SurveyObservation[]>('/survey/observations', { params: { limit: 20 } })
        .then(r => setRecent(r.data)).catch(() => {});
    }
  }, [isOwner]);

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

  const start = async (block: SurveyBlock) => {
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

  return (
    <main className="mx-auto max-w-xl px-4 py-6 space-y-5">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Survey register</p>
        <h1 className="text-2xl font-bold">Walk a block</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Doors come from the city's own address list. Record only what you can see,
          or what building staff tell you when you ask as yourself.
        </p>
      </header>

      <ErrorBanner message={error} />

      {openWalks.length > 0 && (
        <section className="card p-4 space-y-2">
          <h2 className="text-sm font-semibold">Walks in progress</h2>
          {openWalks.map(w => (
            <button key={w.id} type="button" onClick={() => navigate(`/survey/walk/${w.id}`)}
              className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-3 text-left text-sm hover:bg-muted">
              <span>{w.street}</span>
              <span className="text-xs text-muted-foreground">{w.recorded.length} of {w.addresses.length}</span>
            </button>
          ))}
        </section>
      )}

      <section className="card p-4 space-y-3" aria-labelledby="confirm-h">
        <h2 id="confirm-h" className="text-sm font-semibold">1. Before you start</h2>
        {CONFIRMATIONS.map(c => (
          <label key={c.key} className="flex items-start gap-3 rounded-lg border border-border p-3 text-sm">
            <input type="checkbox" className="mt-0.5 h-5 w-5 accent-primary"
              checked={confirmed[c.key]}
              onChange={e => setConfirmed(prev => ({ ...prev, [c.key]: e.target.checked }))} />
            <span>{c.label}</span>
          </label>
        ))}
      </section>

      <section className={`card p-4 space-y-3 ${allConfirmed ? '' : 'opacity-50'}`} aria-labelledby="find-h">
        <h2 id="find-h" className="text-sm font-semibold">2. Find the block you're on</h2>
        <button type="button" onClick={useLocation} disabled={!allConfirmed || busy !== null}
          className="btn-primary w-full py-3 text-sm inline-flex items-center justify-center gap-2">
          {busy === 'locate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <LocateFixed className="h-4 w-4" />}
          Use my location
        </button>
        <div className="flex gap-2">
          <input type="text" value={typed} onChange={e => setTyped(e.target.value)} maxLength={200}
            disabled={!allConfirmed} placeholder="Or type an address, e.g. 433 W 32 St"
            aria-label="Address near the block"
            className="min-w-0 flex-1 rounded-lg border border-input bg-background px-3 py-2.5 text-sm" />
          <button type="button" onClick={() => void locateTyped()}
            disabled={!allConfirmed || typed.trim().length < 3 || busy !== null}
            className="btn-secondary px-3 text-sm" aria-label="Find blocks near this address">
            <Search className="h-4 w-4" />
          </button>
        </div>
      </section>

      {blocks && (
        <section className="card p-4 space-y-2" aria-labelledby="pick-h">
          <h2 id="pick-h" className="text-sm font-semibold">3. Pick a block</h2>
          {blocks.length === 0 && (
            <p className="text-sm text-muted-foreground">The city lists no addresses within 150 m of this point.</p>
          )}
          {blocks.map(b => (
            <button key={b.block_key} type="button" onClick={() => void start(b)}
              disabled={busy !== null}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-border px-3 py-3 text-left hover:bg-muted">
              <span className="flex items-center gap-2 text-sm">
                <MapPin className="h-4 w-4 shrink-0 text-muted-foreground" />
                {b.description}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {busy === b.block_key ? <Loader2 className="h-4 w-4 animate-spin" /> : `${b.addresses.length} doors`}
              </span>
            </button>
          ))}
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
                  {' · '}{o.source.replace('_', ' ')} · {o.observed_on}
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
