import { useEffect, useState } from 'react';
import { Loader2, MapPin } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type { NearbyDoor } from '../api/types';

const BOROUGH_NAMES: Record<string, string> = {
  '1': 'Manhattan', '2': 'Bronx', '3': 'Brooklyn', '4': 'Queens', '5': 'Staten Island',
};

/** Pick the door a package goes to, from PlaceType's city doors near a point,
 *  or pin it there (ADR-584 D4). Used on Sort, tote entry and found-package intake.
 *
 *  The doors are public city addresses (AddressPoint), never a customer's: the
 *  endpoint is bounded to 150 m and 10 doors. A pin always resolves the package,
 *  so one address PlaceType can't place never holds a whole sort. */
export default function DoorPicker({
  lat, lng, street, busy, onPick, onPin,
}: {
  lat: number | null;
  lng: number | null;
  /** Narrows the list to a street the person typed, e.g. "5 AVE". Optional. */
  street?: string;
  busy?: boolean;
  onPick: (door: NearbyDoor) => void;
  onPin: (lat: number, lng: number) => void;
}) {
  const [doors, setDoors] = useState<NearbyDoor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (lat == null || lng == null) { setDoors([]); return; }
    let live = true;
    setDoors(null);
    setError(null);
    axiosClient
      .get<{ doors: NearbyDoor[] }>('/placetype/doors/nearby', {
        params: { lat, lng, ...(street && street.trim().length >= 2 ? { street: street.trim() } : {}) },
      })
      .then(({ data }) => { if (live) setDoors(data.doors); })
      .catch((e) => { if (live) { setDoors([]); setError(errorText(e, "Couldn't load nearby doors.")); } });
    return () => { live = false; };
  }, [lat, lng, street]);

  if (lat == null || lng == null) {
    return (
      <p className="text-[11px] text-muted-foreground">
        This package has no location to search from. Correct the address instead.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[11px] text-muted-foreground">Doors within 150 m. Pick the one it goes to:</p>
      {doors === null && (
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Loader2 className="w-3 h-3 animate-spin" /> Finding doors…
        </span>
      )}
      {error && <p className="text-[11px] text-danger">{error}</p>}
      {doors && doors.length === 0 && !error && (
        <p className="text-[11px] text-muted-foreground">No city door within 150 m.</p>
      )}
      {doors && doors.length > 0 && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1">
          {doors.map((d) => (
            <li key={`${d.borough}:${d.address}`}>
              <button
                type="button"
                disabled={busy}
                onClick={() => onPick(d)}
                className="w-full text-left rounded-md border border-border px-2 py-1 text-[11px] hover:bg-accent disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span className="font-mono">{d.address}</span>
                <span className="text-muted-foreground tabular-nums">
                  {' · '}{BOROUGH_NAMES[d.borough] ?? d.borough}{' · '}{Math.round(d.distance_m)} m
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={() => onPin(lat, lng)}
        className="self-start inline-flex items-center gap-1 text-[11px] text-primary hover:underline disabled:opacity-50"
        title="Use this location without a door; the nearest door within 30 m is taken if there is one"
      >
        <MapPin className="w-3 h-3" /> Pin at the manifest&apos;s location
      </button>
    </div>
  );
}
