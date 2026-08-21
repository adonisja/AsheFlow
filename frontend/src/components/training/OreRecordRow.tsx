/**
 * ADR-281 — the ORE day, as a manager sees it.
 *
 * Three distinct states, because they mean different things:
 *
 *   never uploaded   — nothing to review; the trainee has not finished ORE
 *   uploaded, live   — a button that opens the certificate
 *   uploaded, expired — the completion is on record, the FILE is gone
 *
 * The third is the one worth getting right. Retention is 48h because a
 * certificate carries the trainee's name and an Amazon training id, so an
 * expired certificate is a normal outcome — not an error, and not a missing
 * record.
 */
import { useState } from 'react';
import { FileCheck2, FileX2, ExternalLink, LogOut } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { errorText } from '../../utils/errorText';

type OreRecord = {
  id: string;
  ore_completed_at?: string | null;
  has_certificate?: boolean;
  left_early?: boolean;
  left_early_at?: string | null;
};

export default function OreRecordRow({ record }: { record: OreRecord }) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completed = !!record.ore_completed_at;

  const open = async () => {
    setOpening(true);
    setError(null);
    try {
      const { data } = await axiosClient.get<{ url: string }>(
        `/training/record/${record.id}/ore-certificate`,
      );
      // The API hands back a short-lived URL rather than proxying bytes, so
      // certificate content never lands in application logs.
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (e) {
      setError(errorText(e, 'Could not open the certificate.'));
    } finally {
      setOpening(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {completed ? (
            <FileCheck2 className="w-4 h-4 text-success shrink-0" />
          ) : (
            <FileX2 className="w-4 h-4 text-muted-foreground shrink-0" />
          )}
          <div className="min-w-0">
            <p className="text-sm font-medium">ORE certificate</p>
            <p className="text-xs text-muted-foreground">
              {completed
                ? `Completed ${new Date(record.ore_completed_at!).toLocaleString()}`
                : 'Not uploaded yet'}
            </p>
          </div>
        </div>

        {completed && record.has_certificate && (
          <button
            onClick={open}
            disabled={opening}
            className="btn-ghost text-xs inline-flex items-center gap-1.5 shrink-0 disabled:opacity-50"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {opening ? 'Opening…' : 'View'}
          </button>
        )}
      </div>

      {/* The attestation outlives the file — say that plainly, or an expired
          certificate reads as a missing one. */}
      {completed && !record.has_certificate && (
        <p className="text-xs text-muted-foreground">
          The file has passed its 48-hour retention window. Completion remains
          on record.
        </p>
      )}

      {/* ADR-281 D5: attendance data, not a mark. Worded so it does not read
          as a disciplinary note — leaving after ORE is permitted. */}
      {record.left_early && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground pt-1 border-t border-border">
          <LogOut className="w-3.5 h-3.5 shrink-0" />
          <span>
            Left after completing ORE
            {record.left_early_at
              ? ` at ${new Date(record.left_early_at).toLocaleTimeString([], {
                  hour: 'numeric',
                  minute: '2-digit',
                })}`
              : ''}
            {' '}· affects pay for this date
          </span>
        </div>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
