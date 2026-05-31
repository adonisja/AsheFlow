import React, { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import { ClipboardCheck, Loader2 } from 'lucide-react';
import TaskChecklist from '../components/TrainerDashboard/TaskChecklist';
import NotificationBanner from '../components/NotificationBanner';
import { getLocalYMD } from '../utils/date';

export default function TraineeDashboard() {
  const { user } = useAuth();
  const [trainingRecords, setTrainingRecords] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [trainerName, setTrainerName] = useState<string>('Your Trainer');
  const [traineeId, setTraineeId] = useState<string | null>(null);

  const [rating, setRating] = useState<number>(0);
  const [reviewText, setReviewText] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const meRes = await axiosClient.get('/employees/me');
        const traineeId = meRes.data.id;
        setTraineeId(traineeId);

        const res = await axiosClient.get(`/training/trainee/${traineeId}`);
        const records = res.data;
        setTrainingRecords(records);
        
        // Find today's trainer if applicable
        const todayStr = getLocalYMD();
        const tRec = records.find((r: any) => r.record_date === todayStr);
        if (tRec && tRec.trainer_id) {
           const empRes = await axiosClient.get(`/employees/${tRec.trainer_id}`);
           setTrainerName(empRes.data.name ?? '');
        }
      } catch (error) {
        console.error('Failed to fetch training records:', error);
      }
      setIsLoading(false);
    };
    fetchHistory();
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 opacity-50">
        <Loader2 className="w-8 h-8 text-primary animate-spin mb-4" />
        <p className="text-sm font-medium">Loading Trainee Dashboard...</p>
      </div>
    );
  }

  const sortedRecords = [...trainingRecords].sort((a, b) => new Date(b.record_date).getTime() - new Date(a.record_date).getTime());
  const todayRecord = sortedRecords.find(r => r.record_date === getLocalYMD());
  const pastRecords = sortedRecords.filter(r => r.record_date !== getLocalYMD());

  const handleReviewSubmit = async (recordId: string) => {
    if (!rating || !reviewText.trim()) return;
    setIsSubmitting(true);
    try {
       await axiosClient.post(`/training/record/${recordId}/review`, {
         trainer_rating: rating,
         trainee_comments: reviewText
       });
       setTrainingRecords(prev => prev.map(p => p.id === recordId ? { ...p, trainer_rating: rating, trainee_comments: reviewText } : p));
    } catch (err) {
       console.error('Failed to submit review:', err);
    }
    setIsSubmitting(false);
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">My Training Progress</h1>
          <p className="text-subtle mt-1 flex items-center gap-2">
            Stay on track and review past days.
          </p>
        </div>
      </div>
      {traineeId && <NotificationBanner employeeId={traineeId} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
           {todayRecord ? (
             <div className="space-y-6">
                <div className="bg-primary/5 border border-primary/20 p-4 rounded-xl">
                   <h2 className="font-semibold text-primary mb-1 text-sm uppercase tracking-wide">Today's Shift</h2>
                   <p className="text-foreground text-lg">Day {todayRecord.current_day_number} &middot; Paired with <span className="font-bold">{trainerName}</span></p>
                </div>
                <TaskChecklist 
                 record={todayRecord} 
                 isReadOnly={true} 
               />
             </div>
           ) : (
             <div className="card text-center text-subtle py-12">
                <div className="w-16 h-16 rounded-full bg-accent/50 mx-auto flex items-center justify-center mb-4">
                   <ClipboardCheck className="w-8 h-8 opacity-50" />
                </div>
                <p className="text-lg font-semibold mb-2 text-foreground">Waiting for Dispatch</p>
                <p className="text-sm px-2">You have not been assigned a trainer for today yet. Official tasks will appear here once the schedule is published.</p>
             </div>
           )}
           
           <div className="card">
              <h2 className="text-lg font-semibold mb-4">Training History</h2>
              {pastRecords.length === 0 ? (
                 <div className="text-center py-6 bg-accent border border-transparent border-dashed rounded-xl">
                    <p className="text-subtle text-sm">No historical records found.<br/>Your progress logs will appear here after the shift is completed.</p>
                 </div>
              ) : (
                <div className="space-y-4">
                  {pastRecords.map(record => {
                    const isClosed = new Date().getTime() > (new Date(record.record_date).getTime() + 86400000);
                    return (
                    <div key={record.id} className="border border-border rounded-xl p-4 flex flex-col gap-4">
                      <div className="flex justify-between items-center bg-accent/40 rounded-lg p-2.5">
                         <span className="font-semibold text-foreground text-sm">Day {record.current_day_number} &middot; {new Date(record.record_date).toLocaleDateString()}</span>
                         <span className="text-xs px-2 py-0.5 rounded-md bg-foreground/10 text-muted-foreground font-medium">Archived</span>
                      </div>
                      <div className="text-sm px-1 grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <span className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Topics Covered</span>
                            {record.tasks?.map((task: any) => (
                              <div key={task.id} className="flex gap-2 items-start">
                                  {task.is_completed ? <span className="text-success">&check;</span> : <span className="text-danger font-bold">&times;</span>}
                                  <span className={task.is_completed ? "text-subtle" : "text-foreground font-medium"}>{task.topic_title}</span>
                              </div>
                            ))}
                        </div>
                        <div className="bg-accent/20 p-3 rounded-lg border border-border/50">
                           <span className="font-bold text-xs uppercase tracking-wider text-muted-foreground mb-2 block">Shift Review</span>
                           {record.trainer_rating ? (
                              <div className="space-y-1">
                                 <div className="text-xl font-black text-warning">{'★'.repeat(record.trainer_rating)}{'☆'.repeat(5-record.trainer_rating)}</div>
                                 <p className="text-foreground text-xs">{record.trainee_comments}</p>
                              </div>
                           ) : isClosed ? (
                              <p className="text-xs text-subtle italic mt-2">The review window for this shift has closed.</p>
                           ) : (
                              <div className="space-y-3 mt-1">
                                 <div className="flex gap-1">
                                   {[1,2,3,4,5].map(v => (
                                     <button key={v} type="button" onClick={() => setRating(v)} className={`text-2xl ${rating >= v ? 'text-warning' : 'text-muted-foreground/30 hover:text-warning/50'}`}>★</button>
                                   ))}
                                 </div>
                                 <textarea 
                                   className="w-full text-xs p-2 bg-background border border-input rounded-md resize-none"
                                   placeholder="Add any private comments to management..."
                                   value={reviewText}
                                   onChange={e => setReviewText(e.target.value)}
                                 />
                                 <button onClick={() => handleReviewSubmit(record.id)} disabled={isSubmitting || !rating} className="bg-primary text-primary-foreground text-xs px-3 py-1.5 font-bold rounded-md disabled:opacity-50">
                                   Submit Review
                                 </button>
                              </div>
                           )}
                        </div>
                      </div>
                    </div>
                  )})}
                </div>
              )}
           </div>
        </div>

        <div className="space-y-6">
           <div className="card space-y-4 shadow-sm border-l-4 border-l-primary h-full">
              <h2 className="text-lg font-semibold border-b border-border pb-2">Shift Guidelines</h2>
              <p className="text-sm text-subtle leading-relaxed">
                  Your daily topics are populated automatically based on your progression tree. Communicate closely with your trainer.
              </p>
              <div className="bg-accent/40 p-4 rounded-xl text-sm border border-border/50 text-subtle">
                 Reviews and ratings submitted at the end of the shift are explicitly private and visible only to dispatch and management.
              </div>
           </div>
        </div>
      </div>
    </div>
  );
}