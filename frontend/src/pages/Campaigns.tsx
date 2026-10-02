/**
 * Campaigns — the field-facing surface (ADR-485 D6).
 *
 * What a crew member owes right now, and the form to clear it. Management's
 * design and results surfaces (D15) are separate pages; this is the half that
 * has to work on a phone at the end of a shift.
 *
 * TWO DESIGN RULES FROM THE ADR, both load-bearing:
 *
 *  1. **Lead with the date and the truck, never the campaign name alone.** A
 *     daily campaign routinely has two runs open at once (D12) — yesterday's,
 *     closing at this morning's shift start, and today's. Two entries reading
 *     "Driver Survey" with no date is the one confusion this design can still
 *     produce.
 *  2. **A closed run is a sentence, not a 404.** A walker who taps a
 *     notification at 19:00 for a run that closed at 18:00 gets told that, not
 *     a blank screen.
 */
import { useCallback, useEffect, useState } from 'react';
import { ClipboardList, Clock, Truck, CheckCircle2, AlertCircle } from 'lucide-react';

import axiosClient from '../api/axiosClient';
import SelectMenu from '../components/ui/SelectMenu';
import { errorText } from '../utils/errorText';

interface Question {
  id: string;
  position: number;
  prompt: string;
  kind: 'bool' | 'scale' | 'text' | 'choice';
  required: boolean;
  scale_min?: number | null;
  scale_max?: number | null;
  choices?: string[] | null;
}

interface OpenRun {
  run_id: string;
  campaign_label: string;
  date: string;
  closes_at: string;
  subject_id: string;
  subject_name: string;
  truck_name?: string | null;
  answered: boolean;
  questions: Question[];
}

/** One answer, shaped by the question's kind. */
type Draft = Record<string, { bool?: boolean; int?: number; text?: string }>;

function closesIn(iso: string): { label: string; urgent: boolean } {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return { label: 'Closed', urgent: true };
  const hours = Math.floor(ms / 3_600_000);
  const mins = Math.floor((ms % 3_600_000) / 60_000);
  // Under two hours is where a reminder stops being information and starts
  // being a deadline — the same threshold ADR-130 used for the survey banner.
  if (hours < 2) return { label: `Closes in ${hours}h ${mins}m`, urgent: true };
  return { label: `Closes in ${hours}h`, urgent: false };
}

