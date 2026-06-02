import React, { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { Calendar, ClipboardCheck, MapPin, AlertTriangle, RefreshCw, Truck, Anchor } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { getLocalYMD } from '../../utils/date';

export default function WorkerView() {
  const { user, groups } = useAuth();

  const isTrainer = groups.includes('trainer');
  const isTrainee = groups.includes('trainee');
  const isDriver  = groups.includes('driver');

  // Today's assignment — only fetched for drivers
  const [truckInfo, setTruckInfo]     = useState<{ truck_id: string | null; truck_name: string | null } | null>(null);
  const [dockZone, setDockZone]       = useState<string | null>(null);
  const [assignmentLoading, setAssignmentLoading] = useState(false);

  useEffect(() => {
    if (!isDriver) return;
    setAssignmentLoading(true);
    axiosClient.get('/employees/me').then(meRes => {
      const empId = meRes.data.id;
      Promise.allSettled([
        axiosClient.get(`/field-ops/crew/${empId}`).then(r => {
          setTruckInfo({ truck_id: r.data.truck_id, truck_name: r.data.truck_name });
        }),
        axiosClient.get(`/field-ops/dock-assignment/${empId}`).then(r => {
          setDockZone(r.data?.dock_zone ?? null);
        }),
      ]);
    }).catch((e) => { console.error('Failed to load driver assignment:', e); }).finally(() => setAssignmentLoading(false));
  }, [isDriver]);

  const links = [
    { icon: Calendar,       label: 'My Schedule',     desc: 'View your weekly truck assignments',                href: '/schedule' },
    { icon: ClipboardCheck, label: 'Preferences Hub',  desc: 'Manage your favorites, bans & truck reassignment', href: '/preferences' },
    { icon: RefreshCw,      label: 'Schedule Changes', desc: 'Request permanent changes to your working days',   href: '/schedule-changes' },
    { icon: AlertTriangle,  label: 'Report Incident',  desc: 'Submit a field incident report',                   href: '/incidents' },
  ];

  if (isDriver) {
    links.splice(3, 0,
      { icon: MapPin,   label: 'Field Ops',     desc: 'Check in, departure, inspection & walker log', href: '/field-ops' },
      { icon: Anchor,   label: 'Anchor Point',  desc: 'Submit or view your AP location for today',    href: '/anchor-points' },
    );
  }

  if (isTrainee) {
    links.push({ icon: ClipboardCheck, label: 'My Training',       desc: 'View progress & rate your shifts',      href: '/my-training' });
  }

  if (isTrainer) {
    links.push({ icon: ClipboardCheck, label: 'Trainer Dashboard', desc: 'Manage your daily trainee tasks',        href: '/trainer-dashboard' });
  }

  return (
    <div className="space-y-6">
      {/* Today's assignment card — drivers only */}
      {isDriver && (
        <div className="rounded-2xl border border-border bg-surface-muted/40 px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <Truck className="w-4 h-4 text-primary" />
            <p className="text-sm font-semibold text-foreground">Today's Assignment</p>
          </div>
          {assignmentLoading ? (
            <div className="h-10 rounded-xl bg-accent animate-pulse" />
          ) : truckInfo?.truck_name ? (
            <div className="flex flex-wrap items-center gap-4">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Truck</p>
                <p className="text-base font-bold text-foreground">{truckInfo.truck_name}</p>
              </div>
              {dockZone && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Dock Zone</p>
                  <p className="text-base font-bold text-foreground">{dockZone}</p>
                </div>
              )}
              {!dockZone && (
                <p className="text-xs text-muted-foreground italic">Dock zone not assigned yet</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No truck assignment for today. Check back after dispatch runs.</p>
          )}
        </div>
      )}

      {/* Quick links */}
      <div>
        <h2 className="section-title mb-4">
          {isDriver ? 'Driver Portal' : isTrainer ? 'Trainer Portal' : isTrainee ? 'Trainee Portal' : 'Worker Portal'}
        </h2>
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
    </div>
  );
}
