import React, { useState } from 'react';
import axiosClient from '../../api/axiosClient';
import { useAuth } from '../../contexts/AuthContext';
import { Loader2, MessageSquare, Save } from 'lucide-react';

interface ManagerCommentsProps {
  record: any;
  traineeId: string;
}

export default function ManagerComments({ record, traineeId }: ManagerCommentsProps) {
  const { groups } = useAuth();
  const [commentInput, setCommentInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');
  
  const isManager = groups.includes('management') || groups.includes('admin');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!commentInput.trim() || !isManager) return;
    
    setIsSubmitting(true);
    setSuccessMsg('');
    try {
      await axiosClient.post(`/training/trainee/${traineeId}/manager-comments`, {
        comments: commentInput
      });
      setSuccessMsg('Note added successfully.');
      setCommentInput('');
      // Usually trigger a re-fetch, but for short-circuiting we just show success message mapping it manually or reloading
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      console.error('Failed to add note:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="card space-y-4 shadow-sm border-l-4 border-l-info h-full">
       <div className="flex items-center gap-2 border-b border-border pb-3">
          <MessageSquare className="w-5 h-5 text-info" />
          <h2 className="text-lg font-semibold text-foreground">Management Notes</h2>
       </div>

       {record?.manager_comments ? (
         <div className="bg-info/5 p-4 rounded-xl border border-info/20 text-sm whitespace-pre-wrap leading-relaxed space-y-1">
            <span className="font-semibold text-info mb-1 uppercase tracking-tight block text-xs">Directives for Today</span>
            <span className="text-foreground">{record.manager_comments}</span>
         </div>
       ) : (
         <div className="text-sm text-subtle italic py-2">
            No specific management notes for today's assignment.
         </div>
       )}

       {isManager && !record?.is_locked && (
         <form onSubmit={handleSubmit} className="pt-4 border-t border-border mt-4">
           <label className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
             Add Trainee Note
           </label>
           <textarea 
             className="w-full bg-background border border-input rounded-xl p-3 text-sm focus:ring-1 focus:ring-info focus:border-info transition-colors min-h-[100px] resize-y"
             placeholder="Add specific instructions for the trainer..."
             value={commentInput}
             onChange={(e) => setCommentInput(e.target.value)}
             disabled={isSubmitting}
           />
           <button 
             type="submit" 
             disabled={!commentInput.trim() || isSubmitting}
             className="w-full mt-3 bg-info text-info-foreground font-semibold px-4 py-2.5 rounded-xl hover:bg-info/90 transition-colors shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
           >
             {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
             {isSubmitting ? 'Saving...' : 'Append Note'}
           </button>
           
           {successMsg && <p className="text-xs text-success text-center mt-2 font-medium">{successMsg}</p>}
         </form>
       )}
    </div>
  );
}