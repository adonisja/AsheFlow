import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import axiosClient from '../api/axiosClient';
import { getSchedule, createOffDay } from '../api/preferences';
import { createTimeOffRequest } from '../api/timeOffRequests';
import { CalendarDays, Clock, Users, ChevronLeft, ChevronRight } from 'lucide-react';

export interface ScheduleDay {
  date: string;
  status: string;
  truck_name: string | null;
  crew: string[] | null;
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
  const [employees, setEmployees] = useState<any[]>([]);
  const [myId, setMyId] = useState<string>('');
  const [scheduleData, setScheduleData] = useState<ScheduleDay[]>([]);
  const [weekOffset, setWeekOffset] = useState<number>(0);

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

const fetchSchedule = async (employeeId: string, offset: number) => {
    if (!employeeId) return;
    const today = new Date();
    today.setDate(today.getDate() + offset * 7); // Apply week offset
    const startDate = new Date(today);
    startDate.setDate(today.getDate() - today.getDay());
    const endDate = new Date(startDate);
    endDate.setDate(startDate.getDate() + 6);

    const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    
    try {
      const data = await getSchedule(employeeId, fmt(startDate), fmt(endDate));
      setScheduleData(data);
    } catch (err) {
      console.error("Failed to load schedule", err);
    }
  };

  useEffect(() => { fetchSchedule(myId, weekOffset); }, [myId, weekOffset]);

  const handleRequestRecurringOffDay = async (dateStr: string) => {
    if (!myId) return;
    const parts = dateStr.split('-');
    const dateObj = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    try {
      await createOffDay(myId, days[dateObj.getDay()]);
      await fetchSchedule(myId, weekOffset);
    } catch (err) { console.error("Failed to request recurring off day", err); }
  };

  const handleRequestSpecificPTO = async (dateStr: string) => {
    if (!myId) return;
    try {
      await createTimeOffRequest(myId, dateStr);
      await fetchSchedule(myId, weekOffset);
    } catch (err: any) {
      console.error("Failed to request specific PTO", err);
      if (err.response?.data?.detail) alert(err.response.data.detail);
    }
  };

  const todayStr = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  })();

  const employeeOptions = employees.map(emp => ({
    value: emp.id,
    label: `${emp.first_name || emp.name} (${emp.role})`
  }));

  const getStatusBadge = (status: string) => {
    if (status === 'Off (Recurring)' || status === 'Time Off') return 'badge-success';
    if (status === 'Pending Off (Recurring)' || status === 'Pending Time Off') return 'badge-warning';
    if (status === 'Assigned') return 'badge-info';
    return 'badge bg-accent text-muted-foreground';
  };

  const daysOfWeek = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">My Schedule</h1>
      
      <div className="card flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex-1">
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
        {myId && (
          <div className="flex items-center gap-2 pt-6">
            <button 
              onClick={() => setWeekOffset(prev => prev - 1)}
              className="btn-secondary px-3 py-2 flex items-center"
            >
              <ChevronLeft className="w-4 h-4 mr-1" />
              Prev
            </button>
            <button
              onClick={() => setWeekOffset(0)}
              className="btn-secondary px-4 py-2 font-medium"
              disabled={weekOffset === 0}
            >
              Current Week
            </button>
            <button 
              onClick={() => setWeekOffset(prev => prev + 1)}
              className="btn-secondary px-3 py-2 flex items-center"
            >
              Next
              <ChevronRight className="w-4 h-4 ml-1" />
            </button>
          </div>
        )}
      </div>

      {myId && (
        <div className="space-y-3">
          {scheduleData.map((item, index) => {
            const parts = item.date.split('-');
            const displayDate = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
            const isFutureOrToday = item.date >= todayStr;
            const dayName = daysOfWeek[displayDate.getDay()];
            const isToday = item.date === todayStr;

            return (
              <div 
                key={index} 
                className={`card-elevated transition-all ${isToday ? 'ring-2 ring-primary/20' : ''}`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="space-y-2">
                    <div className="flex items-center gap-3">
                      <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
                        <CalendarDays className="w-4 h-4 text-muted-foreground" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-foreground">
                          {dayName}
                          {isToday && <span className="ml-2 text-xs text-muted-foreground font-normal">Today</span>}
                        </h3>
                        <p className="text-xs text-muted-foreground">
                          {displayDate.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
                        </p>
                      </div>
                    </div>
                    
                    <span className={getStatusBadge(item.status)}>{item.status}</span>

                    {item.status === 'Assigned' && (
                      <div className="mt-2 p-3 rounded-xl bg-info/5 border border-info/10">
                        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                          <Clock className="w-3.5 h-3.5 text-info" />
                          Truck: {item.truck_name}
                        </div>
                        {item.crew && item.crew.length > 0 && (
                          <div className="flex items-start gap-2 mt-2 text-sm text-muted-foreground">
                            <Users className="w-3.5 h-3.5 mt-0.5 text-info" />
                            <span>{item.crew.join(', ')}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {item.status === 'Available' && isFutureOrToday && (
                    <div className="flex flex-col gap-2 sm:items-end">
                      <button 
                        onClick={() => handleRequestSpecificPTO(item.date)}
                        className="btn-primary text-xs px-4 py-2"
                      >
                        Request PTO
                      </button>
                      <button 
                        onClick={() => handleRequestRecurringOffDay(item.date)}
                        className="btn-secondary text-xs px-4 py-2"
                      >
                        Every {dayName} Off
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          
          {scheduleData.length === 0 && (
            <div className="card text-center py-12">
              <CalendarDays className="w-10 h-10 mx-auto text-muted-foreground/40 mb-3" />
              <p className="text-subtle">No schedule data available for this week.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Schedule;
