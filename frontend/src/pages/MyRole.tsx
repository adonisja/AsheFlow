import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BookOpen, RefreshCw } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import GuideBody from '../components/roleGuide/GuideBody';
import type { RoleGuide } from '../api/types';

/** `/my-role` — what your role does here (ADR-494 D4).
 *
 *  This page is the destination for two notifications, and it exists because
 *  they needed one. `graduation` and `operating_mode_change` were GATEs under
 *  ADR-487 D8 — modals whose only control was "OK". ADR-494 D1 dropped both to
 *  PROMPTs on the reasoning that someone proceeding UNINFORMED needs
 *  information rather than a wall; that only holds if the information exists
 *  somewhere, and this is where.
 *
 *  Takes no role parameter: the server answers for the caller's own role and
 *  the company's current mode. A walker cannot read the admin guide here, which
 *  is deliberate — "what can admins do" is a different question.
 */
export default function MyRole() {
  const [guide, setGuide] = useState<RoleGuide | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<RoleGuide>('/my-role');
      setGuide(res.data);
    } catch (err: unknown) {
      // 404 is a real, distinct state — a role whose guide was never seeded —
      // and it gets the server's message, which tells the reader to ask an
      // admin. Anything else is ours and says so without leaking a stack.
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(
        status === 404 && detail
          ? detail
          : 'We could not load your role guide. Try again in a moment.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <div className="animate-pulse space-y-4" aria-busy="true" aria-live="polite">
          <span className="sr-only">Loading your role guide</span>
          <div className="h-7 w-2/3 rounded bg-muted" />
          <div className="h-4 w-1/3 rounded bg-muted" />
          <div className="space-y-2.5 pt-4">
            {[...Array(7)].map((_, i) => (
              <div key={i} className="h-3.5 rounded bg-muted" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !guide) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <div className="rounded-xl border border-warning/30 bg-warning/10 p-5">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
            <div className="min-w-0">
              <h1 className="font-semibold text-warning">
                No guide to show
              </h1>
              <p className="mt-1 text-sm text-warning">{error}</p>
              <button
                type="button"
                onClick={() => void load()}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-warning/40 bg-card px-3 py-1.5 text-sm font-medium text-warning hover:bg-warning/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-warning"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Try again
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <header className="border-b border-border pb-5">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
          Your role
        </div>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-foreground">
          {guide.title}
        </h1>
        {/* The mode is stated plainly rather than inferred from the text. A
            reader whose company just switched needs to see WHICH mode they are
            reading about — that is the whole point of arriving here from an
            operating_mode_change notification. */}
        <p className="mt-1.5 text-sm text-muted-foreground">
          {guide.operating_mode === 'full'
            ? 'This company runs with an Amazon package feed.'
            : 'This company runs without an Amazon package feed.'}
        </p>
      </header>

      <article className="pt-2">
        <GuideBody body={guide.body} />
      </article>

      {/* Shown to everyone, not just admins. A field user who finds something
          here that does not match their lot should know the text is their
          company's to fix, rather than assuming the app is wrong about them. */}
      <footer className="mt-8 border-t border-border pt-4">
        <p className="text-xs text-muted-foreground">
          {guide.is_customized
            ? 'Your company wrote this guide.'
            : 'This is the standard guide. Your company can edit it in company settings.'}
        </p>
      </footer>
    </div>
  );
}
