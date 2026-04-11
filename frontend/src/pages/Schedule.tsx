  // Helper to check if a date is in the past or today
  const isExpired = (dateStr: string) => {
    const today = new Date();
    const reqDate = new Date(dateStr);
    today.setHours(0,0,0,0);
    reqDate.setHours(0,0,0,0);
    return reqDate <= today;
  };
import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import axiosClient from '../api/axiosClient';
import { getSchedule, createOffDay } from '../api/preferences';
import { createTimeOffRequest } from '../api/timeOffRequests';
import { CalendarDays, Clock, Users, CheckCircle2, XCircle, ClipboardCheck, ChevronLeft, ChevronRight } from 'lucide-react';
import { MiniCalendar } from '../components/MiniCalendar';
import NotificationBanner from '../components/NotificationBanner';
import { useAuth } from '../contexts/AuthContext';

export interface CrewMember {
  id: string;
  name: string;
  role: string;
}

interface ScheduleDay {
  date: string;
  status: string;
  truck_name: string | null;
  crew: CrewMember[] | null;
}

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
};

const Schedule = () => {
  const { groups, user } = useAuth();
  const isAdmin = groups.includes('admin');

  const [employees, setEmployees] = useState<any[]>([]);
  // For non-management, always use their own ID
  const [myId, setMyId] = useState<string>(isAdmin ? '' : (user?.userId || user?.username || ''));
  const [scheduleData, setScheduleData] = useState<ScheduleDay[]>([]);
  const [availableData, setAvailableData] = useState<{driver: any[], trainer: any[], walker: any[]} | null>(null);
  const [currentMonth, setCurrentMonth] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<string>('');
  
  const [pendingRequests, setPendingRequests] = useState<any[]>([]);
  const [pendingOffDays, setPendingOffDays] = useState<any[]>([]);

  const todayStr = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  })();

  useEffect(() => {
    axiosClient.get('/employees/')
      .then(res => {
        const sortedEmployees = res.data.sort((a: any, b: any) => {
          const nameA = a.first_name || a.name || '';
          const nameB = b.first_name || b.name || '';
          return nameA.localeCompare(nameB);
        });
        setEmployees(sortedEmployees);
        // For non-management, set myId to their own employee record if not already set
        if (!isAdmin && user && !myId) {
          const self = sortedEmployees.find((e: any) => e.id === user.userId || e.id === user.username);
          if (self) setMyId(self.id);
        }
      })
      .catch(console.error);
    setSelectedDate(todayStr); // Default select today
  }, [isAdmin, user]);

  const fetchSchedule = async (employeeId: string, monthDate: Date) => {
    if (!employeeId) return;
    const startDate = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
    const endDate = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0);

    const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    
    try {
      const data = await getSchedule(employeeId, fmt(startDate), fmt(endDate));
      setScheduleData(data);
    } catch (err) {
      console.error("Failed to load schedule", err);
    }
  };

  const fetchAvailability = async (dateStr: string) => {
    if (!isAdmin) return;
    try {
      const res = await axiosClient.get(`/schedule/available/${dateStr}`);
      setAvailableData(res.data);
    } catch (err) {
      console.error("Failed to load availability", err);
    }
  };

  useEffect(() => { fetchSchedule(myId, currentMonth); }, [myId, currentMonth]);
  useEffect(() => { if(selectedDate) fetchAvailability(selectedDate); }, [selectedDate, isAdmin]);

  useEffect(() => {
    if (isAdmin) {
      axiosClient.get('/time-off-requests/')
        .then(res => setPendingRequests(res.data.filter((r: any) => r.status === 'pending')))
        .catch(console.error);
      axiosClient.get('/employee-off-days/')
        .then(res => setPendingOffDays(res.data.filter((r: any) => r.status === 'pending')))
        .catch(console.error);
    } else if (myId) {
      axiosClient.get(`/time-off-requests/?employee_id=${myId}`)
        .then(res => setPendingRequests(res.data.filter((r: any) => r.status === 'pending')))
        .catch(console.error);
    }
  }, [isAdmin, myId]);

  const handleApprove = (type: 'request' | 'offDay', id: string) => {
    const url = type === 'request' 
      ? `/time-off-requests/${id}/approve`
      : `/employee-off-days/${id}/approve`;
    axiosClient.patch(url).then(() => {
      if (type === 'request') {
        setPendingRequests(prev => prev.filter(r => r.id !== id));
      } else {
        setPendingOffDays(prev => prev.filter(r => r.id !== id));
      }
      if (myId) fetchSchedule(myId, currentMonth);
    });
  };

  const handleReject = (type: 'request' | 'offDay', id: string) => {
    const url = type === 'request' 
      ? `/time-off-requests/${id}/reject`
      : `/employee-off-days/${id}/reject`;
    axiosClient.patch(url).then(() => {
      if (type === 'request') {
        setPendingRequests(prev => prev.filter(r => r.id !== id));
      } else {
        setPendingOffDays(prev => prev.filter(r => r.id !== id));
      }
      if (myId) fetchSchedule(myId, currentMonth);
    });
  };

  const handleRequestSpecificPTO = async (dateStr: string) => {
    if (!myId) return;
    try {
      await createTimeOffRequest(myId, dateStr);
      await fetchSchedule(myId, currentMonth);
    } catch (err: any) {
      console.error("Failed to request specific PTO", err);
      if (err.response?.data?.detail) alert(err.response.data.detail);
    }
  };

  const employeeOptions = employees.map(emp => ({
    value: emp.id,
    label: `${emp.first_name || emp.name} (${emp.role})`
  }));

  const getDayData = (dateStr: string) => scheduleData.find(s => s.date === dateStr);

  const getTileClass = (dateStr: string) => {
    const dayData = getDayData(dateStr);
    if (!dayData) return '';
    
    if (dayData.status === 'Assigned' || dayData.status === 'Available') return 'bg-success/20 text-success hover:bg-success/30 font-bold border-success/30 border';
    if (dayData.status.includes('Pending')) return 'bg-warning/20 text-warning hover:bg-warning/30 font-bold border-warning/30 border';
    if (dayData.status.includes('Off') || dayData.status === 'Time Off') return 'bg-danger/20 text-danger hover:bg-danger/30 font-bold border-danger/30 border';
    
    return '';
  };

  const selectedDayData = selectedDate ? getDayData(selectedDate) : null;
  const isFutureDate = selectedDate > todayStr;

  const getStatusBadge = (status: string) => {
    if (status === 'Off (Recurring)' || status === 'Time Off') return 'badge-danger';
    if (status === 'Pending Off (Recurring)' || status === 'Pending Time Off') return 'badge-warning';
    if (status === 'Assigned' || status === 'Available') return 'badge-success';
    return 'badge bg-accent text-muted-foreground';
  };

  // Cancel PTO request handler
  const handleCancelPTO = async (dateStr: string) => {
    try {
      // Normalize both dates to YYYY-MM-DD for comparison
      const normalize = (d: string) => d.split('T')[0];
      const req = pendingRequests.find(r => normalize(r.date) === normalize(dateStr));
      if (!req) return alert('No pending PTO request found for this date.');
      await axiosClient.delete(`/time-off-requests/${req.id}`);
      setPendingRequests(prev => prev.filter(r => r.id !== req.id));
      await fetchSchedule(myId, currentMonth);
    } catch (err) {
      alert('Failed to cancel PTO request.');
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">My Schedule</h1>
      
      {isAdmin && (
        <div className="card">
           <label className="block text-sm font-medium text-foreground mb-2">Select Employee</label>
          <Select
            options={employeeOptions}
            value={employeeOptions.find(o => o.value === myId) || null}
            onChange={(selected) => setMyId(selected?.value || '')}
            placeholder="Choose employee..."
            isClearable
            styles={selectStyles}
          />
        </div>
      )}


      
      {isAdmin && (
        <div className="w-full card flex flex-col mt-4 animate-slide-up border-primary/20">
          <h2 className="section-title mb-4 flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-primary" />
            Pending Approvals
          </h2>
          <div className="flex flex-col opacity-100">
            {pendingRequests.length === 0 && pendingOffDays.length === 0 ? (
              <div className="text-center py-6 opacity-60">
                <p className="text-sm font-medium">No pending requests.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {pendingRequests.map(req => {
                  const emp = employees.find(e => e.id === req.employee_id);
                  const expired = isExpired(req.date);
                  return (
                    <div key={req.id} className={`p-4 border rounded-xl bg-background flex flex-col justify-between gap-3 shadow-sm ${expired ? 'opacity-60' : ''}`}>
                      <div>
                        <div className="flex justify-between items-start mb-1">
                          <p className="font-semibold text-sm text-foreground">{emp ? `${emp.first_name || emp.name}` : 'Unknown Worker'}</p>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium border ${expired ? 'bg-muted/10 text-muted border-muted/20' : 'bg-primary/10 text-primary border-primary/20'}`}>{expired ? 'Expired PTO Request' : 'PTO Request'}</span>
                        </div>
                        <p className="text-xs text-muted-foreground">{emp?.role || 'No role'} • Date: {req.date}</p>
                        {expired && <p className="text-xs text-danger mt-1">This request is expired (date is today or in the past).</p>}
                      </div>
                      {!expired && (
                        <div className="flex gap-2 mt-1">
                          <button onClick={() => handleApprove('request', req.id)} className="flex-1 bg-success/10 text-success hover:bg-success/20 border border-success/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Approve</button>
                          <button onClick={() => handleReject('request', req.id)} className="flex-1 bg-danger/10 text-danger hover:bg-danger/20 border border-danger/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Reject</button>
                        </div>
                      )}
                    </div>
                  );
                })}
                {pendingOffDays.map(req => {
                  const emp = employees.find(e => e.id === req.employee_id);
                  return (
                    <div key={req.id} className="p-4 border rounded-xl bg-background flex flex-col justify-between gap-3 shadow-sm">
                      <div>
                        <div className="flex justify-between items-start mb-1">
                          <p className="font-semibold text-sm text-foreground">{emp ? `${emp.first_name || emp.name}` : 'Unknown Worker'}</p>
                          <span className="bg-warning/10 text-warning px-2 py-0.5 rounded text-xs font-medium border border-warning/20">Workday Change</span>
                        </div>
                        <p className="text-xs text-muted-foreground">{emp?.role || 'No role'} • Recurring: {req.day_of_week}</p>
                      </div>
                      <div className="flex gap-2 mt-1">
                        <button onClick={() => handleApprove('offDay', req.id)} className="flex-1 bg-success/10 text-success hover:bg-success/20 border border-success/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Approve</button>
                        <button onClick={() => handleReject('offDay', req.id)} className="flex-1 bg-danger/10 text-danger hover:bg-danger/20 border border-danger/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">Reject</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {isAdmin && selectedDate && (
            <div className="w-full card flex flex-col mt-8 animate-slide-up border-primary/20">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-4">
                <h2 className="section-title flex items-center gap-2 mb-0">
                  <Users className="w-5 h-5 text-primary" />
                  Available Staff ({new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })})
                </h2>
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">Preview Date:</label>
                  <button onClick={() => {
                    const d = new Date(selectedDate + 'T00:00:00');
                    d.setDate(d.getDate() - 1);
                    setSelectedDate(d.toISOString().split('T')[0]);
                  }} className="p-1.5 rounded-lg border border-border bg-background hover:bg-accent focus:outline-none transition-colors" title="Previous Day">
                    <ChevronLeft className="w-4 h-4 text-muted-foreground" />
                  </button>
                  <input 
                    type="date" 
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    className="p-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <button onClick={() => {
                    const d = new Date(selectedDate + 'T00:00:00');
                    d.setDate(d.getDate() + 1);
                    setSelectedDate(d.toISOString().split('T')[0]);
                  }} className="p-1.5 rounded-lg border border-border bg-background hover:bg-accent focus:outline-none transition-colors" title="Next Day">
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">
                {[
                  { title: "Drivers", data: availableData?.driver, bg: "bg-blue-500/10 border-blue-500/20 text-blue-700 dark:text-blue-400" },
                  { title: "Trainers", data: availableData?.trainer, bg: "bg-purple-500/10 border-purple-500/20 text-purple-700 dark:text-purple-400" },
                  { title: "Walkers", data: availableData?.walker, bg: "bg-teal-500/10 border-teal-500/20 text-teal-700 dark:text-teal-400" }
                ].map(group => (
                  <div key={group.title} className={`p-4 rounded-xl border ${group.bg}`}>
                    <h3 className="font-semibold text-sm mb-3 flex items-center justify-between">
                      {group.title}
                      <span className="bg-background/50 px-2 py-0.5 rounded-full text-xs">{group.data?.length || 0}</span>
                    </h3>
                    <ul className="space-y-2 max-h-48 overflow-y-auto pr-2 custom-scrollbar">
                      {(group.data?.length ?? 0) > 0 ? (
                        group.data!.map((emp: any) => (
                          <li key={emp.id} className="text-xs font-medium">
                            {emp.first_name || emp.name}
                          </li>
                        ))
                      ) : (
                        <li className="text-xs opacity-60 italic">None available</li>
                      )}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
      )}
      
      {myId && !isAdmin && <NotificationBanner employeeId={myId} />}

      {myId ? (
        <div className="flex flex-col gap-8 items-center max-w-2xl mx-auto w-full">
          {/* Calendar View */}
          <div className="flex flex-col w-full bg-background/50 p-6 rounded-2xl border border-border/50 shadow-sm items-center">
             <MiniCalendar 
                selectedDate={selectedDate} 
                onSelectDate={setSelectedDate} 
                onMonthChange={setCurrentMonth}
                getTileClassName={getTileClass}
             />
             <div className="flex flex-col sm:flex-row flex-wrap items-center gap-4 mt-6 text-sm font-medium text-muted-foreground w-full justify-center">
                <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-success/30 border border-success"></span> Scheduled Workday</span>
                <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-warning/30 border border-warning"></span> Pending PTO</span>
                <span className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-danger/30 border border-danger"></span> Scheduled Off</span>
             </div>
          </div>

          {/* Selected Date Details */}
          <div className="w-full">
            <div className="card h-full flex flex-col min-h-[300px]">
               <h2 className="section-title mb-4 flex items-center gap-2">
                 <CalendarDays className="w-5 h-5 text-primary" />
                 {selectedDate ? new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) : 'Select a Date'}
               </h2>

               {!selectedDate ? (
                 <div className="text-center py-10 opacity-60 flex-1 flex items-center justify-center">
                    <p className="text-sm">Click a date on the calendar to view details.</p>
                 </div>
               ) : selectedDayData ? (
                  <div className="space-y-4">
                    <span className={getStatusBadge(selectedDayData.status)}>{selectedDayData.status}</span>
                    {selectedDayData.status === 'Assigned' ? (
                      <div className="mt-4 p-4 rounded-xl bg-success/5 border border-success/20">
                        <div className="flex items-center gap-2 text-sm font-semibold text-foreground mb-3">
                         <Clock className="w-4 h-4 text-success" />
                         Assigned to: {selectedDayData.truck_name}
                        </div>
                        {selectedDayData.crew && selectedDayData.crew.length > 0 && (
                         <div className="flex items-start gap-2 mt-2 text-sm text-foreground">
                          <Users className="w-4 h-4 mt-0.5 text-success" />
                          <span>Crew: {selectedDayData.crew.map(c => `${c.role}: ${c.name}`).join(', ')}</span>
                         </div>
                        )}
                      </div>
                    ) : (selectedDayData.status === 'Pending Time Off' || selectedDayData.status === 'Pending Off (Recurring)') ? (
                      <div className="mt-4 p-6 rounded-xl bg-warning/5 border border-warning/20 flex flex-col items-center justify-center text-center space-y-2">
                        <XCircle className="w-8 h-8 text-warning/60 mb-2" />
                        <p className="text-sm font-medium text-foreground">Your request for PTO has been sent, waiting for manager approval.</p>
                        <button onClick={() => handleCancelPTO(selectedDate)} className="btn-danger mt-2">Cancel Request</button>
                      </div>
                    ) : selectedDayData.status.includes('Off') ? (
                      <div className="mt-4 p-6 rounded-xl bg-danger/5 border border-danger/20 flex flex-col items-center justify-center text-center space-y-2">
                        <XCircle className="w-8 h-8 text-danger/60 mb-2" />
                        <p className="text-sm font-medium text-foreground">You are scheduled off for this day.</p>
                        <p className="text-xs text-subtle">Enjoy your rest!</p>
                      </div>
                    ) : ( 
                      <div className="mt-4">
                        {isFutureDate ? (
                          <div className="space-y-3">
                            <p className="text-sm text-subtle mb-4">You are currently listed as Available for this date. You can request it off.</p>
                            <div className="pt-2">
                               <button onClick={() => handleRequestSpecificPTO(selectedDate)} className="btn-primary w-full shadow hover:shadow-md py-3 text-sm">
                                 Request PTO
                               </button>
                            </div>
                          </div>
                        ) : (
                          <div className="text-center py-6 text-subtle text-sm bg-accent/20 rounded-xl border border-border/50">
                            You were available but not dispatched on this day.
                          </div>
                        )}
                      </div>
                    )}
                  {/* ...existing code... */}
                 </div>
               ) : isFutureDate ? (
                  <div className="space-y-4">
                     <span className="badge bg-accent text-accent-foreground font-semibold">Available</span>
                     <div className="bg-background border border-border rounded-xl p-4 mt-4 text-center">
                         <p className="text-sm text-subtle mb-4">You have no assignments on this future date yet. You may request it off.</p>
                         <button onClick={() => handleRequestSpecificPTO(selectedDate)} className="btn-primary w-full shadow py-3">Request PTO</button>
                     </div>
                  </div>
               ) : (
                  <div className="text-center py-10 opacity-60 flex-1 flex flex-col items-center justify-center bg-accent/20 rounded-xl border border-border/50">
                    <CalendarDays className="w-10 h-10 mb-2 text-muted-foreground/50" />
                    <p className="text-sm">No assignment data available for this date.</p>
                 </div>
               )}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-12 flex flex-col items-center justify-center opacity-60 card bg-accent/20 border-dashed">
            <Users className="w-12 h-12 mb-4 text-muted-foreground/30" />
            <h3 className="text-base font-medium">No Employee Selected</h3>
            <p className="text-sm mt-1 max-w-sm">Please select your employee profile from the dropdown above to view your schedule and request time off.</p>
        </div>
      )}
    </div>
  );
};

export default Schedule;
