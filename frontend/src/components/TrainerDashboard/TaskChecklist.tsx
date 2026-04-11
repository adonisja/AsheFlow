import React, { useState } from 'react';
import axiosClient from '../../api/axiosClient';
import { Loader2 } from 'lucide-react';

interface TaskChecklistProps {
  record: any;
  isReadOnly: boolean;
}

export default function TaskChecklist({ record, isReadOnly }: TaskChecklistProps) {
  const [tasks, setTasks] = useState<any[]>(record.tasks || []);
  const [isUpdating, setIsUpdating] = useState<string | null>(null);

  const toggleTask = async (taskId: string, currentState: boolean) => {
    if (isReadOnly) return;
    
    setIsUpdating(taskId);
    try {
      // Assuming a patch endpoint for task completion exists
      await axiosClient.patch(`/training/task/${taskId}`, {
        is_completed: !currentState
      });
      
      setTasks(prev => prev.map(t => 
        t.id === taskId ? { ...t, is_completed: !currentState } : t
      ));
    } catch (err) {
      console.error('Failed to update task:', err);
    } finally {
      setIsUpdating(null);
    }
  };

  const debtTasks = tasks.filter(t => t.is_training_debt);
  const currentTasks = tasks.filter(t => !t.is_training_debt);

  return (
    <div className="card space-y-6">
      <div className="flex items-center justify-between border-b border-border pb-4">
         <div>
            <h2 className="text-xl font-bold text-foreground">Today's Goals</h2>
            <p className="text-sm text-subtle mt-1">Review the checklist with your trainee below.</p>
         </div>
      </div>

      {debtTasks.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between px-3 py-2 bg-danger/10 text-danger rounded-lg border border-danger/20">
             <h3 className="font-bold text-sm tracking-wide uppercase flex items-center gap-2">
                ⚠️ Training Debt
             </h3>
             <span className="text-xs font-semibold">Priority</span>
          </div>

          <div className="space-y-3">
            {debtTasks.map(task => (
              <label key={task.id} className={`flex items-start gap-4 p-3 rounded-xl border ${task.is_completed ? 'bg-accent/40 border-transparent' : 'border-danger/30 bg-danger/5'} transition-colors cursor-pointer w-full group relative`}>
                 <div className="pt-0.5 flex-shrink-0">
                    <input 
                      type="checkbox" 
                      className="w-5 h-5 rounded-md border-danger/50 text-danger bg-transparent focus:ring-danger focus:ring-offset-0 transition-all cursor-pointer accent-danger block"
                      checked={task.is_completed}
                      onChange={() => toggleTask(task.id, task.is_completed)}
                      disabled={isReadOnly || isUpdating === task.id}
                    />
                 </div>
                 <div className="flex-1 flex flex-col gap-1">
                    <span className={`font-medium ${task.is_completed ? 'line-through text-subtle' : 'text-danger'}`}>{task.topic_title}</span>
                    {task.description && <span className={`text-xs ${task.is_completed ? 'text-subtle/50' : 'text-danger/80'}`}>{task.description}</span>}
                 </div>
                 {isUpdating === task.id && (
                     <div className="absolute right-4 top-4">
                        <Loader2 className="w-4 h-4 text-danger animate-spin" />
                     </div>
                 )}
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-4">
        {currentTasks.length > 0 ? currentTasks.map(task => (
           <label key={task.id} className={`flex items-start gap-4 p-3 rounded-xl border ${task.is_completed ? 'bg-accent/40 border-transparent box-border' : 'border-border/50 hover:bg-accent/20 bg-background'} transition-colors ${!isReadOnly && 'cursor-pointer'} w-full relative`}>
                 <div className="pt-0.5 flex-shrink-0">
                    <input 
                      type="checkbox" 
                      className="w-5 h-5 rounded-md border-input bg-transparent focus:ring-primary focus:ring-offset-0 transition-all cursor-pointer"
                      checked={task.is_completed}
                      onChange={() => toggleTask(task.id, task.is_completed)}
                      disabled={isReadOnly || isUpdating === task.id}
                    />
                 </div>
                 <div className="flex flex-col flex-1 gap-1">
                    <span className={`font-medium ${task.is_completed ? 'text-subtle line-through' : 'text-foreground'}`}>{task.topic_title}</span>
                    {task.description && <span className={`text-xs ${task.is_completed ? 'text-subtle' : 'text-muted-foreground'}`}>{task.description}</span>}
                 </div>
                 {isUpdating === task.id && (
                     <div className="absolute right-4 top-4">
                        <Loader2 className="w-4 h-4 text-primary animate-spin" />
                     </div>
                 )}
           </label>
        )) : (
          <div className="text-center py-8 text-subtle text-sm">
             No specific tasks found for today's curriculum.
          </div>
        )}
      </div>

    </div>
  );
}