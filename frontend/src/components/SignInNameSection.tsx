/**
 * Your own sign-in name (ADR-566 D4): a second name you can sign in with,
 * beside the username, for tenant and platform accounts alike.
 *
 * Only the person chooses it; an admin can only clear one. Cognito enforces
 * uniqueness (against every username and every other sign-in name), so the
 * client checks the shape and shows the server's answer. Renders nothing until
 * the environment's pool accepts the alias (`available`).
 */
import { useState } from 'react';
import { AtSign } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';

const field = 'w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground font-mono focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all';

// Mirrors sign_in_name.normalise on the server.
const SHAPE = /^[a-z][a-z0-9._-]{2,29}$/;
export const SIGN_IN_NAME_RULES =
  '3–30 characters: letters, numbers, dots, dashes or underscores, starting with a letter.';

type Props = {
  path: string;               // /employees/me/sign-in-name or /platform/me/sign-in-name
  available: boolean;
  current: string | null;
  username: string;
  onSaved?: (name: string | null) => void;
};

export default function SignInNameSection({ path, available, current, username, onSaved }: Props) {
  const [name, setName] = useState<string | null>(current);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  if (!available) return null;

  const cleaned = draft.trim().toLowerCase();
  const shapeOk = SHAPE.test(cleaned);

  const save = async () => {
    if (!shapeOk) { setMsg(SIGN_IN_NAME_RULES); return; }
    if (cleaned === username.toLowerCase()) { setMsg("That's already your username. Choose something different."); return; }
    setBusy(true); setMsg('');
    try {
      const { data } = await axiosClient.put<{ sign_in_name: string }>(path, { sign_in_name: cleaned });
      setName(data.sign_in_name); setEditing(false); onSaved?.(data.sign_in_name);
    } catch (e) {
      setMsg(errorText(e, "Couldn't save your sign-in name."));
    } finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true); setMsg('');
    try {
      await axiosClient.delete(path);
      setName(null); setEditing(false); onSaved?.(null);
    } catch (e) {
      setMsg(errorText(e, "Couldn't remove your sign-in name."));
    } finally { setBusy(false); }
  };

  if (!editing) {
    return (
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Sign-in name</span>
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-sm truncate ${name ? 'text-foreground font-mono font-medium' : 'text-muted-foreground'}`}>
            {name || 'None'}
          </span>
          <button onClick={() => { setDraft(name ?? ''); setEditing(true); setMsg(''); }}
                  className="text-sm text-primary hover:underline shrink-0">
            {name ? 'Change' : 'Add'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2 max-w-sm">
      <label htmlFor="sign-in-name" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
        <AtSign className="w-3.5 h-3.5" aria-hidden="true" /> Sign-in name
      </label>
      <input id="sign-in-name" value={draft} onChange={e => setDraft(e.target.value)} maxLength={30}
             autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="off"
             aria-describedby="sign-in-name-help" className={field} />
      <p id="sign-in-name-help" className="text-xs text-muted-foreground">
        You can sign in with this or with your username, <span className="font-mono">{username}</span>.
        {' '}{SIGN_IN_NAME_RULES}
      </p>
      {msg && <p role="alert" className="text-xs text-destructive">{msg}</p>}
      <div className="flex flex-wrap gap-2">
        <button onClick={() => { setEditing(false); setMsg(''); }} className="btn-ghost text-sm px-3 py-1.5">Cancel</button>
        {name && (
          <button onClick={remove} disabled={busy} className="btn-ghost text-sm px-3 py-1.5 text-destructive disabled:opacity-50">
            Remove
          </button>
        )}
        <button onClick={save} disabled={busy || !cleaned || cleaned === name}
                className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}
