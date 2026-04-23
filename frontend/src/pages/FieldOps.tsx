import React, { useState, useEffect, useRef } from 'react';
import { Camera, LogIn, LogOut, Star, Home, ClipboardCheck, CheckCircle2, XCircle, Gauge, MapPin, AlertTriangle, Fuel, BarChart2, TrendingUp, Award } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Read a File as a base64 data-URI string */
const fileToDataUrl = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

// Human-readable labels for inspection items
const ITEM_LABELS: Record<string, string> = {
  tires: 'Tires',
  tyres: 'Tires', // legacy key fallback
  lights: 'Lights',
  mirrors: 'Mirrors',
  brakes: 'Brakes',
  fluids: 'Fluids',
  horn: 'Horn',
  wipers: 'Wipers',
  seatbelts: 'Seatbelts',
  cargo_security: 'Cargo Security',
  fuel_level: 'Fuel Level',
};

// ---------------------------------------------------------------------------
// Vehicle Inspection Panel
// ---------------------------------------------------------------------------
function InspectionPanel({ employeeId }: { employeeId: string }) {
  const [items, setItems] = useState<string[]>([]);
  const [results, setResults] = useState<Record<string, boolean | null>>({});
  const [notes, setNotes] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [submittedData, setSubmittedData] = useState<{ has_failures: boolean; items: Record<string, boolean>; notes?: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!employeeId) return;

    // Load checklist items and check if already submitted today
    Promise.all([
      axiosClient.get('/field-ops/inspection/items'),
      axiosClient.get(`/field-ops/inspection/${employeeId}`),
    ]).then(([itemsRes, historyRes]) => {
      const canonical: string[] = itemsRes.data.items ?? [];
      setItems(canonical);
      setResults(Object.fromEntries(canonical.map(k => [k, null])));

      const today = todayStr();
      const todayRecord = historyRes.data.find((r: any) => r.date === today);
      if (todayRecord) {
        setSubmitted(true);
        setSubmittedData({ has_failures: todayRecord.has_failures, items: todayRecord.items, notes: todayRecord.notes });
      }
    }).catch(console.error);
  }, [employeeId]);

  const setResult = (item: string, pass: boolean) => {
    setResults(prev => ({ ...prev, [item]: prev[item] === pass ? null : pass }));
  };

  const allAnswered = items.length > 0 && items.every(k => results[k] !== null);

  const handleSubmit = async () => {
    if (!allAnswered) return alert('Please mark every item as pass or fail before submitting.');
    setLoading(true);
    try {
      const payload = {
        driver_id: employeeId,
        date: todayStr(),
        items: results as Record<string, boolean>,
        notes: notes.trim() || null,
      };
      await axiosClient.post('/field-ops/inspection', payload);
      const has_failures = Object.values(results).some(v => v === false);
      setSubmitted(true);
      setSubmittedData({ has_failures, items: results as Record<string, boolean>, notes: notes.trim() || undefined });
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Inspection submission failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <ClipboardCheck className="w-4 h-4 text-primary" />
        </div>
        <h2 className="section-title">Pre-Trip Inspection</h2>
      </div>

      {submitted && submittedData ? (
        <div className={`p-4 rounded-xl border text-sm space-y-3 ${submittedData.has_failures ? 'bg-destructive/10 border-destructive/30' : 'bg-success/10 border-success/30'}`}>
          <p className={`font-semibold ${submittedData.has_failures ? 'text-destructive' : 'text-success'}`}>
            {submittedData.has_failures ? 'Inspection submitted — failures noted. Report to management.' : 'Inspection complete — all items passed.'}
          </p>
          <div className="grid grid-cols-2 gap-1">
            {Object.entries(submittedData.items).map(([k, pass]) => (
              <div key={k} className="flex items-center gap-1.5 text-xs text-foreground">
                {pass
                  ? <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
                  : <XCircle className="w-3.5 h-3.5 text-destructive shrink-0" />}
                <span>{ITEM_LABELS[k] ?? k}</span>
              </div>
            ))}
          </div>
          {submittedData.notes && (
            <p className="text-xs text-subtle italic">Notes: {submittedData.notes}</p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-subtle">Complete this checklist before departing. Tap Pass or Fail for each item.</p>
          <div className="divide-y divide-border">
            {items.map(item => {
              const val = results[item];
              return (
                <div key={item} className="flex items-center justify-between py-2.5">
                  <span className="text-sm font-medium text-foreground">{ITEM_LABELS[item] ?? item}</span>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setResult(item, true)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-colors ${val === true ? 'bg-success text-white border-success' : 'border-border text-subtle hover:border-success hover:text-success'}`}
                    >
                      Pass
                    </button>
                    <button
                      onClick={() => setResult(item, false)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-colors ${val === false ? 'bg-danger text-foreground border-danger' : 'border-border text-subtle hover:border-danger hover:text-danger'}`}
                    >
                      Fail
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Additional notes (optional)…"
            rows={2}
            className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
          />
          <button
            onClick={handleSubmit}
            disabled={!allAnswered || loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Submitting…' : 'Submit Inspection'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Check-In Panel
// ---------------------------------------------------------------------------
function CheckInPanel({ employeeId }: { employeeId: string }) {
  const [checkedIn, setCheckedIn] = useState(false);
  const [checkedInAt, setCheckedInAt] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Check if already checked in today
  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/check-in/${employeeId}`)
      .then(res => {
        const today = todayStr();
        const todayRecord = res.data.find((r: any) => r.date === today);
        if (todayRecord) {
          setCheckedIn(true);
          if (todayRecord.photo_url) setPreviewUrl(todayRecord.photo_url);
          if (todayRecord.checked_in_at) {
            const t = new Date(todayRecord.checked_in_at);
            setCheckedInAt(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
          }
        }
      })
      .catch(console.error);
  }, [employeeId]);

  const handleCapture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    const encoded = await fileToDataUrl(file);
    setDataUrl(encoded);
  };

  const handleCheckIn = async () => {
    if (!dataUrl) return alert('Please take a photo before checking in.');
    setLoading(true);
    try {
      const res = await axiosClient.post('/field-ops/check-in', {
        employee_id: employeeId,
        date: todayStr(),
        photo_url: dataUrl,
      });
      setCheckedIn(true);
      if (res.data.checked_in_at) {
        const t = new Date(res.data.checked_in_at);
        setCheckedInAt(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Check-in failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <LogIn className="w-4 h-4 text-success" />
        </div>
        <h2 className="section-title">Check-In</h2>
      </div>

      {checkedIn ? (
        <div className="p-6 rounded-xl bg-success/10 border border-success/30 text-center space-y-3">
          <p className="text-sm font-semibold text-success">You are checked in for today.</p>
          {checkedInAt && (
            <p className="text-xs text-subtle">Checked in at <span className="font-medium text-foreground">{checkedInAt}</span></p>
          )}
          {previewUrl && (
            <img src={previewUrl} alt="Check-in" className="mx-auto rounded-xl max-h-48 object-cover border border-success/20" />
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-subtle">Take a photo to confirm your attendance at the start of your shift.</p>
          <label className="flex items-center justify-center gap-2 w-full py-4 border-2 border-dashed border-border rounded-xl cursor-pointer hover:border-primary/50 transition-colors text-sm text-muted-foreground">
            <Camera className="w-4 h-4" />
            {previewUrl ? 'Retake Photo' : 'Open Camera / Select Photo'}
            <input ref={inputRef} type="file" accept="image/*" capture="environment" onChange={handleCapture} className="hidden" />
          </label>
          {previewUrl && (
            <img src={previewUrl} alt="Preview" className="mx-auto rounded-xl max-h-48 object-cover border border-border" />
          )}
          <button
            onClick={handleCheckIn}
            disabled={!dataUrl || loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Checking in…' : 'Confirm Check-In'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Departure Panel
// ---------------------------------------------------------------------------
function DeparturePanel({ employeeId }: { employeeId: string }) {
  const [departed, setDeparted] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/departure/${employeeId}`)
      .then(res => {
        const today = todayStr();
        const todayRecord = res.data.find((r: any) => r.date === today);
        if (todayRecord) {
          setDeparted(true);
          if (todayRecord.itinerary_photo_url) setPreviewUrl(todayRecord.itinerary_photo_url);
        }
      })
      .catch(console.error);
  }, [employeeId]);

  const handleCapture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPreviewUrl(URL.createObjectURL(file));
    setDataUrl(await fileToDataUrl(file));
  };

  const handleDepart = async () => {
    if (!dataUrl) return alert('Please photograph the itinerary before departing.');
    setLoading(true);
    try {
      await axiosClient.post('/field-ops/departure', {
        employee_id: employeeId,
        date: todayStr(),
        itinerary_photo_url: dataUrl,
      });
      setDeparted(true);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Departure record failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <LogOut className="w-4 h-4 text-primary" />
        </div>
        <h2 className="section-title">Departure</h2>
      </div>

      {departed ? (
        <div className="p-6 rounded-xl bg-primary/10 border border-primary/30 text-center space-y-3">
          <p className="text-sm font-semibold text-primary">Departure recorded. Safe travels!</p>
          {previewUrl && (
            <img src={previewUrl} alt="Itinerary" className="mx-auto rounded-xl max-h-48 object-cover border border-primary/20" />
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-subtle">Photograph today's route itinerary before you leave.</p>
          <label className="flex items-center justify-center gap-2 w-full py-4 border-2 border-dashed border-border rounded-xl cursor-pointer hover:border-primary/50 transition-colors text-sm text-muted-foreground">
            <Camera className="w-4 h-4" />
            {previewUrl ? 'Retake Photo' : 'Photograph Itinerary'}
            <input type="file" accept="image/*" capture="environment" onChange={handleCapture} className="hidden" />
          </label>
          {previewUrl && (
            <img src={previewUrl} alt="Preview" className="mx-auto rounded-xl max-h-48 object-cover border border-border" />
          )}
          <button
            onClick={handleDepart}
            disabled={!dataUrl || loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Recording…' : 'Confirm Departure'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Return / End-of-Day Panel
// ---------------------------------------------------------------------------
function ReturnPanel({ employeeId }: { employeeId: string }) {
  const [departed, setDeparted] = useState(false);
  const [returned, setReturned] = useState(false);
  const [returnedAt, setReturnedAt] = useState<string | null>(null);
  const [departedAt, setDepartedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/departure/${employeeId}`)
      .then(res => {
        const today = todayStr();
        const todayRecord = res.data.find((r: any) => r.date === today);
        if (todayRecord) {
          setDeparted(true);
          if (todayRecord.departed_at) {
            const t = new Date(todayRecord.departed_at);
            setDepartedAt(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
          }
          if (todayRecord.returned_at) {
            setReturned(true);
            const t = new Date(todayRecord.returned_at);
            setReturnedAt(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
          }
        }
      })
      .catch(console.error);
  }, [employeeId]);

  const handleReturn = async () => {
    setLoading(true);
    try {
      const res = await axiosClient.post(`/field-ops/return/${employeeId}`);
      setReturned(true);
      if (res.data.returned_at) {
        const t = new Date(res.data.returned_at);
        setReturnedAt(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to record return.');
    } finally {
      setLoading(false);
    }
  };

  // Don't render until the driver has departed
  if (!departed) return null;

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <Home className="w-4 h-4 text-success" />
        </div>
        <h2 className="section-title">End of Day — Return</h2>
      </div>

      {returned ? (
        <div className="p-6 rounded-xl bg-success/10 border border-success/30 text-center space-y-2">
          <p className="text-sm font-semibold text-success">You have returned for the day.</p>
          {returnedAt && departedAt && (
            <p className="text-xs text-subtle">
              Departed <span className="font-medium text-foreground">{departedAt}</span>
              {' · '}
              Returned <span className="font-medium text-foreground">{returnedAt}</span>
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-subtle">
            Confirm you are back at the yard to close out your shift.
            {departedAt && (
              <> You departed at <span className="font-medium text-foreground">{departedAt}</span>.</>
            )}
          </p>
          <button
            onClick={handleReturn}
            disabled={loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Recording…' : 'Confirm Return'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unit conversion helpers — DB always stores miles and gallons (imperial)
// ---------------------------------------------------------------------------
const KM_PER_MILE = 1.60934;
const L_PER_GAL   = 3.78541;

// Display value: DB miles → display unit
const toDisplay = (miles: number, unit: 'imperial' | 'metric') =>
  unit === 'metric' ? parseFloat((miles * KM_PER_MILE).toFixed(1)) : miles;

// Display value → DB miles (for writing)
const toMiles = (val: number, unit: 'imperial' | 'metric') =>
  unit === 'metric' ? parseFloat((val / KM_PER_MILE).toFixed(2)) : val;

// Display fuel: DB gallons → display unit
const fuelToDisplay = (gal: number, unit: 'imperial' | 'metric') =>
  unit === 'metric' ? parseFloat((gal * L_PER_GAL).toFixed(2)) : gal;

// Display fuel → DB gallons
const fuelToGallons = (val: number, unit: 'imperial' | 'metric') =>
  unit === 'metric' ? parseFloat((val / L_PER_GAL).toFixed(2)) : val;

// ---------------------------------------------------------------------------
// Fuel / Mileage Log Panel
// ---------------------------------------------------------------------------
function FuelMileagePanel({ employeeId }: { employeeId: string }) {
  type LogRecord = {
    id: string;
    odometer_start: number;
    odometer_end: number | null;
    fuel_added: number | null;
    notes: string | null;
  };

  const [log, setLog] = useState<LogRecord | null>(null);
  const [startOdo, setStartOdo] = useState('');
  const [endOdo, setEndOdo] = useState('');
  const [fuelAdded, setFuelAdded] = useState('');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [unit, setUnit] = useState<'imperial' | 'metric'>('imperial');

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/fuel-log/${employeeId}`)
      .then(res => {
        const today = todayStr();
        const todayRecord = res.data.find((r: any) => r.date === today);
        if (todayRecord) setLog(todayRecord);
      })
      .catch(console.error);
  }, [employeeId]);

  // When the driver flips units, convert displayed input values automatically
  const handleUnitToggle = (newUnit: 'imperial' | 'metric') => {
    if (newUnit === unit) return;
    if (startOdo) {
      const miles = toMiles(parseFloat(startOdo), unit);
      setStartOdo(String(toDisplay(miles, newUnit)));
    }
    if (endOdo) {
      const miles = toMiles(parseFloat(endOdo), unit);
      setEndOdo(String(toDisplay(miles, newUnit)));
    }
    if (fuelAdded) {
      const gal = fuelToGallons(parseFloat(fuelAdded), unit);
      setFuelAdded(String(fuelToDisplay(gal, newUnit)));
    }
    setUnit(newUnit);
  };

  const distUnit = unit === 'metric' ? 'km' : 'mi';
  const fuelUnit = unit === 'metric' ? 'L' : 'gal';

  const handleStartShift = async () => {
    const displayVal = parseFloat(startOdo);
    if (isNaN(displayVal) || displayVal < 0) return alert('Enter a valid odometer reading.');
    const miles = toMiles(displayVal, unit);
    setLoading(true);
    try {
      const res = await axiosClient.post('/field-ops/fuel-log', {
        driver_id: employeeId,
        date: todayStr(),
        odometer_start: miles,  // always stored as miles
      });
      setLog(res.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to save fuel log.');
    } finally {
      setLoading(false);
    }
  };

  const handleEndShift = async () => {
    const displayEnd = parseFloat(endOdo);
    const milesEnd = toMiles(displayEnd, unit);
    if (isNaN(milesEnd) || milesEnd < (log?.odometer_start ?? 0)) {
      return alert('End odometer must be ≥ start odometer.');
    }
    setLoading(true);
    try {
      const res = await axiosClient.patch(`/field-ops/fuel-log/${employeeId}`, {
        odometer_end: milesEnd,
        fuel_added: fuelAdded ? fuelToGallons(parseFloat(fuelAdded), unit) : null,
        notes: notes.trim() || null,
      });
      setLog(res.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update fuel log.');
    } finally {
      setLoading(false);
    }
  };

  // Display values from DB (always stored in miles/gallons)
  const displayStart = log ? toDisplay(log.odometer_start, unit) : null;
  const displayEnd   = log?.odometer_end != null ? toDisplay(log.odometer_end, unit) : null;
  const displayDist  = displayStart != null && displayEnd != null ? displayEnd - displayStart : null;
  const displayFuel  = log?.fuel_added != null ? fuelToDisplay(log.fuel_added, unit) : null;
  const endOfDayDone = log?.odometer_end != null;

  // Unit toggle pill — shown in panel header
  const UnitToggle = () => (
    <div className="flex items-center gap-1 ml-auto bg-accent rounded-lg p-0.5">
      {(['imperial', 'metric'] as const).map(u => (
        <button
          key={u}
          onClick={() => handleUnitToggle(u)}
          className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${
            unit === u ? 'bg-primary text-primary-foreground shadow-sm' : 'text-subtle hover:text-foreground'
          }`}
        >
          {u === 'imperial' ? 'mi / gal' : 'km / L'}
        </button>
      ))}
    </div>
  );

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent shrink-0">
          <Gauge className="w-4 h-4 text-primary" />
        </div>
        <h2 className="section-title">Fuel & Mileage Log</h2>
        <UnitToggle />
      </div>

      {!log ? (
        <div className="space-y-3">
          <p className="text-sm text-subtle">Record the truck's odometer reading before departing.</p>
          <div>
            <label className="block text-xs text-subtle mb-1">Odometer Start ({distUnit})</label>
            <input
              type="number"
              min={0}
              value={startOdo}
              onChange={e => setStartOdo(e.target.value)}
              placeholder={unit === 'imperial' ? 'e.g. 28120' : 'e.g. 45230'}
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <button
            onClick={handleStartShift}
            disabled={!startOdo || loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Saving…' : 'Log Start Odometer'}
          </button>
        </div>
      ) : endOfDayDone ? (
        <div className="p-4 rounded-xl bg-success/10 border border-success/30 text-sm space-y-2">
          <p className="font-semibold text-success">Fuel & mileage log complete.</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-foreground">
            <span className="text-subtle">Start:</span><span>{displayStart} {distUnit}</span>
            <span className="text-subtle">End:</span><span>{displayEnd} {distUnit}</span>
            {displayDist != null && <><span className="text-subtle">Distance:</span><span>{displayDist} {distUnit}</span></>}
            {displayFuel != null && <><span className="text-subtle">Fuel added:</span><span>{displayFuel} {fuelUnit}</span></>}
          </div>
          {log.notes && <p className="text-xs text-subtle italic">Notes: {log.notes}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="p-3 rounded-xl bg-accent/30 border border-border text-xs text-foreground">
            Start odometer: <span className="font-medium">{displayStart} {distUnit}</span>
          </div>
          <p className="text-sm text-subtle">Record your return odometer and any fuel added.</p>
          <div>
            <label className="block text-xs text-subtle mb-1">Odometer End ({distUnit})</label>
            <input
              type="number"
              min={displayStart ?? 0}
              value={endOdo}
              onChange={e => setEndOdo(e.target.value)}
              placeholder={`≥ ${displayStart}`}
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label className="block text-xs text-subtle mb-1">Fuel Added ({fuelUnit}) — optional</label>
            <input
              type="number"
              min={0}
              value={fuelAdded}
              onChange={e => setFuelAdded(e.target.value)}
              placeholder={unit === 'imperial' ? 'e.g. 10' : 'e.g. 40'}
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Notes (optional)…"
            rows={2}
            className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
          />
          <button
            onClick={handleEndShift}
            disabled={!endOdo || loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? 'Saving…' : 'Log End Odometer'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Walker Rating Panel — drivers only, walkers fetched from today's crew
// ---------------------------------------------------------------------------
interface CrewMember { id: string; name: string; role: string; }

type WalkerEntry = {
  stars: number;
  comment: string;
  // null = attendance not yet marked; true = present; false = no-show
  present: boolean | null;
  submitted: boolean;
};

function WalkerRatingPanel({ employeeId }: { employeeId: string }) {
  const [walkers, setWalkers] = useState<CrewMember[]>([]);
  const [entries, setEntries] = useState<Record<string, WalkerEntry>>({});
  const [crewLoading, setCrewLoading] = useState(true);

  useEffect(() => {
    if (!employeeId) return;

    Promise.all([
      axiosClient.get(`/field-ops/crew/${employeeId}`),
      axiosClient.get(`/field-ops/rating/driver/${employeeId}`, { params: { target_date: todayStr() } }),
    ])
      .then(([crewRes, ratingsRes]) => {
        const crew: CrewMember[] = crewRes.data.crew ?? [];
        setWalkers(crew.filter(m => m.role === 'walker'));

        // Pre-populate from already-submitted records
        const pre: Record<string, WalkerEntry> = {};
        for (const r of ratingsRes.data) {
          pre[r.walker_id] = {
            stars: r.stars ?? 0,
            comment: r.comment ?? '',
            present: r.present,
            submitted: true,
          };
        }
        setEntries(pre);
      })
      .catch(console.error)
      .finally(() => setCrewLoading(false));
  }, [employeeId]);

  const ENTRY_DEFAULTS: WalkerEntry = { stars: 0, comment: '', present: null, submitted: false };

  const markAttendance = (id: string, present: boolean) => {
    setEntries(prev => ({
      ...prev,
      [id]: { ...ENTRY_DEFAULTS, ...prev[id], present },
    }));
  };

  const update = (id: string, field: 'stars' | 'comment', value: any) => {
    setEntries(prev => ({
      ...prev,
      [id]: { ...ENTRY_DEFAULTS, ...prev[id], [field]: value },
    }));
  };

  const submit = async (walker: CrewMember) => {
    const e = entries[walker.id];
    // Fix #10: guard against undefined entry or attendance not yet marked
    if (!e || e.present === null) return;
    if (e.present && !e.stars) return alert('Please select a star rating.');
    try {
      const payload: any = {
        driver_id: employeeId,
        walker_id: walker.id,
        date: todayStr(),
        present: e?.present ?? true,
      };
      if (e?.present) {
        payload.stars = e.stars;
        payload.comment = e.comment || null;
      }
      await axiosClient.post('/field-ops/rating', payload);
      setEntries(prev => ({ ...prev, [walker.id]: { ...prev[walker.id], submitted: true } }));
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit.');
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <Star className="w-4 h-4 text-warning" />
        </div>
        <h2 className="section-title">Walker Attendance & Rating</h2>
      </div>
      <p className="text-sm text-subtle">Mark attendance first, then rate walkers who were present. Visible to management only.</p>

      {crewLoading ? (
        <p className="text-sm text-subtle text-center py-4">Loading today's crew…</p>
      ) : walkers.length === 0 ? (
        <div className="py-6 text-center text-sm text-subtle bg-accent/20 rounded-xl border border-border/50">
          No walkers assigned to your truck today.
        </div>
      ) : (
        <div className="space-y-4">
          {walkers.map(walker => {
            const e = entries[walker.id] ?? { stars: 0, comment: '', present: null, submitted: false };
            return (
              <div key={walker.id} className="p-4 rounded-xl border border-border bg-background space-y-3">
                <p className="font-semibold text-sm text-foreground">{walker.name}</p>

                {e.submitted ? (
                  e.present ? (
                    <p className="text-xs text-success font-medium">
                      Rating submitted — {e.stars}★
                    </p>
                  ) : (
                    <p className="text-xs text-warning font-medium">Marked as no-show.</p>
                  )
                ) : (
                  <>
                    {/* Step 1: attendance */}
                    <div className="flex gap-2 items-center">
                      <span className="text-xs text-subtle">Attendance:</span>
                      <button
                        onClick={() => markAttendance(walker.id, true)}
                        className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-colors ${e.present === true ? 'bg-success text-white border-success' : 'border-border text-subtle hover:border-success hover:text-success'}`}
                      >
                        Present
                      </button>
                      <button
                        onClick={() => markAttendance(walker.id, false)}
                        className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-colors ${e.present === false ? 'bg-warning text-white border-warning' : 'border-border text-subtle hover:border-warning hover:text-warning'}`}
                      >
                        No-Show
                      </button>
                    </div>

                    {/* Step 2: rating (only if present) */}
                    {e.present === true && (
                      <>
                        <div className="flex gap-1">
                          {[1, 2, 3, 4, 5].map(star => (
                            <button
                              key={star}
                              onClick={() => update(walker.id, 'stars', star)}
                              className={`text-2xl leading-none transition-colors ${star <= e.stars ? 'text-warning' : 'text-border hover:text-warning/50'}`}
                            >
                              ★
                            </button>
                          ))}
                        </div>
                        <textarea
                          value={e.comment}
                          onChange={ev => update(walker.id, 'comment', ev.target.value)}
                          placeholder="Add a comment (optional)…"
                          rows={2}
                          className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                        />
                      </>
                    )}

                    {e.present !== null && (
                      <button
                        onClick={() => submit(walker)}
                        disabled={e.present === true && !e.stars}
                        className="btn-primary text-xs w-full disabled:opacity-50"
                      >
                        {e.present ? 'Submit Rating' : 'Confirm No-Show'}
                      </button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin Analytics View
// ---------------------------------------------------------------------------
function AdminFieldOpsView() {
  const [checkIns, setCheckIns]         = useState<any[]>([]);
  const [departures, setDepartures]     = useState<any[]>([]);
  const [inspections, setInspections]   = useState<any[]>([]);
  const [fuelLogs, setFuelLogs]         = useState<any[]>([]);
  const [noShows, setNoShows]           = useState<any[]>([]);
  const [loading, setLoading]           = useState(true);

  const load = () => {
    setLoading(true);
    Promise.allSettled([
      axiosClient.get('/field-ops/check-ins/summary').then(r => setCheckIns(r.data)),
      axiosClient.get('/field-ops/returns/summary').then(r => setDepartures(r.data)),
      axiosClient.get('/field-ops/inspections/summary').then(r => setInspections(r.data)),
      axiosClient.get('/field-ops/fuel-logs/summary').then(r => setFuelLogs(r.data)),
      axiosClient.get('/field-ops/no-shows').then(r => setNoShows(r.data)),
    ]).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const trucksOut      = departures.filter(d => d.status === 'out').length;
  const trucksReturned = departures.filter(d => d.status === 'returned').length;

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

  const fmtDuration = (mins: number | null) => {
    if (mins == null) return '—';
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  if (loading) {
    return (
      <div className="flex h-60 items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <MapPin className="w-5 h-5 text-primary" /> Field Operations
          </h1>
          <p className="text-subtle mt-1">Today's field activity — check-ins, departures, inspections, and fuel.</p>
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
          <BarChart2 className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Checked In',      value: checkIns.length,                                             color: 'text-info' },
          { label: 'Trucks Out',      value: trucksOut,                                                    color: trucksOut > 0 ? 'text-warning' : 'text-subtle' },
          { label: 'Returned',        value: trucksReturned,                                               color: 'text-success' },
          { label: 'No-Shows Today',  value: noShows.length,                                               color: noShows.length > 0 ? 'text-danger' : 'text-subtle' },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex items-center gap-4">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
              <p className={`text-2xl font-bold mt-0.5 ${stat.color}`}>{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Departures & Returns */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <LogOut className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Departures & Returns</h2>
          <span className="ml-auto text-xs text-subtle">{departures.length} driver{departures.length !== 1 ? 's' : ''}</span>
        </div>
        {departures.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No departures recorded today.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Driver</th>
                  <th className="pb-2 pr-4">Departed</th>
                  <th className="pb-2 pr-4">Returned</th>
                  <th className="pb-2 pr-4">Duration</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {departures.map((d: any) => (
                  <tr key={d.employee_id}>
                    <td className="py-2 pr-4 font-medium text-foreground">{d.driver_name}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{fmt(d.departed_at)}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{fmt(d.returned_at)}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{fmtDuration(d.duration_minutes)}</td>
                    <td className="py-2">
                      {d.status === 'returned' ? (
                        <span className="inline-flex items-center gap-1 text-success text-xs font-semibold">
                          <CheckCircle2 className="w-3 h-3" /> Returned
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-warning text-xs font-semibold">
                          <MapPin className="w-3 h-3" /> Out
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Inspections */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <ClipboardCheck className="w-5 h-5 text-info" />
          <h2 className="text-base font-semibold text-foreground">Pre-Trip Inspections</h2>
          {inspections.length > 0 && (
            <span className="ml-auto text-xs text-subtle">
              {inspections.filter(i => i.has_failures).length} failed · {inspections.filter(i => !i.has_failures).length} passed
            </span>
          )}
        </div>
        {inspections.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No inspections submitted today.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Driver</th>
                  <th className="pb-2 pr-4">Truck</th>
                  <th className="pb-2 pr-4">Submitted</th>
                  <th className="pb-2 pr-4">Result</th>
                  <th className="pb-2">Failed Items</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {inspections.map((insp: any) => (
                  <tr key={insp.inspection_id} className={insp.has_failures ? 'bg-danger/5' : ''}>
                    <td className="py-2 pr-4 font-medium text-foreground">{insp.driver_name}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{insp.truck_name ?? '—'}</td>
                    <td className="py-2 pr-4 text-muted-foreground text-xs">{fmt(insp.submitted_at)}</td>
                    <td className="py-2 pr-4">
                      {insp.has_failures ? (
                        <span className="inline-flex items-center gap-1 text-danger text-xs font-semibold">
                          <AlertTriangle className="w-3 h-3" /> Failed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-success text-xs font-semibold">
                          <CheckCircle2 className="w-3 h-3" /> Passed
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-xs text-danger">
                      {insp.failed_items?.length > 0
                        ? insp.failed_items.map((item: string) => item.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())).join(', ')
                        : <span className="text-subtle">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Fuel & Mileage */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Fuel className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Fuel & Mileage</h2>
          <span className="ml-auto text-xs text-subtle">{fuelLogs.length} log{fuelLogs.length !== 1 ? 's' : ''}</span>
        </div>
        {fuelLogs.length === 0 ? (
          <p className="text-sm text-subtle text-center py-6">No fuel logs submitted today.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Driver</th>
                  <th className="pb-2 pr-4">Truck</th>
                  <th className="pb-2 pr-4">Start Odo</th>
                  <th className="pb-2 pr-4">End Odo</th>
                  <th className="pb-2 pr-4">Distance</th>
                  <th className="pb-2">Fuel Added</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {fuelLogs.map((log: any) => (
                  <tr key={log.log_id}>
                    <td className="py-2 pr-4 font-medium text-foreground">{log.driver_name}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{log.truck_name ?? '—'}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{log.odometer_start.toLocaleString()}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{log.odometer_end != null ? log.odometer_end.toLocaleString() : '—'}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{log.distance != null ? `${log.distance.toLocaleString()} mi` : '—'}</td>
                    <td className="py-2 text-muted-foreground">{log.fuel_added != null ? `${log.fuel_added} gal` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Walker No-Shows */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <XCircle className="w-5 h-5 text-danger" />
          <h2 className="text-base font-semibold text-foreground">Walker No-Shows</h2>
          {noShows.length > 0 && (
            <span className="ml-auto text-xs font-bold bg-danger text-white px-2 py-0.5 rounded-full">{noShows.length}</span>
          )}
        </div>
        {noShows.length === 0 ? (
          <div className="text-center py-8 opacity-60">
            <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
            <p className="text-sm font-medium">No no-shows recorded today.</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {noShows.map((ns: any) => (
              <div key={ns.walker_id} className="py-2 flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">{ns.walker_name}</span>
                <span className="text-xs text-muted-foreground">Driver: {ns.driver_name}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Anchor Point Panel
// ---------------------------------------------------------------------------
function AnchorPointPanel({ employeeId }: { employeeId: string }) {
  const today = todayStr();
  const [trucks, setTrucks]         = useState<any[]>([]);
  const [myTruckId, setMyTruckId]   = useState('');
  const [existing, setExisting]     = useState<any>(null);
  const [location, setLocation]     = useState('');
  const [eta, setEta]               = useState('');
  const [notes, setNotes]           = useState('');
  const [loading, setLoading]       = useState(false);
  const [success, setSuccess]       = useState(false);
  const [error, setError]           = useState('');

  useEffect(() => {
    // Load today's crew to find which truck this driver is on
    axiosClient.get(`/field-ops/crew/${employeeId}`)
      .then(res => {
        const crew = res.data;
        if (crew.truck_id) setMyTruckId(crew.truck_id);
      })
      .catch(() => {});

    // Check if already submitted today
    axiosClient.get('/anchor-points/driver/today')
      .then(res => {
        if (res.data) {
          setExisting(res.data);
          setLocation(res.data.location);
          setEta(res.data.eta || '');
          setNotes(res.data.notes || '');
        }
      })
      .catch(() => {});
  }, [employeeId]);

  const handleSubmit = async () => {
    if (!myTruckId || !location.trim()) return;
    setLoading(true);
    setError('');
    try {
      await axiosClient.post('/anchor-points/', {
        truck_id: myTruckId,
        date: today,
        location: location.trim(),
        eta: eta.trim() || null,
        notes: notes.trim() || null,
      });
      setSuccess(true);
      // Refresh existing
      const res = await axiosClient.get('/anchor-points/driver/today');
      setExisting(res.data);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to submit anchor point.');
    } finally {
      setLoading(false);
    }
  };

  const isConfirmed = existing?.confirmed_at != null;

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <MapPin className="w-4 h-4 text-info" />
        </div>
        <h2 className="section-title">EOD Anchor Point</h2>
      </div>

      {isConfirmed ? (
        <div className="p-4 rounded-xl bg-success/10 border border-success/30 space-y-1">
          <p className="text-sm font-semibold text-success">Anchor point confirmed by dispatch.</p>
          <p className="text-sm text-foreground">📍 {existing.location}</p>
          {existing.eta && <p className="text-xs text-subtle">ETA: {existing.eta}</p>}
        </div>
      ) : existing ? (
        <div className="space-y-3">
          <div className="p-3 rounded-xl bg-accent/50 border border-border text-sm">
            <p className="text-xs text-subtle mb-1">Submitted — awaiting dispatch confirmation.</p>
            <p className="font-medium text-foreground">📍 {existing.location}</p>
            {existing.eta && <p className="text-xs text-subtle">ETA: {existing.eta}</p>}
          </div>
          <p className="text-xs text-subtle">You can update your submission until dispatch confirms it.</p>
          <div className="space-y-2">
            <input type="text" value={location} onChange={e => setLocation(e.target.value)}
              placeholder="Anchor point address or landmark"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            <input type="text" value={eta} onChange={e => setEta(e.target.value)}
              placeholder="ETA (e.g. 4:30 PM)"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Notes (optional — lot B, facing gate, etc.)"
              rows={2}
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none" />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <button onClick={handleSubmit} disabled={loading || !location.trim() || !myTruckId}
            className="btn-primary text-sm w-full disabled:opacity-50">
            {loading ? 'Updating…' : 'Update Anchor Point'}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-subtle">
            Submit your end-of-day anchor point. This will be posted to your truck channel and notifies dispatch.
          </p>
          {!myTruckId && (
            <p className="text-xs text-warning">No truck assignment found for today. Check in first.</p>
          )}
          <div className="space-y-2">
            <input type="text" value={location} onChange={e => setLocation(e.target.value)}
              placeholder="Anchor point address or landmark *"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            <input type="text" value={eta} onChange={e => setEta(e.target.value)}
              placeholder="ETA (e.g. 4:30 PM)"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Notes (optional — lot B, facing gate, etc.)"
              rows={2}
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none" />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          {success && <p className="text-xs text-success">Anchor point posted to truck channel.</p>}
          <button onClick={handleSubmit} disabled={loading || !location.trim() || !myTruckId}
            className="btn-primary text-sm w-full disabled:opacity-50">
            {loading ? 'Submitting…' : 'Submit Anchor Point'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
// Walker Self-Performance Panel
// ---------------------------------------------------------------------------
function StarRow({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-subtle">No ratings yet</span>;
  const full = Math.floor(value);
  const frac = value - full;
  return (
    <span className="flex items-center gap-0.5">
      {[1,2,3,4,5].map(i => (
        <Star key={i} className={`w-4 h-4 ${i <= full ? 'text-warning fill-warning' : i === full + 1 && frac >= 0.5 ? 'text-warning fill-warning/50' : 'text-muted-foreground'}`} />
      ))}
      <span className="ml-1 text-xs font-semibold text-foreground">{value.toFixed(1)}</span>
    </span>
  );
}

const GRADE_COLOR: Record<string, string> = {
  A: 'text-success', B: 'text-info', C: 'text-warning', D: 'text-orange-500', F: 'text-danger',
};

function WalkerSelfPerformancePanel({ employeeId }: { employeeId: string }) {
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/walker-profile/${employeeId}`)
      .then(r => setProfile(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [employeeId]);

  return (
    <div className="card">
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
        <BarChart2 className="w-5 h-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">My Performance</h2>
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : !profile || profile.total_shifts === 0 ? (
        <p className="text-sm text-subtle text-center py-6">No shift data recorded yet.</p>
      ) : (
        <div className="space-y-4">
          {/* KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Grade', value: profile.grade ?? '—', extra: profile.grade ? <span className={`text-2xl font-bold ${GRADE_COLOR[profile.grade] ?? 'text-foreground'}`}>{profile.grade}</span> : null },
              { label: 'Presence', value: profile.presence_rate !== null ? `${profile.presence_rate}%` : '—', danger: (profile.presence_rate ?? 100) < 80 },
              { label: 'Shifts', value: profile.total_shifts },
              { label: 'No-shows', value: profile.no_show_count, danger: profile.no_show_count >= 3 },
            ].map(({ label, value, extra, danger }) => (
              <div key={label} className="rounded-xl border border-border p-3 text-center">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
                {extra ?? <p className={`text-2xl font-bold ${danger ? 'text-danger' : 'text-foreground'}`}>{value}</p>}
              </div>
            ))}
          </div>

          {/* Avg rating */}
          <div className="flex items-center justify-between py-2 border-t border-border">
            <span className="text-sm text-muted-foreground">Avg Driver Rating</span>
            <StarRow value={profile.avg_stars} />
          </div>

          {/* Recent ratings */}
          {profile.ratings?.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Recent Shift Reviews</p>
              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {profile.ratings.slice(0, 10).map((r: any, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-2.5 rounded-xl border border-border bg-surface-muted/40">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs text-subtle">{r.date}</span>
                        <span className="text-xs text-muted-foreground">· {r.driver_name ?? 'Driver'}</span>
                        {r.present ? (
                          <span className="text-xs text-success font-medium">Present</span>
                        ) : (
                          <span className="text-xs text-danger font-medium">No-show</span>
                        )}
                      </div>
                      {r.comment && <p className="text-xs text-foreground mt-1 italic">"{r.comment}"</p>}
                    </div>
                    {r.stars !== null && (
                      <span className="text-xs font-bold text-warning shrink-0">{r.stars}★</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Driver Inspection History Panel
// ---------------------------------------------------------------------------
function DriverInspectionHistoryPanel({ employeeId }: { employeeId: string }) {
  const [records, setRecords] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get(`/field-ops/inspection/${employeeId}`)
      .then(r => setRecords(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [employeeId]);

  const passCount  = records.filter(r => !r.has_failures).length;
  const failCount  = records.filter(r => r.has_failures).length;

  return (
    <div className="card">
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
        <TrendingUp className="w-5 h-5 text-info" />
        <h2 className="text-base font-semibold text-foreground">My Inspection History</h2>
        {records.length > 0 && (
          <span className="ml-auto text-xs text-subtle">{records.length} inspections</span>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : records.length === 0 ? (
        <p className="text-sm text-subtle text-center py-6">No inspections submitted yet.</p>
      ) : (
        <div className="space-y-3">
          {/* Summary */}
          <div className="grid grid-cols-3 gap-3 mb-2">
            {[
              { label: 'Total', value: records.length },
              { label: 'Passed', value: passCount, color: 'text-success' },
              { label: 'Failed', value: failCount, color: failCount > 0 ? 'text-danger' : 'text-foreground' },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded-xl border border-border p-3 text-center">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-xl font-bold ${color ?? 'text-foreground'}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Record list */}
          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {records.map((r: any) => {
              const isOpen = expanded === r.id;
              const failed = r.items ? Object.entries(r.items as Record<string, boolean>).filter(([, v]) => !v).map(([k]) => k) : [];
              return (
                <div key={r.id} className="rounded-xl border border-border overflow-hidden">
                  <button
                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-accent/40 transition-colors text-left"
                    onClick={() => setExpanded(isOpen ? null : r.id)}
                  >
                    {r.has_failures ? (
                      <XCircle className="w-4 h-4 text-danger shrink-0" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
                    )}
                    <span className="text-sm font-medium text-foreground flex-1">{r.date}</span>
                    {r.has_failures && (
                      <span className="text-xs text-danger font-medium">{failed.length} failure{failed.length !== 1 ? 's' : ''}</span>
                    )}
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.has_failures ? 'bg-danger/10 text-danger' : 'bg-success/10 text-success'}`}>
                      {r.has_failures ? 'Failed' : 'Passed'}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-3 border-t border-border/50 pt-2 space-y-1.5">
                      {failed.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {failed.map(k => (
                            <span key={k} className="text-xs bg-danger/10 text-danger px-2 py-0.5 rounded-full">{ITEM_LABELS[k] ?? k}</span>
                          ))}
                        </div>
                      )}
                      {r.notes && <p className="text-xs text-subtle italic">{r.notes}</p>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
export default function FieldOps() {
  const { groups, user } = useAuth();
  const isAdmin  = groups.includes('admin');
  const isDriver = groups.includes('driver');
  const isWalker = groups.includes('walker');

  const [employeeId, setEmployeeId] = useState('');

  // Resolve the logged-in user's employee DB record (only needed for driver view)
  useEffect(() => {
    if (isAdmin || !user) return;
    axiosClient.get('/employees/me')
      .then(res => setEmployeeId(res.data.id))
      .catch(console.error);
  }, [user, isAdmin]);

  if (isAdmin) {
    return <AdminFieldOpsView />;
  }

  if (!employeeId) {
    return (
      <div className="max-w-2xl mx-auto space-y-6 animate-slide-up">
        <h1 className="page-title">Field Operations</h1>
        <div className="card text-center py-10 text-subtle text-sm">Loading your profile…</div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-slide-up">
      <h1 className="page-title">Field Operations</h1>
      <CheckInPanel employeeId={employeeId} />
      {isDriver && <InspectionPanel employeeId={employeeId} />}
      {isDriver && <FuelMileagePanel employeeId={employeeId} />}
      <DeparturePanel employeeId={employeeId} />
      {isDriver && <ReturnPanel employeeId={employeeId} />}
      {isDriver && <AnchorPointPanel employeeId={employeeId} />}
      {isDriver && <WalkerRatingPanel employeeId={employeeId} />}
      {isDriver && <DriverInspectionHistoryPanel employeeId={employeeId} />}
      {isWalker && <WalkerSelfPerformancePanel employeeId={employeeId} />}
    </div>
  );
}
