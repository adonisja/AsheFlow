import React, { useEffect, useState } from 'react';
import axiosClient from '../../api/axiosClient';
import { Users, Loader2 } from 'lucide-react';
import TaskChecklist from '../../components/TrainerDashboard/TaskChecklist';
import ManagerComments from '../../components/TrainerDashboard/ManagerComments';

export default function TraineeManagement() {
  const [allTrainees, setAllTrainees] = useState<any[]>([]);
  const [activeRecords, setActiveRecords] = useState<any[]>([]);
  const [traineeId, setTraineeId] = useState<string | null>(null);
  const [traineeName, setTraineeName] = useState<string>('');
  const [trainingRecords, setTrainingRecords] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchInit = async () => {
      try {
        const [empRes, activeRes] = await Promise.all([
          axiosClient.get('/employees/'),
          axiosClient.get('/training/daily/active')
        ]);
        const trainees = empRes.data.filter((e: any) => e.role.toLowerCase() === 'trainee');
        setAllTrainees(trainees);
        setActiveRecords(activeRes.data);
      } catch (error) {
        console.error('Failed to fetch trainee data:', error);
      }
      setIsLoading(false);
    };

    fetchInit();
  }, []);

  useEffect(() => {
    if (!traineeId) return;

    const fetchHistory = async () => {
      try {
        const res = await axiosClient.get(`/training/trainee/${traineeId}`);
        setTrainingRecords(res.data);
      } catch (error) {
        console.error('Failed to fetch training records:', error);
      }
    };
    fetchHistory();
  }, [traineeId]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 opacity-50">
        <Loader2 className="w-8 h-8 text-primary animate-spin mb-4" />
        <p className="text-sm font-medium">Loading Trainee Portal...</p>
      </div>
    );
  }

  const getLocalYMD = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };

  const sortedRecords = [...trainingRecords].sort((a, b) => new Date(b.record_date).getTime() - new Date(a.record_date).getTime());
  const todayRecord = sortedRecords.find(r => r.record_date === getLocalYMD());
  const pastRecords = sortedRecords.filter(r => r.record_date !== getLocalYMD());

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="page-title">Trainee Management</h1>
          <p className="text-subtle mt-1">Review historical assignment records and append daily directives.</p>
        </div>

        <div className="w-full md:w-72">
          {allTrainees.length === 0 ? (
            <p className="text-danger font-medium text-sm">No active trainees found in system.</p>
          ) : (
            <select 
              className="w-full border border-input rounded-xl p-2.5 bg-background focus:ring-1 focus:ring-primary focus:border-primary text-sm font-medium"
              onChange={(e) => {
                  const selected = allTrainees.find(t => t.id === e.target.value);
                  if (selected) {
                    setTraineeId(selected.id);
                    setTraineeName(selected.name || selected.first_name || 'Unknown Trainee');
                  }
              }}
              value={traineeId || ""}
            >
              <option value="" disabled>Select a Trainee...</option>
              {allTrainees.map(t => (
                  <option key={t.id} value={t.id}>{t.name || t.first_name}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {!traineeId ? (
        <div className="space-y-6">
          <h2 className="text-lg font-semibold text-foreground mb-4 border-b border-border pb-2">Today's Active Pairings</h2>
          {activeRecords.length === 0 ? (
             <div className="card text-center py-20 flex flex-col items-center justify-center bg-accent/30 border-dashed">
                <div className="w-16 h-16 rounded-full bg-background flex items-center justify-center mb-4">
                  <Users className="text-subtle w-8 h-8" />
                </div>
                <h2 className="text-xl font-semibold mb-2">No Active Pairings</h2>
                <p className="text-subtle max-w-sm mx-auto">Dispatch has not mapped any trainees to trucks today, or the sync hasn't run yet.</p>
             </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
               {activeRecords.map(act => (
                 <div key={act.record.id} className="card-elevated border hover:border-primary/50 cursor-pointer transition-colors" onClick={() => {
                     setTraineeId(act.trainee?.id);
                     setTraineeName(act.trainee?.name);
                 }}>
                    <div className="flex justify-between items-start mb-3">
                       <span className="bg-primary/10 text-primary font-bold text-xs px-2 py-1 rounded-md uppercase tracking-wider">Day {act.record.current_day_number}</span>
                       <span className="text-xs text-muted-foreground font-medium">{act.progress.completed} / {act.progress.total} Tasks</span>
                    </div>
                    <p className="font-semibold text-base mb-1">{act.trainee?.name || 'Unknown Trainee'}</p>
                    <p className="text-sm text-subtle mt-0.5">Trainer: {act.trainer?.name || 'Unassigned'}</p>
                 </div>
               ))}
            </div>
          )}
          <div className="text-center mt-8 py-8 border-t border-border">
             <p className="text-sm text-subtle italic">Select an active pairing above, or use the dropdown to view historical records.</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
             {todayRecord ? (
               <TaskChecklist 
                 record={todayRecord} 
                 isReadOnly={true} 
               />
             ) : (
               <div className="card text-center text-subtle py-12 border-dashed border-2 bg-accent/30">
                  <p className="text-lg font-medium mb-1 text-foreground">No Official Dispatch Today</p>
                  <p className="text-sm">They are not paired via active dispatch for today, or dispatch hasn't run yet.</p>
               </div>
             )}
             
             <div className="card">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-lg font-semibold">Trainee Progress Log</h2>
                    <span className="text-sm px-2 py-1 bg-primary/10 text-primary font-medium rounded-lg">
                        {pastRecords.length} Completed Days
                    </span>
                </div>
                {pastRecords.length === 0 ? (
                   <div className="text-center py-6 bg-accent/50 border border-border border-dashed rounded-xl">
                      <p className="text-subtle text-sm">No historical records documented yet.</p>
                   </div>
                ) : (
                  <div className="space-y-4">
                    {pastRecords.map(record => (
                      <div key={record.id} className="border border-border rounded-xl p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center bg-accent/40 rounded-lg p-2.5">
                           <span className="font-semibold text-foreground text-sm">Day {record.current_day_number} &middot; {new Date(record.record_date).toLocaleDateString()}</span>
                           <span className="text-xs px-2 py-0.5 rounded-md bg-foreground/10 text-muted-foreground font-medium">Locked</span>
                        </div>
                        <div className="text-sm space-y-2.5 px-1 py-1">
                          {record.tasks?.map((task: any) => (
                             <div key={task.id} className="flex gap-2.5 items-start">
                                {task.is_completed ? <span className="text-success text-base flex-shrink-0">&check;</span> : <span className="text-danger flex-shrink-0 font-bold">&times;</span>}
                                <span className={task.is_completed ? "text-subtle strike line-through" : "text-foreground font-medium"}>{task.topic_title}</span>
                             </div>
                          ))}
                        </div>
                        {record.trainer_rating && (
                          <div className="mt-2 bg-accent/20 p-3 rounded-lg border border-border/50 text-xs">
                             <span className="font-bold uppercase tracking-wider text-muted-foreground block mb-1">Trainee Review</span>
                             <div className="text-sm text-warning font-black">{'★'.repeat(record.trainer_rating)}{'☆'.repeat(5-record.trainer_rating)}</div>
                             {record.trainee_comments && <p className="text-foreground mt-1">{record.trainee_comments}</p>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
             </div>
          </div>

          <div className="space-y-6">
             <ManagerComments 
               record={todayRecord} 
               traineeId={traineeId}
             />
          </div>
        </div>
      )}
    </div>
  );
}