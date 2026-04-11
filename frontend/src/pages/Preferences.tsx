import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import {
  getRelationships, createRelationship, deleteRelationship,
  type EmployeeRelationship
} from '../api/preferences';
import { getAllEmployeeRelationships } from '../api/employeeRelationships';
import NotificationBanner from '../components/NotificationBanner';
import { Heart, ShieldOff, X, ArrowLeftRight } from 'lucide-react';

const selectStyles = {
  control: (base: any, state: any) => ({
    ...base,
    borderRadius: '0.75rem',
    borderColor: state.isFocused ? 'hsl(240 5% 65%)' : 'hsl(240 6% 90%)',
    boxShadow: state.isFocused ? '0 0 0 2px hsl(240 5% 65% / 0.2)' : 'none',
    padding: '2px 4px',
    fontSize: '0.875rem',
    '&:hover': { borderColor: 'hsl(240 5% 65%)' },
  }),
  option: (base: any, state: any) => ({
    ...base,
    fontSize: '0.875rem',
    backgroundColor: state.isSelected ? 'hsl(240 5% 16%)' : state.isFocused ? 'hsl(240 5% 96%)' : 'white',
    color: state.isSelected ? 'white' : 'hsl(240 10% 10%)',
  }),
  groupHeading: (base: any) => ({
    ...base,
    fontSize: '0.75rem',
    fontWeight: '600',
    color: 'hsl(240 5% 40%)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  }),
};

const Preferences = () => {
  const { groups = [], user } = useAuth();
  const isAdmin = groups.includes('admin');
  const isTrainee = groups.includes('trainee');
  const canFavBan = groups.some(r => ['driver', 'walker', 'trainer'].includes(r));
  const canReassign = groups.some(r => ['walker', 'trainer'].includes(r));

  const [myId, setMyId] = useState<string>(isAdmin ? '' : (user?.userId || user?.username || ''));
  const [employees, setEmployees] = useState<any[]>([]);
  const [relationships, setRelationships] = useState<EmployeeRelationship[]>([]);
  const [targetFavId, setTargetFavId] = useState('');
  const [targetBanId, setTargetBanId] = useState('');

  // Truck reassignment — today-only, walker/trainer only
  const [changeRequests, setChangeRequests] = useState<any[]>([]);
  const [changeRequestReason, setChangeRequestReason] = useState('');
  const [changeRequestError, setChangeRequestError] = useState('');

  const [allRelationships, setAllRelationships] = useState<Record<string, { favs: string[], bans: string[] }>>({});

  useEffect(() => {
    axiosClient.get('/employees/')
      .then(res => {
        const sorted = res.data.sort((a: any, b: any) =>
          (a.first_name || a.name || '').localeCompare(b.first_name || b.name || '')
        );
        setEmployees(sorted);
        if (!isAdmin && user && !myId) {
          const self = sorted.find((e: any) => e.id === user.userId || e.id === user.username);
          if (self) setMyId(self.id);
        }
      })
      .catch(console.error);

    if (isAdmin) {
      getAllEmployeeRelationships().then(setAllRelationships).catch(console.error);
    }
  }, [isAdmin, user]);

  useEffect(() => {
    if (myId) {
      loadPreferences(myId);
      loadChangeRequests(myId);
    } else {
      setRelationships([]);
    }
  }, [myId]);

  const loadPreferences = async (id: string) => {
    try {
      const rels = await getRelationships(id);
      setRelationships(rels);
      if (isAdmin) getAllEmployeeRelationships().then(setAllRelationships).catch(console.error);
    } catch (err) { console.error(err); }
  };

  const loadChangeRequests = async (id: string) => {
    try {
      const res = await axiosClient.get(`/assignment-change-requests/employee/${id}`);
      setChangeRequests(res.data);
    } catch (err) { console.error(err); }
  };

  const today = new Date().toISOString().split('T')[0];

  const handleSubmitChangeRequest = async () => {
    if (!myId) return;
    setChangeRequestError('');
    try {
      await axiosClient.post('/assignment-change-requests/', {
        employee_id: myId,
        requested_date: today,
        reason: changeRequestReason || undefined,
      });
      setChangeRequestReason('');
      loadChangeRequests(myId);
    } catch (err: any) {
      setChangeRequestError(err.response?.data?.detail || 'Failed to submit request.');
    }
  };

  const handleCancelChangeRequest = async (id: string) => {
    try {
      await axiosClient.delete(`/assignment-change-requests/${id}`);
      loadChangeRequests(myId);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to cancel request.');
    }
  };

  const handleAddFav = async () => { if (!myId || !targetFavId) return; await createRelationship(myId, targetFavId, 'fav'); loadPreferences(myId); setTargetFavId(''); };
  const handleAddBan = async () => { if (!myId || !targetBanId) return; await createRelationship(myId, targetBanId, 'ban'); loadPreferences(myId); setTargetBanId(''); };
  const handleDeleteRelationship = async (id: string) => { await deleteRelationship(id); loadPreferences(myId); };

  const getEmpName = (id: string) => {
    const emp = employees.find(e => e.id === id);
    return emp ? `${emp.first_name || emp.name} (${emp.role})` : id;
  };

  const EXEMPT_ROLES = ['management', 'admin', 'dispatch', 'trainee'];
  const employeeOptions = employees
    .filter(emp => !EXEMPT_ROLES.includes(emp.role))
    .map(emp => ({ value: emp.id, label: `${emp.first_name || emp.name} (${emp.role})` }));

  const getGroupedOptions = (excludeId?: string, isSelector?: boolean) => {
    let valid = excludeId ? employees.filter(e => e.id !== excludeId) : employees;
    valid = valid.filter(e => !EXEMPT_ROLES.includes(e.role));
    if (isSelector) {
      const current = employees.find(e => e.id === excludeId);
      if (current?.role === 'driver') valid = valid.filter(e => e.role !== 'driver');
    }
    const roles = Array.from(new Set(valid.map(e => e.role))).sort();
    return roles.map(role => ({
      label: role.charAt(0).toUpperCase() + role.slice(1) + 's',
      options: valid.filter(e => e.role === role).map(e => ({
        value: e.id, label: `${e.first_name || e.name} (${e.role})`
      }))
    }));
  };

  const favs = relationships.filter(r => r.relationship_type === 'fav');
  const bans = relationships.filter(r => r.relationship_type === 'ban');

  const statusBadge = (status: string) => {
    if (status === 'pending') return 'badge-warning';
    if (status === 'approved') return 'badge-success';
    if (status === 'rejected') return 'badge-danger';
    return 'badge bg-accent text-muted-foreground';
  };

  // For the reassignment section, only show pending/today's requests
  const hasPendingToday = changeRequests.some(r => r.requested_date === today && r.status === 'pending');
  const recentRequests = changeRequests.slice(0, 5);

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">Preferences</h1>

      {myId && !isAdmin && <NotificationBanner employeeId={myId} />}

      {isAdmin && (
        <div className="card">
          <label className="block text-sm font-medium text-foreground mb-2">Select Employee</label>
          <Select
            options={getGroupedOptions()}
            value={employeeOptions.find(o => o.value === myId) || null}
            onChange={(sel) => setMyId(sel?.value || '')}
            placeholder="Search for an employee..."
            isClearable
            isSearchable
            styles={selectStyles}
          />
        </div>
      )}

      {myId && (
        <div className="space-y-6">
          {/* Truck Reassignment — walker/trainer only, today-only */}
          {(canReassign || isAdmin) && (
            <Section icon={ArrowLeftRight} title="Truck Reassignment Request" iconColor="text-warning">
              <p className="text-sm text-subtle mb-4">
                Request to be moved to a different truck for <strong>today</strong>. You must be currently assigned to submit. Dispatch will review.
              </p>
              {!hasPendingToday ? (
                <div className="flex flex-col gap-3 mb-4">
                  <input
                    type="text"
                    value={changeRequestReason}
                    onChange={(e) => setChangeRequestReason(e.target.value)}
                    placeholder="Reason (optional)"
                    className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  {changeRequestError && (
                    <p className="text-xs text-danger">{changeRequestError}</p>
                  )}
                  <button
                    onClick={handleSubmitChangeRequest}
                    className="btn-primary text-xs self-start"
                  >
                    Request Reassignment for Today
                  </button>
                </div>
              ) : (
                <p className="text-sm text-warning mb-4">You have a pending reassignment request for today.</p>
              )}
              <ul className="space-y-2">
                {recentRequests.length === 0 && (
                  <li className="text-subtle py-4 text-center text-sm">No reassignment requests yet.</li>
                )}
                {recentRequests.map((req) => (
                  <li key={req.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium text-foreground">{req.requested_date}</span>
                      {req.reason && <span className="text-xs text-subtle">{req.reason}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={statusBadge(req.status)}>{req.status}</span>
                      {req.status === 'pending' && (
                        <button
                          onClick={() => handleCancelChangeRequest(req.id)}
                          className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"
                          title="Cancel request"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* Favorites — driver/walker/trainer only (not trainee) */}
          {(canFavBan || isAdmin) && (
            <Section icon={Heart} title="Favorites" iconColor="text-success">
              <div className="flex gap-3 mb-4">
                <div className="flex-1">
                  <Select
                    options={getGroupedOptions(myId, true)}
                    value={employeeOptions.find(o => o.value === targetFavId) || null}
                    onChange={(s) => setTargetFavId(s?.value || '')}
                    placeholder="Search and select to add..."
                    isClearable
                    isSearchable
                    styles={selectStyles}
                  />
                </div>
                <button onClick={handleAddFav} className="btn-primary text-xs">Add</button>
              </div>
              <ItemList items={favs} getLabel={(f) => getEmpName(f.target_employee_id)} onDelete={(f) => handleDeleteRelationship(f.id)} emptyText="No favorites yet." />
            </Section>
          )}

          {/* Blocked — driver/walker/trainer only (not trainee) */}
          {(canFavBan || isAdmin) && (
            <Section icon={ShieldOff} title="Blocked" iconColor="text-danger">
              <div className="flex gap-3 mb-4">
                <div className="flex-1">
                  <Select
                    options={getGroupedOptions(myId)}
                    value={employeeOptions.find(o => o.value === targetBanId) || null}
                    onChange={(s) => setTargetBanId(s?.value || '')}
                    placeholder="Search and select to block..."
                    isClearable
                    isSearchable
                    styles={selectStyles}
                  />
                </div>
                <button onClick={handleAddBan} className="btn-primary text-xs">Add</button>
              </div>
              <ItemList items={bans} getLabel={(b) => getEmpName(b.target_employee_id)} onDelete={(b) => handleDeleteRelationship(b.id)} emptyText="No blocks yet." />
            </Section>
          )}

          {/* Trainees see a placeholder explaining what they'll unlock */}
          {isTrainee && !isAdmin && (
            <div className="card text-center py-8">
              <p className="text-sm text-subtle">Dispatch preferences (favorites & blocks) become available after graduating from the training program.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

function Section({ icon: Icon, title, iconColor, children }: { icon: any; title: string; iconColor: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-5">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
        <h2 className="section-title">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function ItemList({ items, getLabel, onDelete, emptyText }: { items: any[]; getLabel: (item: any) => string; onDelete: (item: any) => void; emptyText: string }) {
  return (
    <ul className="space-y-2">
      {items.map(item => (
        <li key={item.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
          <span className="text-sm font-medium text-foreground">{getLabel(item)}</span>
          <button onClick={() => onDelete(item)} className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"><X className="w-4 h-4" /></button>
        </li>
      ))}
      {items.length === 0 && <li className="text-subtle py-4 text-center">{emptyText}</li>}
    </ul>
  );
}

export default Preferences;
