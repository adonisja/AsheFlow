import { useCallback, useEffect, useMemo, useState } from 'react';
import { Package, RefreshCw, Plus, AlertTriangle, Check, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import { errorText } from '../utils/errorText';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import type {
  ToteAddressListOut,
  ToteAddressOut,
  UnaddressedBagOut,
  WorkforceOVOut,
  LoadRosterOut,
} from '../api/types';

/** Tote & OV addressing — workforce mode's only source of geography.
 *
 *  Mobile has had this since ADR-296. Web never did, and web is what the
 *  captain actually uses: no app is shipped, so ADR-402 D4 makes the browser
 *  the field surface. Until this existed a captain could not address a tote at
 *  all on the device in their hand.
 *
 *  ADR-296 D2 governs the interaction and it is deliberately not a form beside
 *  a list: ONE BAG AT A TIME, PICKER OR ENTRY, NEVER BOTH. A 25-row picker
 *  above a form pushes the form off a phone screen, and the captain is holding
 *  a tote while they type.
 *
 *  ADR-400 A2 adds OVs. They address exactly like a tote with two differences:
 *  a size is required (the sort cannot cost the route without it) and only one
 *  address is accepted, because an OV is one package.
 */

const OV_SIZES = ['XS', 'S', 'M', 'L', 'XL'] as const;
type OVSize = typeof OV_SIZES[number];

/** ADR-403 D1a. Packages at THIS address. A drop of eight outvotes a single
 *  package on another block — the signal counting addresses threw away. */
const COUNT_CHOICES = [1, 2, 3, 4, 5, 6, 8, 10] as const;

function isOv(bagId: string): boolean {
  return /^OV\d+$/.test(bagId.trim());
}

export default function ToteAddresses() {
  const { hasFeature } = useAuth();
  const [date] = useState(getLocalYMD());
  const [truckId, setTruckId] = useState<string | null>(null);
  const [taId, setTaId] = useState<string | null>(null);
  const [data, setData] = useState<ToteAddressListOut | null>(null);
  const [ovs, setOvs] = useState<WorkforceOVOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // ADR-296 D2: exactly one of these is on screen at a time.
  const [openBag, setOpenBag] = useState<string | null>(null);
  const [address, setAddress] = useState('');
  const [count, setCount] = useState(1);
  const [size, setSize] = useState<OVSize | null>(null);
  const [saving, setSaving] = useState(false);
  const [addingOv, setAddingOv] = useState(false);

  const beginEntry = (bagId: string) => {
    setOpenBag(bagId);
    setAddress('');
    setCount(1);
    // Pre-fill a known size so a re-address does not silently change it.
    setSize((ovs.find(o => o.ov_id === bagId)?.size as OVSize) ?? null);
    setError('');
  };


  /** ADR-400 A5b/A6c. A mid-day OV is an ARRIVAL, not evidence the sheet was
   *  wrong. The client SUGGESTS which from the clock — the workday starts when
   *  the truck reaches the AP, so hours later is almost certainly a milk-run —
   *  and the captain confirms. The server never infers: a guessed origin would
   *  be unauditable, since no later reader could tell it from a statement. */
  const suggestedSource = (): 'milk_run' | 'captain' =>
    new Date().getHours() >= 11 ? 'milk_run' : 'captain';

  const addOv = async (source: 'milk_run' | 'captain') => {
    if (!taId) return;
    setAddingOv(false);
    setSaving(true);
    try {
      const res = await axiosClient.post<WorkforceOVOut>('/workforce/ovs', {
        truck_assignment_id: taId,
        entry_date: date,
        source,
      });
      await load();
      // Straight into entry: the captain is holding the package they just
      // added, and making them find it in the picker is a step for nothing.
      beginEntry(res.data.ov_id);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not add that OV.'));
    } finally {
      setSaving(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const mine = await axiosClient.get<{ truck_id: string | null }>(
        `/workforce/my-truck/${date}`,
      );
      const id = mine.data.truck_id;
      setTruckId(id);
      if (!id) { setData(null); setError(''); return; }

      const res = await axiosClient.get<ToteAddressListOut>(
        `/workforce/tote-addresses/${date}`, { params: { truck_id: id } },
      );
      setData(res.data);

      // The roster carries the OVs. Fetched separately and tolerantly: OVs are
      // an addition to this screen, and a truck with no BTR sheet still has
      // totes to address.
      try {
        const tas = await axiosClient.get<{ id: string; truck_id: string }[]>(
          '/assignments/', { params: { date } },
        );
        const ta = tas.data.find(t => t.truck_id === id);
        if (ta) {
          // Seed first. `BTROVZone` has carried the sheet's OVs since ADR-290
          // and nothing ever read it, so without this call the OVs the sheet
          // lists never become addressable units and the captain simply does
          // not see them. Idempotent on the truck-day (ADR-400 A2), so running
          // it on every page load adds only what is missing.
          try {
            await axiosClient.post(`/workforce/ovs/${date}/seed`, null,
              { params: { truck_assignment_id: ta.id } });
          } catch {
            // No sheet, or already seeded. Either way the roster read below
            // still reports the truth, so this must not block the page.
          }

          const roster = await axiosClient.get<LoadRosterOut>(
            `/workforce/load-roster/${date}`,
            { params: { truck_assignment_id: ta.id } },
          );
          setOvs(roster.data.ovs ?? []);
          setTaId(ta.id);
        }
      } catch { /* totes are the page; OVs are extra */ }
      setError('');
    } catch (e: unknown) {
      setError(errorText(e, 'Could not load this truck’s totes.'));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  const byBag = useMemo(() => {
    const m = new Map<string, ToteAddressOut[]>();
    for (const a of data?.addresses ?? []) {
      const list = m.get(a.bag_id) ?? [];
      list.push(a);
      m.set(a.bag_id, list);
    }
    return m;
  }, [data]);

  const openIsOv = openBag !== null && isOv(openBag);
  const openHasAddress = openBag !== null && (byBag.get(openBag)?.length ?? 0) > 0;

  const submit = async () => {
    if (!truckId || !openBag) return;
    if (openIsOv && !size) {
      setError('Choose a size for this OV. The sort needs it to plan the route.');
      return;
    }
    setSaving(true);
    try {
      await axiosClient.post('/workforce/tote-addresses', {
        truck_id: truckId,
        entry_date: date,
        bag_id: openBag,
        raw_address: address.trim(),
        package_count: count,
        ...(openIsOv ? { ov_size: size } : {}),
      });
      setAddress('');
      setCount(1);
      await load();
      // An OV takes one address, so entry is finished. A tote may take more.
      if (openIsOv) setOpenBag(null);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not save that address.'));
    } finally {
      setSaving(false);
    }
  };

  if (!hasFeature('workforce_sort')) {
    return (
      <div className="card p-6 text-sm text-muted-foreground">
        Tote addressing is part of workforce mode. This company gets addresses
        from an Amazon package feed instead.
      </div>
    );
  }

  const unaddressed: UnaddressedBagOut[] = data?.unaddressed ?? [];
  const unaddressedOvs = ovs.filter(o => !o.addressed);
  const addressedBags = [...byBag.keys()].sort();

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        eyebrow="Workforce sort"
        title={<span className="flex items-center gap-2"><Package className="w-5 h-5" /> Tote Addresses</span>}
        description="Open a tote, read an address, record where it goes"
      />

      <ErrorBanner message={error || null} />

      {loading ? (
        <div className="card p-6 text-sm text-muted-foreground">Loading…</div>
      ) : !truckId ? (
        <div className="card p-6 text-sm text-muted-foreground">
          You are not crewed on a truck today.
        </div>
      ) : openBag !== null ? (
        /* ── ENTRY. ADR-296 D2: the picker is gone while this is open. ── */
        <div className="card p-4 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs text-muted-foreground">
                {openIsOv ? 'Oversized package' : 'Tote'}
              </div>
              <div className="text-xl font-semibold">{openBag}</div>
            </div>
            <button className="btn-ghost" onClick={() => setOpenBag(null)}>
              <X className="w-4 h-4" /> Done
            </button>
          </div>

          {openIsOv && openHasAddress ? (
            <div className="text-sm text-muted-foreground">
              This OV already has an address. An OV is one package, so it takes
              one address.
            </div>
          ) : (
            <>
              <div>
                <label className="label" htmlFor="addr">Address</label>
                <input
                  id="addr"
                  className="input w-full"
                  value={address}
                  onChange={e => setAddress(e.target.value)}
                  placeholder="350 W 36th St"
                  autoFocus
                />
              </div>

              {/* ADR-400 A2. Required for an OV, and absent for a tote — a size
                  on a tote is rejected by the server, so it must not be
                  offerable here. */}
              {openIsOv && (
                <div>
                  <label className="label">Size</label>
                  <div className="flex flex-wrap gap-2">
                    {OV_SIZES.map(sz => (
                      <button
                        key={sz}
                        type="button"
                        onClick={() => setSize(sz)}
                        className={`px-3 py-2 rounded-lg text-sm font-medium border ${
                          size === sz
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border text-muted-foreground'
                        }`}
                      >
                        {sz}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    How much cart space it takes. XS is an envelope and costs
                    nothing; XL fills a cart slot on its own.
                  </p>
                </div>
              )}

              {/* ADR-403 D1a. Only for totes: an OV is one package by
                  definition, so a count would be meaningless. */}
              {!openIsOv && (
                <div>
                  <label className="label">Packages going here</label>
                  <div className="flex flex-wrap gap-2">
                    {COUNT_CHOICES.map(n => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setCount(n)}
                        className={`w-11 h-11 rounded-lg text-sm font-medium border ${
                          count === n
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border text-muted-foreground'
                        }`}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Several packages to one door counts as several. It decides
                    which block the tote belongs to.
                  </p>
                </div>
              )}

              <button
                className="btn-primary w-full"
                onClick={submit}
                disabled={saving || address.trim().length < 3}
              >
                {saving ? 'Saving…' : 'Save address'}
              </button>
            </>
          )}

          {/* Entries already on this bag, so the captain sees the countdown. */}
          {(byBag.get(openBag)?.length ?? 0) > 0 && (
            <div className="border-t border-border pt-3 space-y-2">
              {byBag.get(openBag)!.map(a => (
                <div key={a.id} className="flex items-start gap-2 text-sm">
                  <Check className="w-4 h-4 mt-0.5 text-success shrink-0" />
                  <div className="min-w-0">
                    <div className="truncate">{a.raw_address}</div>
                    <div className="text-xs text-muted-foreground">
                      {a.block_description ?? a.block_key ?? 'Address could not be read'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        /* ── PICKER ── */
        <>
          <div className="card p-4 flex items-center gap-3">
            <button className="btn-ghost flex items-center gap-2" onClick={load}>
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            {taId && (
              <button
                className="btn-ghost flex items-center gap-2"
                onClick={() => setAddingOv(true)}
                disabled={saving}
              >
                <Plus className="w-4 h-4" /> Add OV
              </button>
            )}
            <span className="text-xs text-muted-foreground ml-auto tabular-nums">
              {unaddressed.length + unaddressedOvs.length} left
            </span>
          </div>

          {/* A6c: the clock suggests, the captain decides. Presented as two
              plain choices rather than a pre-ticked default, because a
              pre-selected wrong answer is worse than no answer — the captain is
              standing there and knows how the package arrived. */}
          {addingOv && (
            <div className="card p-4 space-y-3">
              <div className="text-sm font-medium">Where did this package come from?</div>
              <div className="flex flex-wrap gap-2">
                <button
                  className={suggestedSource() === 'milk_run' ? 'btn-primary' : 'btn-ghost'}
                  onClick={() => addOv('milk_run')}
                >
                  A station run
                </button>
                <button
                  className={suggestedSource() === 'captain' ? 'btn-primary' : 'btn-ghost'}
                  onClick={() => addOv('captain')}
                >
                  It was on the truck
                </button>
                <button className="btn-ghost ml-auto" onClick={() => setAddingOv(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {data && data.disagreements.length > 0 && (
            <div className="card p-4 text-sm space-y-1">
              <div className="flex items-center gap-2 text-warning font-medium">
                <AlertTriangle className="w-4 h-4" /> Split totes
              </div>
              {data.disagreements.map(d => (
                <div key={d.bag_id} className="text-muted-foreground">
                  <span className="font-medium text-foreground">{d.bag_id}</span>
                  {' '}has addresses on {d.block_keys.length} blocks. Most of it
                  looks like {d.winning_block_key.replace(/_/g, ' ')}.
                </div>
              ))}
            </div>
          )}

          {unaddressed.length === 0 && unaddressedOvs.length === 0 ? (
            <div className="card p-6 text-sm text-muted-foreground">
              Every tote on the sheet has an address. Build routes when you are
              ready.
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {unaddressed.map(b => (
                <button
                  key={b.bag_id}
                  onClick={() => beginEntry(b.bag_id)}
                  className="card p-3 flex items-center gap-3 text-left hover:border-primary"
                >
                  <span
                    className="w-6 h-6 rounded-full border border-border shrink-0"
                    style={{ background: b.bag_color ?? 'transparent' }}
                    aria-hidden
                  />
                  <span className="min-w-0">
                    <span className="block font-medium">{b.bag_id}</span>
                    <span className="block text-xs text-muted-foreground truncate">
                      {b.bag_color_name ?? 'No colour on the sheet'}
                    </span>
                  </span>
                  <Plus className="w-4 h-4 ml-auto text-muted-foreground shrink-0" />
                </button>
              ))}

              {unaddressedOvs.map(o => (
                <button
                  key={o.ov_id}
                  onClick={() => beginEntry(o.ov_id)}
                  className="card p-3 flex items-center gap-3 text-left hover:border-primary"
                >
                  <span className="px-1.5 py-0.5 rounded bg-accent text-[11px] font-medium shrink-0">
                    OV
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium">{o.ov_id}</span>
                    <span className="block text-xs text-muted-foreground truncate">
                      {o.zone_label ?? 'Added on the truck'}
                    </span>
                  </span>
                  <Plus className="w-4 h-4 ml-auto text-muted-foreground shrink-0" />
                </button>
              ))}
            </div>
          )}

          {addressedBags.length > 0 && (
            <div className="card p-4">
              <div className="text-sm font-medium mb-2">
                Addressed ({addressedBags.length})
              </div>
              <div className="flex flex-wrap gap-2">
                {addressedBags.map(bag => (
                  <button
                    key={bag}
                    onClick={() => beginEntry(bag)}
                    className="px-2 py-1 rounded-lg bg-accent text-xs hover:bg-accent/70"
                  >
                    {bag}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
