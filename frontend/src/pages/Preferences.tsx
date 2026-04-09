import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { 
  getRelationships, createRelationship, deleteRelationship,
  getOffDays, createOffDay, deleteOffDay, approveOffDay, rejectOffDay,
  type EmployeeRelationship, type EmployeeOffDay
} from '../api/preferences';
import {
  getTimeOffRequests, createTimeOffRequest, deleteTimeOffRequest,
  approveTimeOffRequest, rejectTimeOffRequest, type TimeOffRequest
} from '../api/timeOffRequests';
import { Heart, ShieldOff, CalendarOff, CalendarClock, X, Check, Ban } from 'lucide-react';

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
  const { groups = [] } = useAuth();
  const isMgmt = groups.some((r: string) => ['admin', 'management'].includes(r));
  const [myId, setMyId] = useState('');
  const [employees, setEmployees] = useState<any[]>([]);
  const [relationships, setRelationships] = useState<EmployeeRelationship[]>([]);
  const [offDays, setOffDays] = useState<EmployeeOffDay[]>([]);
  const [timeOffRequests, setTimeOffRequests] = useState<TimeOffRequest[]>([]);
  const [targetFavId, setTargetFavId] = useState('');
  const [targetBanId, setTargetBanId] = useState('');
  const [selectedOffDay, setSelectedOffDay] = useState('Monday');
  const [selectedDate, setSelectedDate] = useState('');

  useEffect(() => {
    axiosClient.get('/employees/')
      .then(res => {
        const sortedEmployees = res.data.sort((a: any, b: any) => {
          const nameA = a.first_name || a.name || '';
          const nameB = b.first_name || b.name || '';
          return nameA.localeCompare(nameB);
        });
        setEmployees(sortedEmployees);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (myId) loadPreferences(myId);
    else { setRelationships([]); setOffDays([]); setTimeOffRequests([]); }
  }, [myId]);

  const loadPreferences = async (id: string) => {
    try {
      const [rels, days, tReqs] = await Promise.all([
        getRelationships(id), getOffDays(id), getTimeOffRequests(id)
      ]);
      setRelationships(rels); setOffDays(days); setTimeOffRequests(tReqs);
    } catch (err) { console.error("Error loading preferences:", err); }
  };

  const handleAddFav = async () => { if (!myId || !targetFavId) return; await createRelationship(myId, targetFavId, 'fav'); loadPreferences(myId); setTargetFavId(''); };
  const handleAddBan = async () => { if (!myId || !targetBanId) return; await createRelationship(myId, targetBanId, 'ban'); loadPreferences(myId); setTargetBanId(''); };
  const handleAddOffDay = async () => { if (!myId) return; await createOffDay(myId, selectedOffDay); loadPreferences(myId); setSelectedOffDay('Monday'); };
  const handleAddTimeOffReq = async () => {
    if (!myId || !selectedDate) return;
    try { await createTimeOffRequest(myId, selectedDate); loadPreferences(myId); setSelectedDate(''); }
    catch (err: any) { alert(err?.response?.data?.detail || 'Failed'); }
  };
  const handleDeleteRelationship = async (id: string) => { await deleteRelationship(id); loadPreferences(myId); };
  const handleDeleteOffDay = async (id: string) => { await deleteOffDay(id); loadPreferences(myId); };
  const handleApproveOffDay = async (id: string) => { await approveOffDay(id); loadPreferences(myId); };
  const handleRejectOffDay = async (id: string) => { await rejectOffDay(id); loadPreferences(myId); };
  const handleDeleteTimeOffReq = async (id: string) => { await deleteTimeOffRequest(id); loadPreferences(myId); };
  const handleApproveTimeOffReq = async (id: string) => { await approveTimeOffRequest(id); loadPreferences(myId); };
  const handleRejectTimeOffReq = async (id: string) => { await rejectTimeOffRequest(id); loadPreferences(myId); };

  const getEmpName = (id: string) => {
    const emp = employees.find(e => e.id === id);
    return emp ? `${emp.first_name || emp.name} (${emp.role})` : id;
  };

  const employeeOptions = employees.map(emp => ({
    value: emp.id, label: `${emp.first_name || emp.name} (${emp.role})`
  }));

  const getGroupedOptions = (excludeId?: string, isSelector?: boolean) => {
    let validEmployees = excludeId ? employees.filter(e => e.id !== excludeId) : employees;
    if (isSelector) {
      const currentEmp = employees.find(e => e.id === excludeId);
      if (currentEmp && currentEmp.role === 'driver') {
        validEmployees = validEmployees.filter(e => e.role !== 'driver');
      }
    }
    const roles = Array.from(new Set(validEmployees.map(e => e.role))).sort();
    return roles.map(role => ({
      label: role.charAt(0).toUpperCase() + role.slice(1) + 's',
      options: validEmployees
        .filter(emp => emp.role === role)
        .map(emp => ({
          value: emp.id, 
          label: `${emp.first_name || emp.name} (${emp.role})`
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

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">Preferences</h1>

      <div className="card">
        <label className="block text-sm font-medium text-foreground mb-2">Select Employee</label>
        <Select
          options={getGroupedOptions()}
          value={employeeOptions.find(o => o.value === myId) || null}
          onChange={(sel) => setMyId(sel?.value || '')}
          placeholder="Search for an identity to impersonate..."
          isClearable
          isSearchable
          styles={selectStyles}
        />
      </div>

      {myId && (
        <div className="space-y-6">
          {/* Favorites */}
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

          {/* Bans */}
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

          {/* Off Days */}
          <Section icon={CalendarOff} title="Recurring Off Days" iconColor="text-info">
            <div className="flex gap-3 mb-4">
              <select className="input-field flex-1" value={selectedOffDay} onChange={(e) => setSelectedOffDay(e.target.value)}>
                {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map(d => <option key={d} value={d}>{d}</option>)}
              </select>
              <button onClick={handleAddOffDay} className="btn-primary text-xs">Add</button>
            </div>
            <ul className="space-y-2">
              {offDays.map(od => (
                <li key={od.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-sm text-foreground">{od.day_of_week}</span>
                    <span className={statusBadge(od.status)}>{od.status}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {isMgmt && od.status === 'pending' && (
                      <>
                        <button onClick={() => handleApproveOffDay(od.id)} className="btn-ghost text-success p-1.5"><Check className="w-4 h-4" /></button>
                        <button onClick={() => handleRejectOffDay(od.id)} className="btn-ghost text-danger p-1.5"><Ban className="w-4 h-4" /></button>
                      </>
                    )}
                    <button onClick={() => handleDeleteOffDay(od.id)} className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"><X className="w-4 h-4" /></button>
                  </div>
                </li>
              ))}
              {offDays.length === 0 && <li className="text-subtle py-4 text-center">No off days set.</li>}
            </ul>
          </Section>

          {/* Time Off Requests */}
          <Section icon={CalendarClock} title="Specific Time Off" iconColor="text-warning">
            <div className="flex gap-3 mb-4">
              <input type="date" className="input-field flex-1" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} />
              <button onClick={handleAddTimeOffReq} className="btn-primary text-xs">Request</button>
            </div>
            <ul className="space-y-2">
              {timeOffRequests.map(req => (
                <li key={req.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-sm text-foreground">{req.date}</span>
                    <span className={statusBadge(req.status)}>{req.status}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {isMgmt && req.status === 'pending' && (
                      <>
                        <button onClick={() => handleApproveTimeOffReq(req.id)} className="btn-ghost text-success p-1.5"><Check className="w-4 h-4" /></button>
                        <button onClick={() => handleRejectTimeOffReq(req.id)} className="btn-ghost text-danger p-1.5"><Ban className="w-4 h-4" /></button>
                      </>
                    )}
                    <button onClick={() => handleDeleteTimeOffReq(req.id)} className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"><X className="w-4 h-4" /></button>
                  </div>
                </li>
              ))}
              {timeOffRequests.length === 0 && <li className="text-subtle py-4 text-center">No requests yet.</li>}
            </ul>
          </Section>
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