export default function Campaigns() {
  const [runs, setRuns] = useState<OpenRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<OpenRun | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<OpenRun[]>('/campaigns/my-open');
      setRuns(res.data);
      setError(null);
    } catch (err: unknown) {
      setError(errorText(err, 'Could not load your campaigns.'));
      setRuns([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const open = (run: OpenRun) => {
    setActive(run);
    setDraft({});
    setDone(null);
    setError(null);
  };

  const setAnswer = (qid: string, value: Draft[string]) =>
    setDraft(d => ({ ...d, [qid]: value }));

  const submit = async () => {
    if (!active) return;
    setSubmitting(true);
    setError(null);
    try {
      await axiosClient.post(`/campaigns/runs/${active.run_id}/respond`, {
        subject_id: active.subject_id,
        answers: active.questions
          .filter(q => draft[q.id] !== undefined)
          .map(q => ({
            question_id: q.id,
            bool_value: q.kind === 'bool' ? draft[q.id].bool : null,
            int_value: q.kind === 'scale' || q.kind === 'choice' ? draft[q.id].int : null,
            text_value: q.kind === 'text' ? draft[q.id].text : null,
          })),
      });
      setDone(`Thanks. Your answers about ${active.subject_name} are in.`);
      setActive(null);
      await load();
    } catch (err: unknown) {
      /* The server validates each answer against its own question and says
         which one is wrong. Surfacing that beats a generic failure on a form
         somebody just filled in. */
      setError(errorText(err, 'Could not submit your answers.'));
    } finally {
      setSubmitting(false);
    }
  };

  // ---- the list -----------------------------------------------------------

  if (active === null) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-semibold text-foreground">Campaigns</h1>
        </div>

        {done && (
          <div className="bg-success/5 text-success px-4 py-3 rounded-xl text-sm font-medium border border-success/20 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            {done}
          </div>
        )}

        {error && (
          <div className="bg-danger/5 text-danger px-4 py-3 rounded-xl text-sm font-medium border border-danger/20">
            {error}
          </div>
        )}

        {runs === null && (
          <div className="card text-center py-10 text-subtle text-sm">Loading…</div>
        )}

        {runs !== null && runs.length === 0 && (
          <div className="card text-center py-10">
            <p className="text-sm text-foreground">Nothing to answer right now.</p>
            <p className="text-xs text-muted-foreground mt-1">
              You will see a campaign here while one is open for a shift you worked.
            </p>
          </div>
        )}

        {runs?.map(run => {
          const closing = closesIn(run.closes_at);
          return (
            <button
              key={`${run.run_id}-${run.subject_id}`}
              type="button"
              onClick={() => open(run)}
              disabled={run.answered}
              className={`card w-full text-left transition-colors ${
                run.answered ? 'opacity-60 cursor-default' : 'hover:bg-accent/30'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">
                    {run.campaign_label}
                  </p>
                  {/* The DATE and the TRUCK, always — two open runs of the same
                      campaign are told apart by nothing else. */}
                  <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span>{run.date}</span>
                    {run.truck_name && (
                      <span className="flex items-center gap-1">
                        <Truck className="w-3 h-3" />
                        {run.truck_name}
                      </span>
                    )}
                    <span>·</span>
                    <span>About {run.subject_name}</span>
                  </p>
                </div>
                {run.answered ? (
                  <span className="text-xs text-success flex items-center gap-1 shrink-0">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Done
                  </span>
                ) : (
                  <span
                    className={`text-xs flex items-center gap-1 shrink-0 ${
                      closing.urgent ? 'text-warning' : 'text-muted-foreground'
                    }`}
                  >
                    <Clock className="w-3.5 h-3.5" />
                    {closing.label}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    );
  }

  // ---- the form -----------------------------------------------------------

  const closing = closesIn(active.closes_at);

  return (
    <div className="space-y-4">
      <button type="button" onClick={() => setActive(null)} className="btn-ghost text-sm">
        ← Back
      </button>

      <div className="card">
        <h1 className="text-lg font-semibold text-foreground">{active.campaign_label}</h1>
        <p className="text-xs text-muted-foreground mt-1 flex items-center gap-2 flex-wrap">
          <span>{active.date}</span>
          {active.truck_name && (
            <span className="flex items-center gap-1">
              <Truck className="w-3 h-3" />
              {active.truck_name}
            </span>
          )}
          <span>·</span>
          <span className="text-foreground font-medium">About {active.subject_name}</span>
        </p>
        <p className={`text-xs mt-2 flex items-center gap-1 ${
          closing.urgent ? 'text-warning' : 'text-muted-foreground'
        }`}>
          <Clock className="w-3.5 h-3.5" />
          {closing.label}
        </p>
      </div>

      {error && (
        <div className="bg-danger/5 text-danger px-4 py-3 rounded-xl text-sm font-medium border border-danger/20 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="card space-y-5">
        {active.questions.map(q => (
          <div key={q.id}>
            <label className="block text-sm font-medium text-foreground mb-2">
              {q.prompt}
              {!q.required && (
                <span className="text-xs text-muted-foreground font-normal"> (optional)</span>
              )}
            </label>

            {q.kind === 'bool' && (
              /* Two buttons, not a dropdown: a yes/no answered on a phone in a
                 van should be one tap, and the chosen state has to be visible
                 without opening anything. */
              <div className="flex gap-2">
                {[
                  { v: true, label: 'Yes' },
                  { v: false, label: 'No' },
                ].map(opt => (
                  <button
                    key={String(opt.v)}
                    type="button"
                    onClick={() => setAnswer(q.id, { bool: opt.v })}
                    className={`flex-1 px-4 py-2.5 rounded-xl border text-sm transition-colors ${
                      draft[q.id]?.bool === opt.v
                        ? 'border-primary bg-primary/5 text-foreground font-medium'
                        : 'border-border hover:bg-accent text-foreground'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}

            {q.kind === 'scale' && (
              <div className="flex flex-wrap gap-2">
                {Array.from(
                  { length: (q.scale_max ?? 5) - (q.scale_min ?? 1) + 1 },
                  (_, i) => (q.scale_min ?? 1) + i,
                ).map(n => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setAnswer(q.id, { int: n })}
                    className={`w-11 h-11 rounded-xl border text-sm transition-colors ${
                      draft[q.id]?.int === n
                        ? 'border-primary bg-primary/5 text-foreground font-medium'
                        : 'border-border hover:bg-accent text-foreground'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            )}

            {q.kind === 'choice' && (
              /* The house dropdown (ADR-484), not a native select. The option
                 INDEX is the value — renaming an option later must not rewrite
                 what a past answer meant (ADR-485 D2). */
              <SelectMenu
                value={draft[q.id]?.int !== undefined ? String(draft[q.id].int) : ''}
                options={(q.choices ?? []).map((c, i) => ({ value: String(i), label: c }))}
                placeholder="Choose one"
                ariaLabel={q.prompt}
                onChange={v => setAnswer(q.id, { int: Number(v) })}
              />
            )}

            {q.kind === 'text' && (
              <textarea
                value={draft[q.id]?.text ?? ''}
                onChange={e => setAnswer(q.id, { text: e.target.value })}
                maxLength={2000}
                rows={3}
                aria-label={q.prompt}
                className="input-field w-full resize-y"
                placeholder="Optional"
              />
            )}
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => void submit()}
        disabled={submitting}
        className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {submitting ? 'Sending…' : 'Submit'}
      </button>

      <p className="text-xs text-muted-foreground text-center">
        Your answers go to management, never to {active.subject_name}.
      </p>
    </div>
  );
}
