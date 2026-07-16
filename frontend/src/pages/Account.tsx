import React, { useState } from 'react';
import { updatePassword } from 'aws-amplify/auth';
import { useAuth } from '../contexts/AuthContext';
import { Lock, CheckCircle2 } from 'lucide-react';
import Avatar from '../components/ui/Avatar';
import MyPerformanceCard from '../components/MyPerformanceCard';

export default function Account() {
  const { user, groups } = useAuth();

  const [current,  setCurrent]  = useState('');
  const [next,     setNext]     = useState('');
  const [confirm,  setConfirm]  = useState('');
  const [error,    setError]    = useState('');
  const [success,  setSuccess]  = useState(false);
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess(false);
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8)  { setError('Password must be at least 8 characters.'); return; }
    setLoading(true);
    try {
      await updatePassword({ oldPassword: current, newPassword: next });
      setSuccess(true);
      setCurrent(''); setNext(''); setConfirm('');
    } catch (err: any) {
      const msg = err?.message ?? '';
      if (msg.includes('NotAuthorizedException') || msg.includes('Incorrect')) {
        setError('Current password is incorrect.');
      } else if (msg.includes('LimitExceededException')) {
        setError('Too many attempts. Please wait a few minutes and try again.');
      } else {
        setError(msg || 'Failed to update password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">My Account</h1>

      {/* Profile info */}
      <div className="card">
        <div className="flex items-center gap-4 mb-6">
          <Avatar size={56} />
          <div>
            <h2 className="text-lg font-bold text-foreground">{user?.displayName || user?.username}</h2>
            <p className="text-sm text-muted-foreground capitalize">{groups[0]?.replace('_', ' ') ?? ''}</p>
          </div>
        </div>
        <dl className="space-y-0">
          {[
            { label: 'Username', value: user?.username || '—' },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between py-2 border-t border-border">
              <dt className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{label}</dt>
              <dd className="text-sm font-medium text-foreground font-mono">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* My Performance (our live stats; ADR-203). The official Amazon Scorecard
          card (ADR-204) will sit alongside this. */}
      <MyPerformanceCard />

      {/* Change password */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
            <Lock className="w-4 h-4 text-primary" />
          </div>
          <h2 className="section-title">Change Password</h2>
        </div>

        {success ? (
          <div className="flex items-center gap-2 text-success text-sm font-medium py-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            Password updated successfully.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 max-w-sm">
            {[
              { label: 'Current password', value: current, setter: setCurrent, auto: 'current-password' },
              { label: 'New password',     value: next,    setter: setNext,    auto: 'new-password' },
              { label: 'Confirm new password', value: confirm, setter: setConfirm, auto: 'new-password' },
            ].map(({ label, value, setter, auto }) => (
              <div key={label} className="space-y-1">
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{label}</label>
                <input
                  type="password"
                  value={value}
                  onChange={e => { setter(e.target.value); setError(''); setSuccess(false); }}
                  required
                  autoComplete={auto}
                  className="w-full px-3 py-2.5 rounded-xl border border-border bg-input text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all"
                />
              </div>
            ))}
            {error && <p className="text-xs text-danger">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="btn-primary text-sm px-4 py-2 flex items-center gap-2 disabled:opacity-50"
            >
              {loading && <span className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
              {loading ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
