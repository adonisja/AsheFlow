import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useCallback } from 'react';
import { ClipboardList, Users, CheckCircle, XCircle, RefreshCw, ChevronLeft, ChevronRight, X, type LucideIcon } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { today } from '../utils/date';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub, color = 'text-foreground' }: {
  label: string; value: string | number; sub?: string; color?: string;
}) {
  return (
    <div className="card-elevated">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-subtle mt-0.5">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title, subtitle, iconColor }: {
  icon: LucideIcon; title: string; subtitle?: string; iconColor: string;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
      <Icon className={`w-5 h-5 ${iconColor}`} />
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {subtitle && <span className="ml-auto text-xs text-subtle">{subtitle}</span>}
    </div>
  );
}

function PctBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2.5 rounded-full bg-accent overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-300 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-bold text-foreground w-10 text-right">{pct}%</span>
    </div>
  );
}

function YesNo({ value }: { value: boolean }) {
  return value
    ? <CheckCircle className="w-4 h-4 text-success inline-block" />
    : <XCircle    className="w-4 h-4 text-danger  inline-block" />;
}

// ---------------------------------------------------------------------------
// Response detail modal
// ---------------------------------------------------------------------------

function ResponseModal({ response, onClose }: {
  response: SurveyResponseItem;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const rows: { label: string; value: boolean }[] = [
    { label: 'Routes organized at shift start', value: response.routes_organized },
    { label: 'Anchor point in good location',   value: response.anchor_point_location },
    { label: 'Rabbit & supplies ready',          value: response.supplies_ready },
    { label: 'Driver support at anchor point',   value: response.driver_support },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="card w-full max-w-md relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-subtle hover:text-foreground transition-colors"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        <h3 className="text-base font-semibold text-foreground mb-1">{response.respondent_name}</h3>
        <p className="text-xs text-muted-foreground mb-4 capitalize">
          {response.respondent_role}
          {response.respondent_email ? ` · ${response.respondent_email}` : ''}
        </p>

        <div className="space-y-0.5 text-sm mb-4">
          <p><span className="text-muted-foreground">Truck: </span><span className="font-medium text-foreground">{response.truck_name ?? '—'}</span></p>
          <p><span className="text-muted-foreground">Driver: </span><span className="font-medium text-foreground">{response.driver_name ?? '—'}</span></p>
          <p><span className="text-muted-foreground">Submitted: </span><span className="text-foreground">
            {new Date(response.submitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span></p>
        </div>

        <div className="space-y-3 mb-4">
          {rows.map(({ label, value }) => (
            <div key={label} className="flex items-start justify-between gap-3">
              <span className="text-sm text-foreground flex-1">{label}</span>
              <span className={`text-sm font-semibold shrink-0 ${value ? 'text-success' : 'text-danger'}`}>
                {value ? 'Yes' : 'No'}
              </span>
            </div>
          ))}
        </div>

        {response.notes ? (
          <div className="bg-accent rounded-lg p-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Notes</p>
            <p className="text-sm text-foreground italic">{response.notes}</p>
          </div>
        ) : (
          <p className="text-xs text-subtle italic">No additional notes.</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SurveyListItem {
  id: string;
  date: string;
  created_at: string;
  expected_count: number;
  response_count: number;
}

interface SurveyStats {
  expected_count: number;
  response_count: number;
  routes_organized_pct: number;
  anchor_location_pct: number;
  supplies_ready_pct: number;
  driver_support_pct: number;
}

interface SurveyResponseItem {
  id: string;
  respondent_name: string;
  respondent_email: string | null;
  respondent_role: string;
  truck_name: string | null;
  driver_name: string | null;
  routes_organized: boolean;
  anchor_point_location: boolean;
  supplies_ready: boolean;
  driver_support: boolean;
  notes: string | null;
  submitted_at: string;
}

interface SurveyDetail {
  id: string;
  date: string;
  created_at: string;
  stats: SurveyStats;
  responses: SurveyResponseItem[];
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

export default function DriverSurveys() {
  const { groups } = useAuth();
  const isManagement = groups?.some(g => ['management', 'admin'].includes(g));

  const [selectedDate, setSelectedDate] = useState<string>(today());
  const [surveys, setSurveys]           = useState<SurveyListItem[]>([]);
  const [total, setTotal]               = useState(0);
  const [page, setPage]                 = useState(0);
  const [detail, setDetail]             = useState<SurveyDetail | null>(null);
  const [activating, setActivating]     = useState(false);
  const [loading, setLoading]           = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [modalResponse, setModalResponse] = useState<SurveyResponseItem | null>(null);

  const loadSurveys = useCallback(async (targetPage = page) => {
    setLoading(true);
    setError(null);
    try {
      const skip = targetPage * PAGE_SIZE;
      const { data, headers } = await axiosClient.get<SurveyListItem[]>(
        `/driver-surveys/?limit=${PAGE_SIZE}&skip=${skip}`
      );
      setSurveys(data);
      const ct = parseInt(headers['x-total-count'] ?? '0', 10);
      setTotal(isNaN(ct) ? data.length + skip : ct);
    } catch {
      setError('Failed to load surveys.');
    } finally {
      setLoading(false);
    }
  }, [page]);

  const loadDetail = useCallback(async (date: string) => {
    setDetailLoading(true);
    try {
      const { data } = await axiosClient.get<SurveyDetail>(`/driver-surveys/${date}`);
      setDetail(data);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSurveys(0);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-load detail for the most recent survey on mount
  useEffect(() => {
    if (surveys.length > 0 && !detail) {
      const latest = surveys[0];
      setSelectedDate(latest.date);
      loadDetail(latest.date);
    }
  }, [surveys]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleActivate = async () => {
    if (!selectedDate) return;
    setActivating(true);
    setError(null);
    try {
      await axiosClient.post('/driver-surveys/', { date: selectedDate });
      await loadSurveys(0);
      await loadDetail(selectedDate);
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to activate survey.'));
    } finally {
      setActivating(false);
    }
  };

  const handleSelectDate = (date: string) => {
    setSelectedDate(date);
    loadDetail(date);
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    loadSurveys(newPage);
  };

  const surveyForSelectedDate = surveys.find(s => s.date === selectedDate);
  const alreadyActivated = !!surveyForSelectedDate;

  const todayStr = today();
  const isTodaySurvey = detail?.date === todayStr;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  if (!isManagement) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">Access restricted to management and admin.</p>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ClipboardList className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-xl font-bold text-foreground">Driver Surveys</h1>
          <p className="text-sm text-muted-foreground">End-of-shift feedback from trainers and walkers</p>
        </div>
        <button
          onClick={() => { loadSurveys(page); if (selectedDate) loadDetail(selectedDate); }}
          className="ml-auto btn-ghost p-2 rounded"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 text-subtle ${loading || detailLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-danger/10 border border-danger/30 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {/* Activate panel */}
      <div className="card">
        <SectionHeader icon={ClipboardList} title="Activate Survey" iconColor="text-primary"
          subtitle="Requires shift to be ≥ 3 hours underway" />
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Date</label>
            <input
              type="date"
              value={selectedDate}
              onChange={e => setSelectedDate(e.target.value)}
              className="input text-sm"
            />
          </div>
          <button
            onClick={handleActivate}
            disabled={activating || alreadyActivated || !selectedDate}
            className="btn-primary text-sm"
          >
            {activating ? 'Activating…' : alreadyActivated ? 'Already activated' : 'Activate Survey'}
          </button>
        </div>
      </div>

      {/* Survey list */}
      {surveys.length > 0 && (
        <div className="card">
          <SectionHeader icon={Users} title="Survey History" iconColor="text-info"
            subtitle={total > PAGE_SIZE ? `${total} total` : undefined} />
          <div className="space-y-1">
            {surveys.map(s => {
              const rate = s.expected_count > 0
                ? Math.round(s.response_count / s.expected_count * 100)
                : 0;
              const isSelected = s.date === selectedDate;
              return (
                <button
                  key={s.id}
                  onClick={() => handleSelectDate(s.date)}
                  className={`w-full text-left flex items-center justify-between px-3 py-2 rounded-lg transition-colors ${
                    isSelected ? 'bg-primary/10 border border-primary/30' : 'hover:bg-accent'
                  }`}
                >
                  <span className="text-sm font-medium text-foreground">{s.date}</span>
                  <span className="text-xs text-muted-foreground">
                    {s.response_count}/{s.expected_count} responded
                    <span className={`ml-2 font-semibold ${rate >= 75 ? 'text-success' : rate >= 40 ? 'text-warning' : 'text-danger'}`}>
                      {rate}%
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-3 mt-3 border-t border-border">
              <span className="text-xs text-muted-foreground">
                Page {page + 1} of {totalPages}
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => handlePageChange(page - 1)}
                  disabled={page === 0 || loading}
                  className="btn-ghost p-1.5 rounded disabled:opacity-40"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handlePageChange(page + 1)}
                  disabled={page >= totalPages - 1 || loading}
                  className="btn-ghost p-1.5 rounded disabled:opacity-40"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Detail panel */}
      {detailLoading && (
        <div className="card flex items-center justify-center py-12">
          <RefreshCw className="w-5 h-5 animate-spin text-subtle" />
        </div>
      )}

      {detail && !detailLoading && (
        <>
          {/* Live poll indicator for today's survey */}
          {isTodaySurvey && (
            <div className="rounded-lg bg-info/10 border border-info/30 px-4 py-2 text-xs text-info">
              Use the ↻ button to refresh responses · Survey closes at midnight tonight
            </div>
          )}

          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Expected"
              value={detail.stats.expected_count}
              sub="trainers + walkers"
            />
            <StatCard
              label="Responded"
              value={detail.stats.response_count}
              color={detail.stats.response_count >= detail.stats.expected_count ? 'text-success' : 'text-warning'}
            />
            <StatCard
              label="Response Rate"
              value={
                detail.stats.expected_count > 0
                  ? `${Math.round(detail.stats.response_count / detail.stats.expected_count * 100)}%`
                  : '—'
              }
            />
            <StatCard label="Survey Date" value={detail.date} />
          </div>

          {/* Per-question breakdown */}
          <div className="card">
            <SectionHeader icon={ClipboardList} title="Question Breakdown"
              subtitle={`${detail.stats.response_count} responses`} iconColor="text-primary" />
            <div className="space-y-4">
              {[
                { label: 'Routes organized at shift start', pct: detail.stats.routes_organized_pct },
                { label: 'Anchor point in good location',  pct: detail.stats.anchor_location_pct },
                { label: 'Rabbit & supplies ready',        pct: detail.stats.supplies_ready_pct },
                { label: 'Driver support at anchor point', pct: detail.stats.driver_support_pct },
              ].map(({ label, pct }) => (
                <div key={label}>
                  <div className="flex justify-between text-xs text-muted-foreground mb-1">
                    <span>{label}</span>
                  </div>
                  <PctBar
                    pct={pct}
                    color={pct >= 75 ? 'bg-success' : pct >= 50 ? 'bg-warning' : 'bg-danger'}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Individual responses */}
          {detail.responses.length > 0 && (
            <div className="card">
              <SectionHeader icon={Users} title="Individual Responses"
                subtitle={`${detail.responses.length} submitted · click a row to expand`} iconColor="text-info" />
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground border-b border-border">
                      <th className="text-left pb-2 font-medium">Name</th>
                      <th className="text-left pb-2 font-medium">Role</th>
                      <th className="text-left pb-2 font-medium">Truck</th>
                      <th className="text-left pb-2 font-medium">Driver</th>
                      <th className="text-center pb-2 font-medium" title="Routes organized">Routes</th>
                      <th className="text-center pb-2 font-medium" title="Anchor point location">AP Loc.</th>
                      <th className="text-center pb-2 font-medium" title="Supplies ready">Supplies</th>
                      <th className="text-center pb-2 font-medium" title="Driver support">Support</th>
                      <th className="text-left pb-2 font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {detail.responses.map(r => (
                      <tr
                        key={r.id}
                        className="hover:bg-accent/40 transition-colors cursor-pointer"
                        onClick={() => setModalResponse(r)}
                      >
                        <td className="py-2 pr-3 font-medium text-foreground whitespace-nowrap">
                          {r.respondent_name}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground capitalize">{r.respondent_role}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{r.truck_name ?? '—'}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{r.driver_name ?? '—'}</td>
                        <td className="py-2 pr-3 text-center"><YesNo value={r.routes_organized} /></td>
                        <td className="py-2 pr-3 text-center"><YesNo value={r.anchor_point_location} /></td>
                        <td className="py-2 pr-3 text-center"><YesNo value={r.supplies_ready} /></td>
                        <td className="py-2 pr-3 text-center"><YesNo value={r.driver_support} /></td>
                        <td className="py-2 text-muted-foreground text-xs max-w-[180px] truncate">
                          {r.notes ? (
                            <span className="italic">{r.notes}</span>
                          ) : (
                            <span className="text-subtle">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {detail.responses.length === 0 && (
            <div className="card text-center py-8 text-sm text-muted-foreground">
              No responses yet for {detail.date}.
            </div>
          )}
        </>
      )}

      {!detail && !detailLoading && surveys.length === 0 && !loading && (
        <div className="card text-center py-12 text-sm text-muted-foreground">
          No surveys activated yet. Select a date above and activate the first one.
        </div>
      )}

      {/* Response detail modal */}
      {modalResponse && (
        <ResponseModal response={modalResponse} onClose={() => setModalResponse(null)} />
      )}
    </div>
  );
}
