import React, { useState, useEffect } from 'react';
import Select from 'react-select';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { 
  getRelationships, 
  createRelationship, 
  deleteRelationship,
  getOffDays,
  createOffDay,
  deleteOffDay,
  approveOffDay,
  rejectOffDay,
  type EmployeeRelationship,
  type EmployeeOffDay
} from '../api/preferences';
import {
  getTimeOffRequests,
  createTimeOffRequest,
  deleteTimeOffRequest,
  approveTimeOffRequest,
  rejectTimeOffRequest,
  type TimeOffRequest
} from '../api/timeOffRequests';

const Preferences = () => {
   const { user, groups = [] } = useAuth();
   const isMgmt = groups.some((r: string) => ['admin', 'management'].includes(r));
   const [myId, setMyId] = useState<string>('');
   const [employees, setEmployees] = useState<any[]>([]);
   
   const [relationships, setRelationships] = useState<EmployeeRelationship[]>([]);
   const [offDays, setOffDays] = useState<EmployeeOffDay[]>([]);
   const [timeOffRequests, setTimeOffRequests] = useState<TimeOffRequest[]>([]);

   const [targetFavId, setTargetFavId] = useState<string>('');
   const [targetBanId, setTargetBanId] = useState<string>('');
   const [selectedOffDay, setSelectedOffDay] = useState<string>('Monday');
   const [selectedDate, setSelectedDate] = useState<string>('');

   useEffect(() => {
     axiosClient.get('/employees/').then(res => {
       setEmployees(res.data);
     }).catch(console.error);
   }, []);

   useEffect(() => {
     if (myId) {
       loadPreferences(myId);
     } else {
       setRelationships([]);
       setOffDays([]);
       setTimeOffRequests([]);
     }
   }, [myId]);

   const loadPreferences = async (employeeId: string) => {
     try {
       const rels = await getRelationships(employeeId);
       setRelationships(rels);
       const days = await getOffDays(employeeId);
       setOffDays(days);
       const tReqs = await getTimeOffRequests(employeeId);
       setTimeOffRequests(tReqs);
     } catch (err) {
       console.error("Error loading preferences:", err);
     }
   };

   const handleAddFav = async () => {
     if (!myId || !targetFavId) return;
     try {
       await createRelationship(myId, targetFavId, 'fav');
       loadPreferences(myId);
       setTargetFavId('');
     } catch (err) {
       console.error("Failed to add fav", err);
     }
   };

   const handleAddBan = async () => {
     if (!myId || !targetBanId) return;
     try {
       await createRelationship(myId, targetBanId, 'ban');
       loadPreferences(myId);
       setTargetBanId('');
     } catch (err) {
       console.error("Failed to add ban", err);
     }
   };

   const handleAddOffDay = async () => {
     if (!myId || !selectedOffDay) return;
     try {
       await createOffDay(myId, selectedOffDay);
       loadPreferences(myId);
       setSelectedOffDay('Monday');
     } catch (err) {
       console.error("Failed to add off day", err);
     }
   };

   const handleAddTimeOffReq = async () => {
     if (!myId || !selectedDate) return;
     try {
       await createTimeOffRequest(myId, selectedDate);
       loadPreferences(myId);
       setSelectedDate('');
     } catch (err: any) {
       console.error("Failed to add time off request", err);
       alert(err?.response?.data?.detail || 'Failed to add time off request');
     }
   };

   const handleDeleteRelationship = async (relId: string) => {
     try {
       await deleteRelationship(relId);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to delete relationship", err);
     }
   };

   const handleDeleteOffDay = async (offDayId: string) => {
     try {
       await deleteOffDay(offDayId);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to delete off day", err);
     }
   };

   const handleApproveOffDay = async (offDayId: string) => {
     try {
       await approveOffDay(offDayId);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to approve off day", err);
     }
   };

   const handleRejectOffDay = async (offDayId: string) => {
     try {
       await rejectOffDay(offDayId);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to reject off day", err);
     }
   };

   const handleDeleteTimeOffReq = async (id: string) => {
     try {
       await deleteTimeOffRequest(id);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to delete time off request", err);
     }
   };

   const handleApproveTimeOffReq = async (id: string) => {
     try {
       await approveTimeOffRequest(id);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to approve time off request", err);
     }
   };

   const handleRejectTimeOffReq = async (id: string) => {
     try {
       await rejectTimeOffRequest(id);
       loadPreferences(myId);
     } catch (err) {
       console.error("Failed to reject time off request", err);
     }
   };

   const getEmpName = (id: string) => {
     const emp = employees.find(e => e.id === id);
     return emp ? `${emp.first_name || emp.name} (${emp.role})` : id;
   };

   const employeeOptions = employees.map(emp => ({
     value: emp.id,
     label: `${emp.first_name || emp.name} (${emp.role})`
   }));

   const favs = relationships.filter(r => r.relationship_type === 'fav');
   const bans = relationships.filter(r => r.relationship_type === 'ban');

   return (
      <div className="p-8 max-w-4xl mx-auto">
         <h1 className="text-2xl font-bold mb-6">Preferences</h1>

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
           <div className="space-y-8">
             {/* FAVORITES SECTION */}
             <div className="bg-white p-6 rounded-lg shadow">
               <h2 className="text-xl font-semibold mb-4 text-green-700">My Favorites</h2>
               <div className="flex gap-4 mb-4 items-center">
                 <div className="flex-1">
                   <Select
                     options={employeeOptions.filter(o => o.value !== myId)}
                     value={employeeOptions.find(o => o.value === targetFavId) || null}
                     onChange={(selected) => setTargetFavId(selected?.value || '')}
                     placeholder="-- Select Employee --"
                     isClearable
                     className="text-left"
                   />
                 </div>
                 <button 
                   onClick={handleAddFav}
                   className="bg-green-600 text-white px-4 py-2 rounded shadow hover:bg-green-700"
                 >
                   Add Fav
                 </button>
               </div>
               <ul className="space-y-2">
                 {favs.map(f => (
                   <li key={f.id} className="flex justify-between items-center bg-gray-50 p-3 rounded border">
                     <span>{getEmpName(f.target_employee_id)}</span>
                     <button onClick={() => handleDeleteRelationship(f.id)} className="text-red-500 font-bold hover:text-red-700">X</button>
                   </li>
                 ))}
                 {favs.length === 0 && <li className="text-gray-400 italic">No favorites added.</li>}
               </ul>
             </div>

             {/* BANS SECTION */}
             <div className="bg-white p-6 rounded-lg shadow">
               <h2 className="text-xl font-semibold mb-4 text-red-700">My Bans</h2>
               <div className="flex gap-4 mb-4 items-center">
                 <div className="flex-1">
                   <Select
                     options={employeeOptions.filter(o => o.value !== myId)}
                     value={employeeOptions.find(o => o.value === targetBanId) || null}
                     onChange={(selected) => setTargetBanId(selected?.value || '')}
                     placeholder="-- Select Employee --"
                     isClearable
                     className="text-left"
                   />
                 </div>
                 <button 
                   onClick={handleAddBan}
                   className="bg-red-600 text-white px-4 py-2 rounded shadow hover:bg-red-700"
                 >
                   Add Ban
                 </button>
               </div>
               <ul className="space-y-2">
                 {bans.map(b => (
                   <li key={b.id} className="flex justify-between items-center bg-gray-50 p-3 rounded border">
                     <span>{getEmpName(b.target_employee_id)}</span>
                     <button onClick={() => handleDeleteRelationship(b.id)} className="text-red-500 font-bold hover:text-red-700">X</button>
                   </li>
                 ))}
                 {bans.length === 0 && <li className="text-gray-400 italic">No bans added.</li>}
               </ul>
             </div>

             {/* OFF DAYS SECTION */}
             <div className="bg-white p-6 rounded-lg shadow">
               <h2 className="text-xl font-semibold mb-4 text-blue-700">My Off Days</h2>
               <div className="flex gap-4 mb-4">
                 <select 
                   className="flex-1 border-gray-300 rounded-md shadow-sm p-2 border"
                   value={selectedOffDay} 
                   onChange={(e) => setSelectedOffDay(e.target.value)}
                 >
                   {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(d => (
                     <option key={d} value={d}>{d}</option>
                   ))}
                 </select>
                 <button 
                   onClick={handleAddOffDay}
                   className="bg-blue-600 text-white px-4 py-2 rounded shadow hover:bg-blue-700"
                 >
                   Add Off Day
                 </button>
               </div>
               <ul className="space-y-2">
                 {offDays.map(od => {
                   let statusColor = "bg-gray-50";
                   if (od.status === 'pending') statusColor = "bg-yellow-100 text-yellow-800";
                   if (od.status === 'approved') statusColor = "bg-green-100 text-green-800";
                   if (od.status === 'rejected') statusColor = "bg-red-100 text-red-800";

                   return (
                     <li key={od.id} className={`flex justify-between items-center p-3 rounded border ${statusColor}`}>
                       <div className="flex gap-4">
                         <span className="font-semibold">{od.day_of_week}</span>
                         <span className="text-sm italic">- {od.status}</span>
                       </div>
                       <div className="flex gap-4">
                         {isMgmt && od.status === 'pending' && (
                           <>
                             <button onClick={() => handleApproveOffDay(od.id)} className="text-green-600 font-bold hover:text-green-800">Approve</button>
                             <button onClick={() => handleRejectOffDay(od.id)} className="text-red-500 font-bold hover:text-red-700">Reject</button>
                           </>
                         )}
                         <button onClick={() => handleDeleteOffDay(od.id)} className="text-gray-500 font-bold hover:text-red-700">X</button>
                       </div>
                     </li>
                   );
                 })}
                 {offDays.length === 0 && <li className="text-gray-400 italic">No off days added.</li>}
               </ul>
             </div>

             {/* SPECIFIC TIME-OFF REQUESTS */}
             <div className="bg-white p-6 rounded-lg shadow">
               <h2 className="text-xl font-semibold mb-4 text-purple-700">Specific Request Time Off</h2>
               <div className="flex gap-4 mb-4">
                 <input 
                   type="date"
                   className="flex-1 border-gray-300 rounded-md shadow-sm p-2 border"
                   value={selectedDate} 
                   onChange={(e) => setSelectedDate(e.target.value)}
                 />
                 <button 
                   onClick={handleAddTimeOffReq}
                   className="bg-purple-600 text-white px-4 py-2 rounded shadow hover:bg-purple-700"
                 >
                   Request Exact Date
                 </button>
               </div>
               <ul className="space-y-2">
                 {timeOffRequests.map(req => {
                   let statusColor = "bg-gray-50";
                   if (req.status === 'pending') statusColor = "bg-yellow-100 text-yellow-800";
                   if (req.status === 'approved') statusColor = "bg-green-100 text-green-800";
                   if (req.status === 'rejected') statusColor = "bg-red-100 text-red-800";
                   
                   return (
                     <li key={req.id} className={`flex justify-between items-center p-3 rounded border ${statusColor}`}>
                       <div className="flex gap-4">
                         <span className="font-semibold">{req.date}</span>
                         <span className="text-sm italic">- {req.status}</span>
                       </div>
                       <div className="flex gap-4">
                         {isMgmt && req.status === 'pending' && (
                           <>
                             <button onClick={() => handleApproveTimeOffReq(req.id)} className="text-green-600 font-bold hover:text-green-800">Approve</button>
                             <button onClick={() => handleRejectTimeOffReq(req.id)} className="text-red-500 font-bold hover:text-red-700">Reject</button>
                           </>
                         )}
                         <button onClick={() => handleDeleteTimeOffReq(req.id)} className="text-gray-500 font-bold hover:text-red-700">X</button>
                       </div>
                     </li>
                   );
                 })}
                 {timeOffRequests.length === 0 && <li className="text-gray-400 italic">No specific requests.</li>}
               </ul>
             </div>
           </div>
         )}
      </div>
   );
};

export default Preferences;
