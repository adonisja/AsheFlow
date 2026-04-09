import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import axiosClient from '../api/axiosClient';
import { getSchedule, createOffDay } from '../api/preferences';
import { createTimeOffRequest } from '../api/timeOffRequests';

export interface ScheduleDay {
  date: string;
  status: string;
  truck_name: string | null;
  crew: string[] | null;
}

const Schedule = () => {
    const [employees, setEmployees] = useState<any[]>([]);
    const [myId, setMyId] = useState<string>('');
    const [scheduleData, setScheduleData] = useState<ScheduleDay[]>([]);

    useEffect(() => {
        axiosClient.get('/employees/').then(res => {
            setEmployees(res.data);
        }).catch(console.error);
    }, []);

    const fetchSchedule = async (employeeId: string) => {
        if (!employeeId) return;
        
        const today = new Date();
        const currentDayOfWeek = today.getDay(); // 0 is Sunday, 6 is Saturday
        
        // Find Sunday of the current week (or keep it if today is Sunday)
        const startDate = new Date(today);
        startDate.setDate(today.getDate() - currentDayOfWeek);
        
        // Next Saturday
        const endDate = new Date(startDate);
        endDate.setDate(startDate.getDate() + 6);

        // Format to YYYY-MM-DD to avoid timezone shifts
        // We use local offsets because we want today according to user's computer
        const formatYMD = (d: Date) => {
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        };

        const startDateStr = formatYMD(startDate);
        const endDateStr = formatYMD(endDate);

        try {
            const data = await getSchedule(employeeId, startDateStr, endDateStr);
            setScheduleData(data);
        } catch (err) {
            console.error("Failed to load schedule", err);
        }
    };

    useEffect(() => {
        fetchSchedule(myId);
    }, [myId]);

    const handleRequestRecurringOffDay = async (dateStr: string) => {
        if (!myId) return;
        const parts = dateStr.split('-');
        const dateObj = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const dayOfWeek = days[dateObj.getDay()]; 

        try {
            await createOffDay(myId, dayOfWeek);
            await fetchSchedule(myId);
        } catch (err) {
            console.error("Failed to request recurring off day", err);
        }
    };

    const handleRequestSpecificPTO = async (dateStr: string) => {
        if (!myId) return;
        try {
            await createTimeOffRequest(myId, dateStr);
            await fetchSchedule(myId);
        } catch (err: any) {
            console.error("Failed to request specific PTO", err);
            if (err.response?.data?.detail) {
                alert(err.response.data.detail);
            }
        }
    };

    // calculate today's date in YYYY-MM-DD for comparison
    const formatedTodayStr = (() => {
        const d = new Date();
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    })();

    const employeeOptions = employees.map(emp => ({
        value: emp.id,
        label: `${emp.first_name || emp.name} (${emp.role})`
    }));

    return (
        <div className="p-8 max-w-4xl mx-auto">
            <h1 className="text-2xl font-bold mb-6">My Schedule</h1>
            
            <div className="mb-8 p-4 bg-white rounded-lg shadow">
                <label className="block text-sm font-medium text-gray-700 mb-2">Select Your Identity (For Demo)</label>
                <Select
                    options={employeeOptions}
                    value={employeeOptions.find(o => o.value === myId) || null}
                    onChange={(selected) => setMyId(selected?.value || '')}
                    placeholder="-- Choose Employee --"
                    isClearable
                    className="w-full text-left"
                />
            </div>

            {myId && (
                <div className="space-y-4">
                    {scheduleData.map((item, index) => {
                        const parts = item.date.split('-');
                        const displayDateObj = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
                        const isFutureOrToday = item.date >= formatedTodayStr;

                        const daysOfWeekLocal = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
                        const dayOfWeekStr = daysOfWeekLocal[displayDateObj.getDay()];

                        let statusColor = "text-gray-600";
                        if (item.status === 'Off (Recurring)' || item.status === 'Time Off') statusColor = "text-green-600 font-bold";
                        if (item.status === 'Pending Off (Recurring)' || item.status === 'Pending Time Off') statusColor = "text-yellow-600 font-bold";
                        if (item.status === 'Assigned') statusColor = "text-blue-600 font-bold";

                        return (
                            <div key={index} className="bg-white p-4 rounded-lg shadow flex flex-col sm:flex-row justify-between items-start sm:items-center border">
                                <div>
                                    <h3 className="text-lg font-semibold text-gray-800">
                                        {dayOfWeekStr}, {displayDateObj.toLocaleDateString()}
                                    </h3>
                                    <p className={`text-sm ${statusColor} mt-1`}>Status: {item.status}</p>
                                    
                                    {item.status === 'Assigned' && (
                                        <div className="mt-3 p-3 bg-blue-50 rounded border border-blue-100">
                                            <p className="font-semibold text-blue-800">Truck: {item.truck_name}</p>
                                            {item.crew && item.crew.length > 0 && (
                                                <ul className="list-disc list-inside mt-1 text-sm text-blue-700">
                                                    {item.crew.map((member, idx) => (
                                                        <li key={idx}>{member}</li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    )}
                                </div>

                                <div className="mt-4 sm:mt-0 flex flex-col gap-2">
                                    {item.status === 'Available' && isFutureOrToday && (
                                        <>
                                            <button 
                                                onClick={() => handleRequestSpecificPTO(item.date)}
                                                className="bg-blue-600 text-white px-4 py-2 rounded shadow hover:bg-blue-700 transition text-sm"
                                            >
                                                Request Date Off (PTO)
                                            </button>
                                            <button 
                                                onClick={() => handleRequestRecurringOffDay(item.date)}
                                                className="bg-indigo-100 text-indigo-800 px-4 py-2 rounded shadow hover:bg-indigo-200 transition text-sm border border-indigo-200"
                                            >
                                                Request Every {dayOfWeekStr} Off
                                            </button>
                                        </>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                    
                    {scheduleData.length === 0 && (
                        <p className="text-gray-500 italic">No schedule data available for this week.</p>
                    )}
                </div>
            )}
        </div>
    );
};

export default Schedule;