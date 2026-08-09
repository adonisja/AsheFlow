import React, { useEffect, useState } from 'react';
import { BookOpen, RefreshCw, Eye } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorBanner from '../components/ui/ErrorBanner';

interface CurriculumItem {
  id: string;
  day_number: number;
  topic_title: string;
  description: string | null;
  category: string | null;
  is_mandatory: boolean;
  record_type: string;
  /** Training track(s) this item belongs to (ADR-263). A shared item carries both. */
  roles: string[];
}

type TrackFilter = 'all' | 'walker' | 'driver';

const TRACK_LABEL: Record<TrackFilter, string> = {
  all: 'All tracks',
  walker: 'Walker',
  driver: 'Driver',
};

const PHASE_LABELS: Record<number, string> = {
  1: 'Phase 1 — Orientation & Setup',
  2: 'Phase 2 — Delivery Standards',
  3: 'Phase 3 — Delivery Types & Edge Cases',
  4: 'Phase 4 — Practical Shadowing (auto-generated)',
};

const CATEGORY_BADGE: Record<string, string> = {
  app_setup: 'badge-info',
  policy: 'badge-warning',
  delivery_standards: 'badge-success',
  delivery_types: 'badge-success',
  // `badge-danger`, not `badge-error` — the latter is not defined in index.css and
  // rendered unstyled.
  scorecard: 'badge-danger',
  // Token-backed badges rather than raw Tailwind palette utilities. `bg-amber-500`
  // bypasses the token layer exactly as a hex literal does: it does not follow a
  // palette change and the contrast gate cannot see it.
  vehicle_safety: 'badge-gold',
  crew_ops: 'badge-teal',
  observation: 'badge-slate',
};

const CATEGORY_LABEL: Record<string, string> = {
  app_setup: 'App Setup',
  policy: 'Policy',
  delivery_standards: 'Delivery Standards',
  delivery_types: 'Delivery Types',
  scorecard: 'Scorecard',
  vehicle_safety: 'Vehicle & Safety',
  crew_ops: 'Load & Crew Ops',
  observation: 'Observation',
};

export default function TrainingCurriculum() {
  const [items, setItems] = useState<CurriculumItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedItem, setExpandedItem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [track, setTrack] = useState<TrackFilter>('all');

  const load = () => {
    setLoading(true);
    setError(null);
    axiosClient.get('/training/curriculum')
      .then(r => setItems(r.data))
      .catch(() => setError('Failed to load training curriculum.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  // Track filter (ADR-263). Applied before every downstream derivation — the
  // Phase 4 preview especially, since an unfiltered preview shows a mixed
  // walker+driver checklist that matches no real trainee's Phase 4.
  const visible = track === 'all'
    ? items
    : items.filter(i => i.roles?.includes(track));

  const byPhase = [1, 2, 3].reduce<Record<number, CurriculumItem[]>>((acc, phase) => {
    acc[phase] = visible.filter(i => i.day_number === phase);
    return acc;
  }, {});

  // Phase 4 preview — mandatory items from phases 1–3, for the selected track.
  const phase4Preview = visible.filter(i => i.is_mandatory && i.day_number <= 3);

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Admin" title="Training Curriculum" />
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} className="h-32" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Admin"
        title="Training Curriculum"
        description="4-phase training curriculum for the walker and driver tracks. Phase 4 observation checklist is auto-generated from all mandatory Phase 1–3 topics at dispatch time."
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg overflow-hidden border border-white/10" role="group" aria-label="Filter by training track">
              {(['all', 'walker', 'driver'] as TrackFilter[]).map(t => (
                <button
                  key={t}
                  onClick={() => setTrack(t)}
                  aria-pressed={track === t}
                  className={`px-3 py-1.5 text-sm transition-colors ${
                    track === t
                      ? 'bg-white/15 text-white'
                      : 'text-muted-foreground hover:text-white hover:bg-white/5'
                  }`}
                >
                  {TRACK_LABEL[t]}
                </button>
              ))}
            </div>
            <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
          </div>
        }
      />

      <ErrorBanner message={error} />

      {/* Phases 1–3 */}
      {[1, 2, 3].map(phase => {
        const phaseItems = byPhase[phase] ?? [];
        const mandatory = phaseItems.filter(i => i.is_mandatory).length;
        const optional = phaseItems.filter(i => !i.is_mandatory).length;

        return (
          <MotionCard key={phase} delay={phase * 0.05} hoverable={false}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="font-semibold">{PHASE_LABELS[phase]}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {mandatory} mandatory{optional > 0 ? `, ${optional} optional` : ''} topics
                </p>
              </div>
              <span className="badge bg-accent text-foreground">{phaseItems.length} topics</span>
            </div>

            <div className="space-y-2">
              {phaseItems.map(item => (
                <div key={item.id} className="border border-border rounded-lg overflow-hidden">
                  <div
                    className="flex items-center gap-3 p-3 cursor-pointer hover:bg-accent/50 transition-colors"
                    onClick={() => setExpandedItem(expandedItem === item.id ? null : item.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium leading-snug">{item.topic_title}</p>
                        {!item.is_mandatory && (
                          <span className="text-[10px] text-muted-foreground border border-border rounded px-1.5 py-0.5">
                            Optional
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.category && (
                        <span className={`badge text-[10px] ${CATEGORY_BADGE[item.category] ?? 'bg-accent'}`}>
                          {CATEGORY_LABEL[item.category] ?? item.category}
                        </span>
                      )}
                      <Eye className="w-3.5 h-3.5 text-muted-foreground" />
                    </div>
                  </div>
                  {expandedItem === item.id && item.description && (
                    <div className="px-3 pb-3 text-xs text-muted-foreground leading-relaxed border-t border-border pt-2 bg-accent/30">
                      {item.description}
                    </div>
                  )}
                </div>
              ))}

              {phaseItems.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No topics seeded for this phase. Run the seed script.
                </p>
              )}
            </div>
          </MotionCard>
        );
      })}

      {/* Phase 4 preview */}
      <MotionCard delay={0.2} hoverable={false}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="font-semibold">{PHASE_LABELS[4]}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Auto-generated from {phase4Preview.length} mandatory Phase 1–3 topics as observation items.
              Not stored as static curriculum rows.
            </p>
          </div>
          <span className="badge bg-accent text-foreground">{phase4Preview.length} items</span>
        </div>

        <div className="rounded-lg border border-border divide-y divide-border">
          {phase4Preview.slice(0, 5).map(item => (
            <div key={item.id} className="px-3 py-2 text-sm flex items-center gap-2">
              <BookOpen className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <span className="text-muted-foreground">{item.topic_title}</span>
            </div>
          ))}
          {phase4Preview.length > 5 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              + {phase4Preview.length - 5} more topics…
            </div>
          )}
        </div>
      </MotionCard>
    </div>
  );
}
