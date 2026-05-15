import React from 'react';
import { AlertCircle } from 'lucide-react';

interface Props {
  message: string | null;
  className?: string;
}

export default function ErrorBanner({ message, className }: Props) {
  if (!message) return null;
  return (
    <div className={`rounded-lg border border-danger/50 bg-danger/10 p-4 flex gap-3 text-danger${className ? ` ${className}` : ''}`}>
      <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <p className="text-sm font-medium">{message}</p>
    </div>
  );
}
