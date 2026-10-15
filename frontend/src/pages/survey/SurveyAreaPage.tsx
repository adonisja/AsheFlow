/**
 * One survey area's blocks, and claiming one (ADR-513 D3, D6).
 *
 * Every block says which kind of "not done" it is: open, in progress (with how
 * far), done (with when it re-opens), held by you, or held by someone else. Who
 * holds a block is never shown.
 *
 * "Nearest first" uses the device's location when it is allowed. When it is
 * not, the list stays in the city's street order and nothing else changes.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ChevronLeft, Hand, Loader2, LocateFixed } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { errorText } from '../../utils/errorText';
import type { SurveyArea, SurveyAreaBlock } from '../../api/types';
import { BlockStateBadge, ProgressBar, distanceLabel } from './surveyUi';

type Filter = 'todo' | 'done' | 'all';
const FILTERS: { value: Filter; label: string }[] = [
  { value: 'todo', label: 'To do' }, { value: 'done', label: 'Done' }, { value: 'all', label: 'All' },
];

export default function SurveyAreaPage() {
  const { areaId } = useParams<{ areaId: string }>();
  const navigate = useNavigate();
  const [area, setArea] = useState<SurveyArea | null>(null);
  const [blocks, setBlocks] = useState<SurveyAreaBlock[] | null>(null);
  const [here, setHere] = useState<{ lat: number; lng: number } | null>(null);
  const [filter, setFilter] = useState<Filter>('todo');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (p: { lat: number; lng: number } | null) => {
    try {
      const [a, b] = await Promise.all([
        axiosClient.get<SurveyArea[]>('/survey/areas'),
        axiosClient.get<SurveyAreaBlock[]>(`/survey/areas/${areaId}/blocks`, { params: p ?? {} }),
      ]);
      setArea(a.data.find(x => x.id === areaId) ?? null);
      setBlocks(b.data);
    } catch (e) {
      setError(errorText(e, "Couldn't load this area."));
    }
  }, [areaId]);
  useEffect(() => { void load(null); }, [load]);

  const nearest = () => {
    if (!('geolocation' in navigator)) {
      setError("This browser has no location. The list stays in street order.");
      return;
    }
    setBusy('locate');
    navigator.geolocation.getCurrentPosition(
      pos => {
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setHere(p);
        void load(p).finally(() => setBusy(null));
      },
      () => { setBusy(null); setError('Location was refused or unavailable. The list stays in street order.'); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  };

  const claim = async (b: SurveyAreaBlock) => {
    setBusy(b.id);
    setError(null);
    try {
      await axiosClient.post(`/survey/areas/${areaId}/blocks/${b.id}/claim`);
      navigate('/survey');
    } catch (e) {
      setError(errorText(e, "Couldn't claim this block."));
      setBusy(null);
      void load(here);
    }
  };

  const shown = useMemo(() => (blocks ?? []).filter(b =>
    filter === 'all' ? true : filter === 'done' ? b.state === 'done' : b.state !== 'done'), [blocks, filter]);

  return (
    <main className="mx-auto max-w-xl px-4 py-6 space-y-4">
      <Link to="/survey" className="btn-ghost -ml-3 inline-flex min-h-11 items-center gap-1 px-3 text-sm">
        <ChevronLeft className="h-4 w-4" /> Survey
      </Link>
      <header className="space-y-2">
        <h1 className="text-xl font-bold">{area?.name ?? 'Survey area'}</h1>
        {area && <p className="text-sm text-muted-foreground">{area.reason}</p>}
        {area && <ProgressBar done={area.blocks_done} total={area.blocks_total} label="blocks done" />}
      </header>
      <ErrorBanner message={error} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="radiogroup" aria-label="Show" className="inline-flex rounded-full border border-border p-0.5">
          {FILTERS.map(f => (
            <button key={f.value} type="button" role="radio" aria-checked={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`min-h-11 rounded-full px-4 text-sm ${filter === f.value ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground'}`}>
              {f.label}
            </button>
          ))}
        </div>
        <button type="button" onClick={nearest} disabled={busy !== null}
          className="btn-ghost inline-flex min-h-11 items-center gap-1 px-3 text-sm">
          {busy === 'locate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <LocateFixed className="h-4 w-4" />}
          {here ? 'Nearest first' : 'Sort by nearest'}
        </button>
      </div>

      {blocks === null ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filter === 'done' ? 'No block in this area is done yet.' : 'Every block in this area is done.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map(b => {
            const claimable = b.state !== 'done' && b.claim === null;
            return (
              <li key={b.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-medium">{b.description}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <BlockStateBadge state={b.state} done={b.doors_done} total={b.doors_total} reopensOn={b.reopens_on} />
                    {distanceLabel(b.distance_m) && (
                      <span className="text-xs text-muted-foreground">{distanceLabel(b.distance_m)}</span>
                    )}
                  </div>
                </div>
                {b.claim === 'mine' ? (
                  <Link to="/survey" className="btn-secondary inline-flex min-h-11 items-center px-3 text-sm">Yours</Link>
                ) : b.claim === 'taken' ? (
                  <span className="text-xs text-muted-foreground">Someone's walking it</span>
                ) : claimable ? (
                  <button type="button" onClick={() => void claim(b)} disabled={busy !== null}
                    className="btn-primary inline-flex min-h-11 items-center gap-1 px-3 text-sm">
                    {busy === b.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Hand className="h-4 w-4" />}
                    Claim
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
