import React from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { Calendar, ClipboardCheck, MapPin, AlertTriangle, RefreshCw } from 'lucide-react';

export default function WorkerView() {
  const { groups } = useAuth();

  const isTrainer = groups.includes('trainer');
  const isTrainee = groups.includes('trainee');
  const isDriver = groups.includes('driver');

  const links = [
    { icon: Calendar, label: 'My Schedule', desc: 'View your weekly truck assignments', href: '/schedule' },
    { icon: ClipboardCheck, label: 'Preferences Hub', desc: 'Manage your favorites, bans & truck reassignment', href: '/preferences' },
    { icon: RefreshCw, label: 'Schedule Changes', desc: 'Request permanent changes to your working days', href: '/schedule-changes' },
    { icon: AlertTriangle, label: 'Report Incident', desc: 'Submit a field incident report', href: '/incidents' },
  ];

  if (isDriver) {
    links.splice(3, 0, { icon: MapPin, label: 'Field Ops', desc: 'Check in, departure, inspection & walker log', href: '/field-ops' });
  }

  if (isTrainee) {
    links.push({ icon: ClipboardCheck, label: 'My Training', desc: 'View progress & rate your shifts', href: '/my-training' });
  }

  if (isTrainer) {
    links.push({ icon: ClipboardCheck, label: 'Trainer Dashboard', desc: 'Manage your daily trainee tasks', href: '/trainer-dashboard' });
  }

  return (
    <div>
      <h2 className="section-title mb-4">Worker Portal</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {links.map(link => (
          <a
            key={link.label}
            href={link.href}
            className="card-elevated group flex items-center gap-4 hover:border-ring/30"
          >
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-primary/5 group-hover:bg-primary/10 transition-colors shrink-0">
              <link.icon className="w-6 h-6 text-primary" />
            </div>
            <div>
              <p className="font-semibold text-foreground">{link.label}</p>
              <p className="text-sm text-subtle">{link.desc}</p>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
