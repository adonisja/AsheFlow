/**
 * The name you're called in AsheFlow (ADR-567), on My account.
 *
 * Only the person sets it. It is shown everywhere instead of the legal name;
 * the legal name stays the record (payroll, Amazon) and is shown here, to the
 * person, read-only. Nothing anywhere else marks that someone uses a chosen
 * name.
 */
import { useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';

const field = 'w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all';

// Mirrors chosen_name.normalise on the server: letters (any script), spaces,
// apostrophes, hyphens and periods, starting with a letter.
const SHAPE = /^\p{L}[\p{L} '’.\-]*$/u;
export const CHOSEN_NAME_RULES =
  'Up to 100 characters: letters, spaces, apostrophes, hyphens and periods, starting with a letter.';

type Me = { name: string; legal_name?: string; chosen_name?: string | null };
type Props = { legalName: string; chosen: string | null; onChanged: (me: Me) => void };

export default function ChosenNameSection({ legalName, chosen, onChanged }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const cleaned = draft.trim().replace(/\s+/g, ' ');
  const shown = chosen || legalName;

  const save = async () => {
    if (!cleaned || cleaned.length > 100 || !SHAPE.test(cleaned)) { setMsg(CHOSEN_NAME_RULES); return; }
    setBusy(true); setMsg('');
    try {
      const { data } = await axiosClient.put<Me>('/employees/me/chosen-name', { chosen_name: cleaned });
      setEditing(false); onChanged(data);
    } catch (e) {
      setMsg(errorText(e, "Couldn't save your name."));
    } finally { setBusy(false); }
  };

  const useLegal = async () => {
    setBusy(true); setMsg('');
    try {
      const { data } = await axiosClient.delete<Me>('/employees/me/chosen-name');
      setEditing(false); onChanged(data);
    } catch (e) {
      setMsg(errorText(e, "Couldn't change your name."));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-2.5">
      {!editing ? (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Name shown to others</span>
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-medium text-foreground truncate">{shown}</span>
            <button onClick={() => { setDraft(chosen ?? ''); setEditing(true); setMsg(''); }}
                    className="text-sm text-primary hover:underline shrink-0">
              Change
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-2 max-w-md">
          <label htmlFor="chosen-name" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Name shown to others
          </label>
          <input id="chosen-name" value={draft} onChange={e => setDraft(e.target.value)} maxLength={100}
                 autoComplete="nickname" aria-describedby="chosen-name-help" className={field} />
          <div id="chosen-name-help" className="text-xs text-muted-foreground space-y-1">
            <p>Everyone in AsheFlow will see this name instead of your legal name, on every screen and in new messages.</p>
            <p>Your legal name stays on payroll and other official records. Messages sent before the change keep the old name.</p>
          </div>
          {msg && <p role="alert" className="text-xs text-destructive">{msg}</p>}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => { setEditing(false); setMsg(''); }} className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
            {chosen && (
              <button onClick={useLegal} disabled={busy} className="btn-ghost text-sm px-3 py-1.5 disabled:opacity-50">
                Use my legal name
              </button>
            )}
            <button onClick={save} disabled={busy || !cleaned || cleaned === chosen}
                    className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
      {chosen && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Legal name</span>
          <span className="text-sm text-muted-foreground truncate" title="From your employer's records. Ask management to correct it.">
            {legalName}
          </span>
        </div>
      )}
    </div>
  );
}
