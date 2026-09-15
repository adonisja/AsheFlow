import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Footprints, Plus, Trash2, Download, Upload, Clock,
  RotateCcw, ChevronDown, ChevronRight, Save, Layers, Search, CornerDownLeft,
  Route, X, Pencil, Check, FileSpreadsheet, Camera, Loader2,
} from 'lucide-react';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';
import { getLocalYMD } from '../utils/date';
import {
  RTS_CODES, dayId, deleteDay, download, durationMin, emptyDay,
  emptyRoute, fmtDuration, getDay, getUnclaimed, importJSON, knownNames, listAll,
  clearDate, clearWalkers, deleteProfile, downloadBlob, getActiveBtr, getCrew,
  allProfiles, isDateCleared, profilesForDate, putProfile,
  listAllUnclaimed, unclearDate,
  listByDate,
  manifestLoad, manifestsForDate, nextRouteId, nowHM,
  putCrew, putDay, putManifest, putUnclaimed, setActiveBtr, toCSV,
  type LogRoute, type StoredManifest, type WalkerDay,
} from '../utils/walkerLogDb';
import {
  bagToTote, crewFor, seedFor, unassignedBags, type SeedBag,
} from '../utils/walkerLogSeed';
import WalkerPicker from '../components/walkerlog/WalkerPicker';
import Dropdown from '../components/walkerlog/Dropdown';
import DifficultyPicker from '../components/walkerlog/DifficultyPicker';
import ToteList from '../components/walkerlog/ToteList';
import OVList from '../components/walkerlog/OVList';
import LabelScanner from '../components/walkerlog/LabelScanner';
import ImportDialog from '../components/walkerlog/ImportDialog';
import AddressProfileForm from '../components/walkerlog/AddressProfileForm';
import {
  emptyProfile, isUsable, profileId, profilesToCSV, type AddressProfile, knownAddresses, rememberKnown, doorKey} from '../utils/addressProfile';
import { checkAddress, submitConfigured, submitProfiles } from '../utils/collectionSubmit';
import { buildWorkbook } from '../utils/walkerLogXlsx';

/** Manual walker/route tracker — a research instrument, not an operational page.
 *
 *  UNAUTHENTICATED AND OUTSIDE <Layout> ON PURPOSE. It makes no API call and
 *  holds no tenant data, so there is nothing here to authorise: the only data
 *  it can reach is what this browser typed into its own IndexedDB. Putting it
 *  behind ProtectedRoute would mean logging in to take notes. It therefore also
 *  never touches AuthContext, and renders its own page chrome.
 *
 *  Everything here is hand-entered observation stored in THIS BROWSER
 *  (IndexedDB) and never sent anywhere. That isolation is the point: the data
 *  exists to be compared against what the production sort produced, and mixing
 *  observations into `routes` would destroy the ability to tell them apart.
 *
 *  Two entry modes, because the same data gets captured two ways (both were
 *  asked for):
 *    LIVE  — "now" buttons stamp arrival/start/end as the day happens.
 *    TYPE-UP — every timestamp is a plain <input type="time">, so a day can be
 *              backfilled from paper with no stamping at all.
 *  Neither is a mode switch: the stamp buttons sit BESIDE always-editable
 *  fields, so a live-stamped time can be corrected later and a backfilled day
 *  can be finished live.
 *
 *  Saving is explicit rather than debounced-on-keystroke. A debounce racing a
 *  half-typed address into IndexedDB makes the export non-reproducible, and
 *  there is no server round-trip to make an explicit save feel slow.
 */

/** Touch-target floor, applied only on a COARSE POINTER (finger), so the
 *  desktop layout keeps its density.
 *
 *  Measured on an iPhone-width viewport: 57 controls were under 32px — crew
 *  rows 20px tall, the small remove buttons 18x18. The page fit the screen and
 *  was still awkward to use, which is the difference between "responsive" and
 *  "usable on the device". iOS HIG asks for 44pt and Material for 48dp; 40px
 *  here is the pragmatic floor that does not force every row taller than a
 *  phone screen can hold.
 *
 *  Scoped to this page rather than added to index.css, which 30+ other pages
 *  render and which I have no mandate to re-space. */
const TOUCH_CSS = `
@media (pointer: coarse) {
  .wl-touch button,
  .wl-touch [role="button"],
  .wl-touch summary,
  .wl-touch select {
    min-height: 40px;
  }
  /* Icon-only controls need width as well — an 18px square is the worst case. */
  .wl-touch button:not(:has(> span)):empty,
  .wl-touch button > svg:only-child {
    min-width: 24px;
    min-height: 24px;
  }
  /* Icon-only buttons get width too. The only-child form missed four crew and
     tote remove buttons (measured 22x40) whose svg is the sole ELEMENT child
     but not the sole node, so match first-and-last element instead. */
  .wl-touch button:has(> svg:first-child:last-child),
  .wl-touch [role="button"]:has(> svg:first-child:last-child) {
    min-width: 40px;
  }
  /* Inputs at 16px stop iOS zooming the viewport on focus, which otherwise
     scrolls the form sideways the moment a field is tapped. */
  .wl-touch input,
  .wl-touch textarea {
    font-size: 16px;
    min-height: 40px;
  }
  .wl-touch textarea { min-height: 64px; }
}
`;

const TEXT_INPUT =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-primary/40';

export default function WalkerLog({ dataset = 'routes' }: {
  /** Which half of the log this route shows. Defaults to routes so an old
   *  /walker-log link keeps meaning what it always meant. */
  dataset?: 'routes' | 'addresses';
}) {
  const [date, setDate] = useState(getLocalYMD());
  const [name, setName] = useState('');
  const [day, setDay] = useState<WalkerDay | null>(null);
  // Every walker logged on the SELECTED DATE. The bag pool is
  // (manifest − assigned), and "assigned" must span every walker on that date,
  // not just the one open: without them a bag given to another walker would still look
  // free while logging Craig, and get handed out twice.
  //
  // Scoped to the date and no wider. A bag label is reused on later days
  // carrying different work, so counting yesterday's assignment against today's
  // manifest would hide a bag that is genuinely on the truck this morning.
  const [dayList, setDayList] = useState<WalkerDay[]>([]);
  /** Routes built before a walker took them. Saved immediately on every change
   *  — unlike a walker-day there is no open/save cycle to hang them on, and a
   *  route built at the dock must not be lost by navigating away. */
  const [unclaimed, setUnclaimed] = useState<LogRoute[]>([]);
  /** Today's crew. null = never set for this date, so the seeded roster stands
   *  in; an array = an explicit choice, including a deliberately empty one. */
  const [crew, setCrew] = useState<string[] | null>(null);
  /** Manifests imported from a workbook for this date, one per BTR. These take
   *  precedence over the compile-time seeds: a fixture in the bundle is a
   *  starting point, and what the operator imported this morning is the truth. */
  const [imported, setImported] = useState<StoredManifest[]>([]);
  const [activeBtr, setActiveBtrState] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  /** Which dataset is on screen, fixed by the route that rendered this page.
   *
   *  These are two separate jobs — logging what a walker carried, and profiling
   *  what is at a door — so they get two URLs you can hand to two people.
   *
   *  It was one page with a client-side tab, on the reasoning that a route
   *  change is a full page load over a flaky hotspot. That was true of the dev
   *  server and is NOT true of the deployed site: react-router navigates
   *  BrowserRouter routes client-side, so /walker-log <-> /address-log costs no
   *  network at all, exactly like the tab did. Verified before splitting —
   *  a direct hit on /walker-log returns 200, so CloudFront serves index.html
   *  for unknown paths and a deep link is a real, shareable URL. */
  const tab = dataset;
  const routesTab = dataset === 'routes';
  const [profiles, setProfiles] = useState<AddressProfile[]>([]);
  /** Collection token, remembered per browser so a collector pastes the link
   *  once. localStorage rather than IndexedDB: it is one short string, and it
   *  is NOT data — losing it costs a paste, not a day's work. */
  const [collectToken, setCollectToken] = useState(
    () => localStorage.getItem('walkerlog.collectToken') ?? '',
  );
  const [sending, setSending] = useState(false);
  /** Door keys the campaign has already received, as reported by the server on
   *  this device's own submissions. Seeded from localStorage so the warning
   *  survives a reload. */
  const [known, setKnown] = useState<Set<string>>(() => knownAddresses());
  /** Profile id -> the date the campaign already has it, from the server check.
   *  Absent means "not a duplicate, or not checked". */
  const [dupes, setDupes] = useState<Map<string, string | null>>(new Map());
  /** Profile id currently being checked, so the field can say so. */
  const [checking, setChecking] = useState<string | null>(null);
  /** True when this date was explicitly cleared — suppresses the bundled
   *  fixture so a clear actually sticks. */
  const [cleared, setCleared] = useState(false);
  /** Which importer the dialog opens on. Two buttons open the same dialog, so
   *  the one you pressed must be the tab you land on. */
  const [importTab, setImportTab] = useState<'sheet' | 'crew'>('sheet');
  const [bagQuery, setBagQuery] = useState('');
  const [assignTarget, setAssignTarget] = useState<number | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [dirty, setDirty] = useState(false);
  const [openRoutes, setOpenRoutes] = useState<Set<number>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshSidebar = useCallback(async (d: string) => {
    setDayList(await listByDate(d));
    setUnclaimed(await getUnclaimed(d));
    setCrew(await getCrew(d));
    const ms = await manifestsForDate(d);
    setImported(ms);
    setCleared(await isDateCleared(d));
    setProfiles(await profilesForDate(d));
    const saved = await getActiveBtr(d);
    // Fall back to the first imported truck so a fresh import is immediately
    // usable without a second choice.
    setActiveBtrState(saved && ms.some((m) => m.btr === saved) ? saved : (ms[0]?.btr ?? null));
    setNames(await knownNames());
  }, []);

  /** Unclaimed routes persist on every mutation, so there is no unsaved state
   *  for them to lose. */
  const commitUnclaimed = useCallback(async (d: string, routes: LogRoute[]) => {
    setUnclaimed(routes);
    await putUnclaimed(d, routes);
  }, []);

  useEffect(() => { void refreshSidebar(date); }, [date, refreshSidebar]);

  /** A transient confirmation line. Explicit save needs explicit feedback. */
  const flash = useCallback((msg: string) => {
    setStatus(msg);
    window.setTimeout(() => setStatus((s) => (s === msg ? '' : s)), 2500);
  }, []);

  /** Mutating helper: every edit goes through here so `dirty` can never drift
   *  out of sync with the buffer the way per-field setters would let it. */
  const edit = useCallback((fn: (d: WalkerDay) => WalkerDay) => {
    setDay((prev) => (prev ? fn(structuredClone(prev)) : prev));
    setDirty(true);
  }, []);

  const openDay = useCallback(async (d: string, n: string) => {
    if (!n.trim()) {
      // Says what to DO, not just what is missing. After a crew import the
      // list is full and this field is empty, and "enter a walker name" reads
      // as though the import failed.
      setError('Pick a walker from the crew list, or type a name above.');
      return;
    }
    setError('');
    const existing = await getDay(dayId(d, n));
    const loaded = existing ?? emptyDay(d, n);
    setDay(loaded);
    setName(loaded.name);
    setDirty(!existing);
    setOpenRoutes(new Set(loaded.routes.map((r) => r.route_id)));
  }, []);

  const save = useCallback(async () => {
    if (!day) return;
    try {
      await putDay(day);
      setDirty(false);
      await refreshSidebar(day.date);
      flash('Saved to this browser.');
    } catch {
      setError('Could not write to local storage. Private browsing may block IndexedDB.');
    }
  }, [day, refreshSidebar, flash]);

  const removeDay = useCallback(async (id: string) => {
    if (!window.confirm('Delete this walker-day permanently? This cannot be undone.')) return;
    await deleteDay(id);
    if (day?.id === id) { setDay(null); setDirty(false); }
    await refreshSidebar(date);
  }, [day, date, refreshSidebar]);

  // ── Route mutations ────────────────────────────────────────────────────
  // route_id is a DAY-WIDE identifier and never renumbers. Deleting route 2
  // leaves a gap on purpose: the surviving routes keep the identity they were
  // exported and discussed under, and a route handed to another walker stays
  // the same route.
  const addRoute = () => edit((d) => {
    const others = dayList.filter((x) => x.id !== d.id);
    const next = emptyRoute(nextRouteId([...others, d], unclaimed));
    setOpenRoutes((s) => new Set(s).add(next.route_id));
    return { ...d, routes: [...d.routes, next] };
  });

  const delRoute = (rid: number) => edit((d) => ({
    ...d,
    routes: d.routes.filter((r) => r.route_id !== rid),
  }));

  const patchRoute = (rid: number, patch: Partial<LogRoute>) => edit((d) => ({
    ...d,
    routes: d.routes.map((r) => (r.route_id === rid ? { ...r, ...patch } : r)),
  }));

  const toggleOpen = (rid: number) => setOpenRoutes((s) => {
    const n = new Set(s);
    if (n.has(rid)) n.delete(rid); else n.add(rid);
    return n;
  });

  // ── Manifest bag pool ──────────────────────────────────────────────────
  // Only offered on the date the workbook covers. On any other date there is no
  // manifest, so the pool is simply absent rather than showing bags that are
  // not on that day's truck.
  /** The workbook for the selected date, or null when that date has none.
   *  Everything manifest-shaped keys off this rather than a global constant, so
   *  each date shows its own truck. */
  const seed = useMemo(() => {
    // An imported manifest for the active BTR wins. The bundled seeds remain as
    // a fallback so the fixtures still work with nothing imported.
    const m = imported.find((x) => x.btr === activeBtr);
    if (m) {
      return { btr: m.btr, date: m.date, anchor: m.anchor,
               stops: m.stops, bags: m.bags } as unknown as ReturnType<typeof seedFor>;
    }
    // A cleared date shows nothing, even when a fixture is bundled for it.
    return cleared ? null : seedFor(date);
  }, [date, imported, activeBtr, cleared]);
  const manifestDay = seed !== null;

  /** The day being edited may hold unsaved assignments, so it must override its
   *  stored copy in the pool calculation — otherwise a bag just dropped onto a
   *  route reappears as available until save. */
  const daysForPool = useMemo(() => {
    if (!day) return dayList;
    return [...dayList.filter((d) => d.id !== day.id), day];
  }, [dayList, day]);

  // Unclaimed routes hold real totes off the same truck, so they consume the
  // pool exactly like a walker's route does. Modelled as a nameless pseudo-day
  // fed ONLY to unassignedBags — it never reaches storage, the sidebar or the
  // CSV, so it cannot be mistaken for a walker.
  const pool = useMemo(() => {
    if (!manifestDay) return [];
    const asDay = { ...emptyDay(date, ''), routes: unclaimed };
    return unassignedBags(seed, [...daysForPool, asDay]);
  }, [manifestDay, daysForPool, unclaimed, date]);

  const visiblePool = useMemo(() => {
    const q = bagQuery.trim().toLowerCase();
    if (!q) return pool;
    return pool.filter((b) =>
      b.bag_id.toLowerCase().includes(q) ||
      b.stop.toLowerCase().includes(q) ||
      b.sort_zone.toLowerCase().includes(q));
  }, [pool, bagQuery]);

  /** Stops with at least one unassigned bag, for whole-stop assignment. A stop
   *  whose bags are partly assigned still appears, showing only what is left —
   *  that is what makes a stop splittable rather than all-or-nothing. */
  const poolStops = useMemo(() => {
    const by = new Map<string, SeedBag[]>();
    for (const b of visiblePool) {
      const list = by.get(b.stop) ?? [];
      list.push(b);
      by.set(b.stop, list);
    }
    return [...by.entries()].map(([stop, bags]) => ({ stop, bags }));
  }, [visiblePool]);

  /** Adds bags to a route, ignoring any the route already holds so a
   *  double-click cannot duplicate a tote. */
  const assignBags = useCallback((rid: number, bags: SeedBag[]) => {
    edit((d) => ({
      ...d,
      routes: d.routes.map((r) => {
        if (r.route_id !== rid) return r;
        const have = new Set(r.totes.map((t) => t.bag_id));
        return { ...r, totes: [...r.totes, ...bags.filter((b) => !have.has(b.bag_id)).map(bagToTote)] };
      }),
    }));
  }, [edit]);

  /** Today's crew, resolved.
   *
   *  A saved crew always wins — including an empty one, which is why this tests
   *  `crew !== null` rather than truthiness. With nothing saved, a seeded date
   *  falls back to the manifest roster and any other date starts empty, to be
   *  filled by hand. Anyone already logged on the date is folded in so a walker
   *  can never be logged yet absent from the crew list. */
  const effectiveCrew = useMemo(() => {
    const m = imported.find((x) => x.btr === activeBtr);
    const base = crew !== null ? crew
      : (m && m.crew.length > 0 ? m.crew : (cleared ? [] : crewFor(date)));
    return [...new Set([...base, ...dayList.map((d) => d.name)])];
  }, [crew, date, dayList, imported, activeBtr, cleared]);

  /** Everyone logged on some other date. They are the likely additions to a
   *  later crew — the same faces recur — but they are NOT on this truck until
   *  someone puts them on it. */
  const previousWalkers = useMemo(() => {
    const today = new Set(effectiveCrew.map((n) => n.toLowerCase()));
    return names.filter((n) => !today.has(n.toLowerCase()));
  }, [names, effectiveCrew]);

  /** Is there anything a walker-level clear would remove?
   *
   *  Counts what is ON SCREEN, not just what is stored: on a seeded date the
   *  crew can be non-empty while the stored crew row is [], and a guard that
   *  only looked at storage disabled the very action needed to clear it. */
  const hasWalkerData = dayList.length > 0 || unclaimed.length > 0 || effectiveCrew.length > 0;

  /** Human summary of what a destructive action will remove, so the confirm
   *  names the actual contents rather than saying "everything". */
  const dayContents = useCallback((withManifests: boolean) => {
    const parts = [
      dayList.length && `${dayList.length} walker-day${dayList.length === 1 ? '' : 's'}`,
      unclaimed.length && `${unclaimed.length} unclaimed route${unclaimed.length === 1 ? '' : 's'}`,
      effectiveCrew.length && `the ${effectiveCrew.length}-person crew`,
      withManifests && imported.length && `${imported.length} imported load sheet${imported.length === 1 ? '' : 's'}`,
      // The bundled fixture counts too, and has no stored row to measure. Its
      // absence produced "Delete  for 2026-09-12?" — a confirm naming nothing.
      withManifests && !imported.length && seed && `the ${seed.btr} load sheet`,
    ].filter(Boolean);
    return parts.length ? parts.join(', ') : 'everything';
  }, [dayList, unclaimed, effectiveCrew, imported, seed]);

  /** Clears the PEOPLE — days, unclaimed routes, crew — and keeps the load
   *  sheet. The workbook is still the right workbook when the crew was wrong. */
  const clearWalkersToday = useCallback(async () => {
    if (!window.confirm(
      `Delete ${dayContents(false)} for ${date}?\n\nThe imported load sheet is kept. This cannot be undone.`,
    )) return;
    const r = await clearWalkers(date);
    setDay(null); setName(''); setDirty(false); setError('');
    await refreshSidebar(date);
    flash(`Cleared walkers. ${r.days} day${r.days === 1 ? '' : 's'} removed.`);
  }, [date, dayContents, refreshSidebar, flash]);

  /** Clears EVERYTHING, load sheets included — the date returns to blank. */
  const clearDayToday = useCallback(async () => {
    if (!window.confirm(
      `Delete ${dayContents(true)} for ${date}?\n\nThis removes the imported load sheet too. This cannot be undone.`,
    )) return;
    const r = await clearDate(date);
    setDay(null); setName(''); setDirty(false); setError('');
    await refreshSidebar(date);
    flash(`Cleared ${date}. ${r.days} day${r.days === 1 ? '' : 's'}, ${r.manifests} load sheet${r.manifests === 1 ? '' : 's'}.`);
  }, [date, dayContents, refreshSidebar, flash]);

  const importSheets = useCallback(async (sheets: {
    btr: string; anchor: string; stops: unknown[]; bags: unknown[];
  }[]) => {
    for (const sh of sheets) {
      // Preserve a crew already imported for this BTR — the two importers run
      // independently and in either order, so writing the manifest must not
      // wipe names that came off the screenshot first.
      const prev = imported.find((m) => m.btr === sh.btr);
      await putManifest({
        date, btr: sh.btr, anchor: sh.anchor,
        stops: sh.stops, bags: sh.bags, crew: prev?.crew ?? [],
      });
    }
    if (sheets[0]) await setActiveBtr(date, sheets[0].btr);
    // Importing is the opposite of clearing — lift the tombstone.
    await unclearDate(date);
    await refreshSidebar(date);
    flash(`Imported ${sheets.length} truck${sheets.length === 1 ? '' : 's'}.`);
  }, [date, imported, refreshSidebar, flash]);

  const importCrew = useCallback(async (names: string[]) => {
    // Merge, never replace: a screenshot is one card, and the crew may already
    // hold someone added by hand.
    const merged = [...new Set([...effectiveCrew, ...names])];
    setCrew(merged);
    await putCrew(date, merged);
    await unclearDate(date);
    await refreshSidebar(date);
    // Preselect the first imported walker when nothing is open yet. Without
    // this the crew list is full, the name field is empty, and "Open / start
    // day" errors — which reads as the import having failed.
    if (!name.trim() && names[0]) setName(names[0]);
    flash(`Added ${names.length} to the crew.`);
  }, [date, effectiveCrew, name, refreshSidebar, flash]);

  const saveCrew = useCallback(async (next: string[]) => {
    setCrew(next);
    await putCrew(date, next);
  }, [date]);

  const addToCrew = useCallback((name: string) => {
    const n = name.trim();
    if (!n || effectiveCrew.some((w) => w.toLowerCase() === n.toLowerCase())) return;
    void saveCrew([...effectiveCrew, n]);
  }, [effectiveCrew, saveCrew]);

  /** Removing a walker who has a logged day would orphan that day — it would
   *  still exist, still export, and no longer appear on the crew. So this
   *  refuses, and says why, rather than silently half-removing them. */
  /** Removes ONE walker: their crew entry, and their logged day if they have
   *  one.
   *
   *  It used to refuse when a day existed and tell the user to go delete it
   *  elsewhere — technically safe, and a dead end: the delete lived further
   *  down the sidebar under a heading nothing connected to the message. Doing
   *  the whole removal here is what the × plainly promises; the confirm is what
   *  makes it safe. */
  const removeFromCrew = useCallback(async (name: string) => {
    const theirDay = dayList.find((d) => d.name.toLowerCase() === name.toLowerCase());

    // Confirm EVERY removal, not only when a logged day exists. Removing an
    // unlogged walker silently is still destructive — the crew came off a
    // screenshot and retyping a name is exactly the work the import avoided.
    const n = theirDay?.routes.length ?? 0;
    const what = theirDay
      ? `Remove ${name} and delete their logged day (${n} route${n === 1 ? '' : 's'})?`
      : `Remove ${name} from the crew?`;
    if (!window.confirm(`${what}\n\nThis cannot be undone.`)) return;

    if (theirDay) {
      await deleteDay(theirDay.id);
      if (day?.id === theirDay.id) { setDay(null); setName(''); setDirty(false); }
    }
    setError('');
    await saveCrew(effectiveCrew.filter((w) => w !== name));
    await refreshSidebar(date);
  }, [date, day, dayList, effectiveCrew, saveCrew, refreshSidebar]);

  // ── Address profiles ───────────────────────────────────────────────────
  // Saved on every change, like unclaimed routes: there is no open/save cycle
  // to hang them on, and a profile typed at a door must not be lost by
  // switching tabs.
  const saveProfile = useCallback(async (p: AddressProfile) => {
    setProfiles((ps) => ps.map((x) => (x.id === p.id ? p : x)));
    await putProfile(p);
  }, []);

  const addProfile = useCallback(async () => {
    const p = emptyProfile(date);
    // A stable id before an address exists — otherwise two blank rows collide
    // on `${date}|` and the second overwrites the first.
    p.id = `${date}|new-${Date.now()}`;
    setProfiles((ps) => [...ps, p]);
    await putProfile(p);
  }, [date]);

  /** Saves a profile WITHOUT touching its id.
   *
   *  The id must stay stable while the address is being typed. It used to be
   *  recomputed from the address on every change — and because the form is
   *  keyed by id, each keystroke gave React a "different" component, which it
   *  unmounted and remounted. The input lost focus after exactly one character.
   *
   *  Re-keying happens in `rekeyProfile`, on blur. */
  const commitProfile = useCallback(async (p: AddressProfile) => {
    await saveProfile(p);
  }, [saveProfile]);

  /** Settles a profile's address: re-key it, then ask the campaign about it.
   *
   *  `${date}|address` is what makes revisiting a building an EDIT rather than
   *  a second row, so the re-key still has to happen — just not mid-word.
   */
  const rekeyProfile = useCallback(async (p: AddressProfile) => {
    const want = p.address.trim() ? profileId(p.date, p.address) : p.id;

    let settled = p;
    if (want !== p.id) {
      // An existing profile for this address wins: typing an address that is
      // already recorded should reach that record, not silently replace it
      // with a half-filled duplicate.
      const clash = profiles.find((x) => x.id === want && x.id !== p.id);
      if (clash) {
        setError(`${p.address.trim()} is already recorded. Edit that entry instead.`);
        return;
      }
      await deleteProfile(p.id);
      settled = { ...p, id: want };
      setProfiles((ps) => ps.map((x) => (x.id === p.id ? settled : x)));
      await putProfile(settled);

      // A door profiled on an EARLIER date is not a local clash — re-observing
      // a building later is new information — but it is worth saying so,
      // because the usual reason to retype it is not knowing it was done.
      const earlier = (await allProfiles()).find(
        (x) => x.date !== p.date && doorKey(x.address) === doorKey(p.address),
      );
      if (earlier) flash(`Heads up: this door was already profiled on ${earlier.date}.`);
    }

    if (!settled.address.trim()) return;

    // ADR-417 D7 — ask the CAMPAIGN, not just this device.
    //
    // Collection is a group activity, so the duplicate that matters is a
    // coworker's, and this browser cannot know about it. Without asking, the
    // collector walks to a door somebody already did — repeatedly, because
    // nothing ever tells them.
    //
    // On blur, so it is one request per address entered rather than per
    // keystroke. Fails open by contract (see checkAddress): offline returns
    // `unknown` and entry continues, because a dropped hotspot must not stop
    // data entry. Nothing bad reaches the database either way — the unique
    // constraint still rejects a true duplicate on submit.
    if (!collectToken.trim()) return;
    setChecking(settled.id);
    const verdict = await checkAddress(collectToken, settled.address);
    setChecking((c) => (c === settled.id ? null : c));
    setDupes((m) => {
      const next = new Map(m);
      if (verdict.state === 'known') next.set(settled.id, verdict.collected_on);
      else next.delete(settled.id);
      return next;
    });
  }, [profiles, flash, collectToken]);

  const removeProfile = useCallback(async (id: string) => {
    const p = profiles.find((x) => x.id === id);
    if (p && (p.address.trim() || p.building_type)
      && !window.confirm(`Delete the profile for ${p.address || 'this address'}?`)) return;
    setProfiles((ps) => ps.filter((x) => x.id !== id));
    await deleteProfile(id);
  }, [profiles]);

  /** Profiles out as their own CSV.
   *
   *  A SEPARATE file from the route export, deliberately. The route CSV is one
   *  row per delivery address on a route; this is one row per building. Same
   *  columns at a glance, different grain — merged into one file, neither
   *  imports cleanly. Two files, two tables.
   *
   *  Exports EVERY date, not just the one on screen: a building profile is a
   *  fact about a place, and filtering it by the day it happened to be
   *  collected would drop most of the dataset. */
  const exportProfiles = useCallback(async () => {
    const all = (await allProfiles()).filter(isUsable);
    if (all.length === 0) {
      setError('No complete profiles yet. A profile needs an address and a building type.');
      return;
    }
    all.sort((a, b) => a.address.localeCompare(b.address));
    download(`address-profiles-${getLocalYMD()}.csv`, profilesToCSV(all), 'text/csv');
    flash(`Exported ${all.length} profile${all.length === 1 ? '' : 's'}.`);
  }, [flash]);

  /** Sends complete profiles to the shared collection endpoint.
   *
   *  Local storage is NOT cleared on success. The collector keeps their own
   *  copy — the submission is a copy sent onward, not a handoff — so a server
   *  that later loses the batch does not take the only record with it. */
  const sendProfiles = useCallback(async () => {
    // A door the campaign already has is excluded from the batch. The server
    // would reject a same-day duplicate anyway, but it would ACCEPT one from
    // another date — and re-sending a building a coworker already profiled is
    // the waste this whole check exists to stop.
    const ready = profiles.filter((p) => isUsable(p) && !dupes.has(p.id));
    const held = profiles.filter((p) => isUsable(p) && dupes.has(p.id)).length;
    if (ready.length === 0) {
      setError(
        held > 0
          ? `Nothing new to send. ${held} ${held === 1 ? 'profile is' : 'profiles are'} already collected by this campaign.`
          : 'Nothing complete to send. A profile needs an address and a building type.',
      );
      return;
    }
    setSending(true);
    setError('');
    try {
      const r = await submitProfiles(collectToken.trim(), ready);
      localStorage.setItem('walkerlog.collectToken', collectToken.trim());
      // Remember what the server said was already there, so the next person to
      // type one of these addresses is warned BEFORE walking to it.
      if (r.duplicate_addresses.length > 0) {
        rememberKnown(r.duplicate_addresses);
        setKnown(knownAddresses());
      }
      flash(
        `Sent ${r.accepted}`
        + (r.duplicate ? ` (${r.duplicate} already received)` : '')
        + (held ? `, held back ${held} already collected` : '')
        + '.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send.');
    } finally {
      setSending(false);
    }
  }, [profiles, collectToken, flash, dupes]);

  // ── Build-first routes ─────────────────────────────────────────────────
  // The truck is usually there before the walkers, so a route gets built and
  // loaded and only later does someone pick it up. The walker-first path stays
  // exactly as it was — both orders are real, and which one happens depends on
  // whether the truck or the crew is late.

  const addUnclaimedRoute = useCallback(async () => {
    const r = emptyRoute(nextRouteId(dayList, unclaimed));
    await commitUnclaimed(date, [...unclaimed, r]);
  }, [date, dayList, unclaimed, commitUnclaimed]);

  const patchUnclaimed = useCallback(async (rid: number, patch: Partial<LogRoute>) => {
    await commitUnclaimed(date, unclaimed.map((r) => (r.route_id === rid ? { ...r, ...patch } : r)));
  }, [date, unclaimed, commitUnclaimed]);

  const delUnclaimed = useCallback(async (rid: number) => {
    await commitUnclaimed(date, unclaimed.filter((r) => r.route_id !== rid));
  }, [date, unclaimed, commitUnclaimed]);

  /** Hand an unclaimed route to a walker. The route keeps its number and every
   *  tote; only custody changes. Writes the walker-day straight through rather
   *  than into the edit buffer, so claiming works whether or not that walker is
   *  the one currently open — and cannot be lost by forgetting to save. */
  const claimRoute = useCallback(async (rid: number, walker: string) => {
    const route = unclaimed.find((r) => r.route_id === rid);
    if (!route || !walker.trim()) return;

    const id = dayId(date, walker);
    const target = (await getDay(id)) ?? emptyDay(date, walker);
    if (target.routes.some((r) => r.route_id === rid)) return;

    await putDay({ ...target, routes: [...target.routes, route] });
    await commitUnclaimed(date, unclaimed.filter((r) => r.route_id !== rid));
    await refreshSidebar(date);
    // Keep the open buffer honest: if the claimer is on screen, reload them so
    // the new route appears instead of being overwritten by a stale save.
    if (day && day.id === id) await openDay(date, walker);
    flash(`Route ${rid} → ${walker}.`);
  }, [date, unclaimed, commitUnclaimed, refreshSidebar, day, openDay, flash]);

  /** Move a claimed route to another walker, or back to unclaimed (walker '').
   *  Totes travel with it and the number is untouched, so the pool never
   *  changes and the route stays the same route. */
  const reassignRoute = useCallback(async (rid: number, from: WalkerDay, to: string) => {
    const route = from.routes.find((r) => r.route_id === rid);
    if (!route) return;

    await putDay({ ...from, routes: from.routes.filter((r) => r.route_id !== rid) });

    if (!to.trim()) {
      await commitUnclaimed(date, [...unclaimed, route]);
    } else {
      const id = dayId(date, to);
      const target = (await getDay(id)) ?? emptyDay(date, to);
      if (!target.routes.some((r) => r.route_id === rid)) {
        await putDay({ ...target, routes: [...target.routes, route] });
      }
    }
    await refreshSidebar(date);
    if (day && (day.id === from.id || day.id === dayId(date, to))) {
      await openDay(date, day.name);
    }
    flash(to.trim() ? `Route ${rid} → ${to}.` : `Route ${rid} released.`);
  }, [date, unclaimed, commitUnclaimed, refreshSidebar, day, openDay, flash]);

  // ── Export / import ────────────────────────────────────────────────────
  const exportAll = async (fmt: 'json' | 'csv' | 'xlsx') => {
    const all = await listAll();
    const allUnclaimed = (await listAllUnclaimed()).filter((u) => u.routes.length > 0);
    if (all.length === 0 && allUnclaimed.length === 0) {
      setError('Nothing recorded yet, so nothing to export.'); return;
    }
    all.sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name));
    const stamp = getLocalYMD();

    const dates = [...new Set([...all.map((d) => d.date), ...allUnclaimed.map((u) => u.date)])].sort();

    if (fmt === 'xlsx') {
      // Sections keep each date's unclaimed routes with that date's walkers;
      // one flat call would stamp every leftover with a single date.
      const blob = buildWorkbook(dates.map((d) => ({
        days: all.filter((x) => x.date === d),
        unclaimed: allUnclaimed.find((u) => u.date === d) ?? null,
      })));
      downloadBlob(`walker-log-${stamp}.xlsx`, blob);
    } else if (fmt === 'json') {
      // Profiles ride along. They are a separate dataset, but they are
      // collected on the same phone in the same session — exporting one without
      // the other strands whichever was forgotten.
      const profs = (await allProfiles()).filter(isUsable);
      download(`walker-log-${stamp}.json`,
        JSON.stringify({ days: all, unclaimed: allUnclaimed, profiles: profs }, null, 2),
        'application/json');
    } else {
      // Unclaimed routes are keyed by date, so the CSV is built per date and
      // concatenated — one header, then each date's walkers followed by that
      // date's unclaimed rows. Passing every date's leftovers to a single
      // toCSV call would stamp them all with one date.
      const parts: string[] = [];
      for (const d of dates) {
        const section = toCSV(
          all.filter((x) => x.date === d),
          allUnclaimed.find((u) => u.date === d) ?? null,
        ).split('\n');
        parts.push(...(parts.length === 0 ? section : section.slice(1)));
      }
      download(`walker-log-${stamp}.csv`, parts.join('\n'), 'text/csv');
    }
    const n = all.length;
    const u = allUnclaimed.reduce((sum, x) => sum + x.routes.length, 0);
    flash(`Exported ${n} walker-day${n === 1 ? '' : 's'}${u ? ` + ${u} unclaimed route${u === 1 ? '' : 's'}` : ''}.`);
  };

  const onImport = async (file: File) => {
    try {
      const n = await importJSON(await file.text());
      await refreshSidebar(date);
      flash(`Imported ${n} walker-day${n === 1 ? '' : 's'}.`);
      setError('');
    } catch {
      setError('Could not read that file. Expected a JSON export from this page.');
    }
    if (fileRef.current) fileRef.current.value = '';
  };

  // ── Derived ────────────────────────────────────────────────────────────
  const dayMinutes = useMemo(
    () => (day ? durationMin(day.arrival_time, day.departure_time) : null),
    [day],
  );
  const routedMinutes = useMemo(
    () => (day ? day.routes.reduce((sum, r) => sum + (durationMin(r.route_start, r.route_end) ?? 0), 0) : 0),
    [day],
  );
  const totalRTS = day?.routes.reduce((n, r) => n + r.rts.length, 0) ?? 0;
  const totalTotes = day?.routes.reduce((n, r) => n + r.totes.length, 0) ?? 0;

  return (
    <div className="wl-touch min-h-screen bg-background text-foreground p-4 sm:p-8">
      <style>{TOUCH_CSS}</style>
      <div className="mx-auto max-w-6xl space-y-6">
      <SectionHeader
        eyebrow={routesTab ? 'Route study' : 'Address study'}
        title={routesTab ? 'Walker Route Tracker' : 'Address Profiles'}
        /* DESCRIBES THE CAMPAIGN. Makes no claim about where the data goes.
         *
         * This said "Stored only in this browser — nothing is sent to
         * AsheFlow" while the address page had a submit button on it. That
         * sentence was true when written and became false when ADR-415 landed,
         * and it is the worst kind of thing to be wrong about: a privacy claim
         * rendered to users, who make disclosure decisions from it.
         *
         * A promise about data handling has to be re-verified every time the
         * data path changes, and nothing enforces that. A description of what
         * the page is for does not go stale, so that is what this is. What
         * actually happens to an entry is said at the control that does it —
         * the send box names the campaign it posts to, and the export button
         * is visibly an export. */
        description={
          routesTab ? (
            <>
              What each walker actually carried, and how long it took: totes,
              addresses, OVs, RTS and route times, entered by hand for one day
              at a time. The point is a record to compare against what the
              dispatch system produced for the same day.
            </>
          ) : (
            <>
              What is behind each door and how much work it is: building type,
              workload, hours and access notes, collected one address at a time.
              The point is a picture of the buildings a route actually visits.
            </>
          )
        }
      />

      {/* Export/import sit in their OWN row, not SectionHeader's `actions` slot.
          That slot is wrapped in a `shrink-0` div inside a non-wrapping flex
          row, so these four buttons measured 425px in a 390px viewport whatever
          classes went on the inner element — the whole log scrolled sideways on
          a phone. A sibling row wraps freely. */}
      {/* Two SELF-CONTAINED groups, not one wrapping row.
          A single flex-wrap container let buttons flow across the group
          boundary — on a phone "IMPORT" ended up mid-row after the JSON button
          and "Log JSON" sat beside "Crew" with nothing tying them together, so
          the labels stopped meaning anything. Each group is now its own box:
          its buttons can wrap inside it and never past it.

          Icon direction: lucide's Download arrow points INTO a tray
          (receiving) and Upload points OUT of it (sending). Export sends data
          out, so it takes Upload; Import brings it in, so it takes Download.
          These were inverted. */}
      <div className="grid gap-2 sm:grid-cols-2">
        {([
          {
            key: 'import',
            title: 'Import',
            hint: 'Bring a day in',
            items: [
              { label: 'Load sheet', sub: '.xlsx', icon: FileSpreadsheet, onClick: () => { setImportTab('sheet'); setShowImport(true); } },
              { label: 'Crew', sub: 'screenshot', icon: Camera, onClick: () => { setImportTab('crew'); setShowImport(true); } },
              { label: 'Saved log', sub: '.json', icon: Download, onClick: () => fileRef.current?.click() },
            ],
          },
          {
            key: 'export',
            title: 'Export',
            hint: 'Take this log out',
            // Two datasets, named. They have DIFFERENT GRAINS — the route
            // export is one row per delivery address on a route, the address
            // export is one row per building — so a single unlabelled row of
            // buttons would make "CSV" ambiguous and invite importing one into
            // the other's table.
            items: [
              { group: 'Routes', label: 'Excel', sub: '.xlsx', icon: Upload, onClick: () => void exportAll('xlsx') },
              { group: 'Routes', label: 'CSV', sub: '.csv', icon: Upload, onClick: () => void exportAll('csv') },
              { group: 'Routes', label: 'JSON', sub: '.json', icon: Upload, onClick: () => void exportAll('json') },
              { group: 'Addresses', label: 'CSV', sub: '.csv', icon: Upload, onClick: () => void exportProfiles() },
            ],
          },
        ] as const).map((g) => (
          <section key={g.key} className="rounded-xl border border-border bg-surface/40 p-3">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {g.title}
              </h2>
              <span className="text-[11px] text-muted-foreground/70">{g.hint}</span>
            </div>
            {/* Items carrying a `group` are rendered under that label; the
                rest sit in one unlabelled row. Import has no subgroups, Export
                has two, and one renderer serves both. */}
            {[...new Set(g.items.map((it) => ('group' in it ? it.group : '')))].map((sub) => (
              <div key={sub || 'ungrouped'} className={sub ? 'mt-1.5 first:mt-0' : ''}>
                {sub && (
                  <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {sub}
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {g.items.filter((it) => ('group' in it ? it.group : '') === sub).map((it) => (
                    <button
                      key={`${sub}-${it.label}`} type="button" onClick={it.onClick}
                      className="inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm hover:border-primary/60 hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary/40"
                    >
                      <it.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">{it.label}</span>
                      <span className="shrink-0 text-[10px] text-muted-foreground/70">{it.sub}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {/* The one piece of advice worth keeping from the old header, moved
                to the control it is about. It survives a change in where data
                goes, because it is about this browser losing its copy — which
                is true whether or not anything was ever sent. */}
            {g.key === 'export' && (
              <p className="mt-2 text-[10px] text-muted-foreground/70">
                Worth doing before clearing site data or switching machines.
              </p>
            )}
          </section>
        ))}
      </div>

      <input
        ref={fileRef} type="file" accept="application/json,.json" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void onImport(f); }}
      />

      {showImport && (
        <ImportDialog
          date={date}
          initialTab={importTab}
          onClose={() => setShowImport(false)}
          onImportSheets={importSheets}
          onImportCrew={importCrew}
        />
      )}

      <ErrorBanner message={error || null} />
      {status && (
        <div className="rounded-lg border border-success/40 bg-success/10 px-4 py-2 text-sm text-success">
          {status}
        </div>
      )}

      {/* `min-w-0` on the grid items: a grid item defaults to min-width:auto,
          so a long bag label or address sets a floor wider than the column and
          the whole page scrolls sideways on a phone (measured: 385px content in
          a 382px viewport). Explicit zero lets the content shrink and wrap. */}
      {/* Dataset switch. <Link>, not a button: these are two URLs now, so the
          switcher must produce a real navigation a phone can bookmark, share
          and reload. react-router handles it client-side, so it costs no
          network — the property the tab was chosen for in the first place. */}
      <nav className="flex gap-1 rounded-lg bg-muted p-1">
        {([
          ['routes', '/walker-log', 'Routes', dayList.length],
          ['addresses', '/address-log', 'Addresses', profiles.filter(isUsable).length],
        ] as const).map(([k, to, label, count]) => (
          <Link
            key={k} to={to}
            aria-current={tab === k ? 'page' : undefined}
            className={`flex-1 rounded-md px-3 py-2 text-center text-sm font-medium transition-colors ${
              tab === k ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {label}
            {count > 0 && (
              <span className="ml-1.5 text-[11px] text-muted-foreground">{count}</span>
            )}
          </Link>
        ))}
      </nav>

      {tab === 'addresses' ? (
        <section className="card p-4 space-y-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-sm font-semibold">Address profiles</h2>
              <p className="text-[11px] text-muted-foreground">
                What is at the door, and how much work it is. Collected for {date}.
              </p>
            </div>
            {/* Export is NOT duplicated here — it lives in the page-header
                Export card under an "Addresses" label, so every export on the
                page is found in one place regardless of which tab is open. */}
            <button
              onClick={() => void addProfile()}
              className="btn-secondary text-xs px-2.5 py-1 inline-flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" /> Add address
            </button>
          </div>

          {profiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No addresses yet. Add one, or scan a package label to fill it in.
            </p>
          ) : (
            <div className="space-y-2">
              {profiles.map((p) => (
                <AddressProfileForm
                  key={p.id}
                  profile={p}
                  onChange={(next) => void commitProfile(next)}
                  onAddressCommitted={(next) => void rekeyProfile(next)}
                  onDelete={() => void removeProfile(p.id)}
                  known={known}
                  serverDuplicate={dupes.has(p.id) ? (dupes.get(p.id) ?? '') : null}
                  checking={checking === p.id}
                />
              ))}
            </div>
          )}

          {profiles.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {profiles.filter(isUsable).length} of {profiles.length} complete;
              a profile needs an address and a building type.
            </p>
          )}

          {/* Sending is OPTIONAL and additive (ADR-415 D5). Hidden entirely when
              no collection server is configured, so a purely local deployment
              never shows a control that cannot work. */}
          {submitConfigured() && profiles.some(isUsable) && (
            <div className="rounded-lg border border-border p-3 space-y-2">
              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Collection link
                </label>
                <input
                  value={collectToken}
                  onChange={(e) => setCollectToken(e.target.value)}
                  placeholder="Paste the code you were given"
                  className={`${TEXT_INPUT} mt-1 font-mono text-xs`}
                />
              </div>
              <button
                type="button"
                onClick={() => void sendProfiles()}
                disabled={sending || !collectToken.trim()}
                className="btn-primary w-full text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
              >
                {sending
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending…</>
                  : <><Upload className="w-4 h-4" /> Send {profiles.filter(isUsable).length} to the team</>}
              </button>
              <p className="text-[11px] text-muted-foreground">
                Your entries stay on this device either way. Sending is a copy,
                not a handoff.
              </p>
            </div>
          )}
        </section>
      ) : (

      <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)] items-start [&>*]:min-w-0">
        {/* ── Picker + that date's entries ─────────────────────────────── */}
        <aside className="card p-4 space-y-4">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Date</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${TEXT_INPUT} mt-1`} />
          </div>
          {/* Which truck this date's work belongs to. A workbook holds the
              whole fleet and each BTR has its own bags AND its own crew, so
              switching swaps both. Hidden when only one truck was imported —
              a selector with one option is noise. */}
          {imported.length > 1 && (
            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Truck</label>
              <div className="mt-1">
                <Dropdown
                  value={activeBtr ?? ''}
                  placeholder="Pick a truck"
                  ariaLabel="Active BTR"
                  onChange={(v) => {
                    setActiveBtrState(v);
                    void setActiveBtr(date, v).then(() => refreshSidebar(date));
                  }}
                  options={imported.map((m) => ({
                    value: m.btr,
                    label: m.btr,
                    hint: `${(m.bags as unknown[]).length} bags`,
                  }))}
                />
              </div>
            </div>
          )}

          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Walker</label>
            <input
              list="walker-log-names" value={name} placeholder="Name"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void openDay(date, name); }}
              className={`${TEXT_INPUT} mt-1`}
            />
            <datalist id="walker-log-names">
              {/* Today's crew first, then everyone ever logged — so a walker
                  who returns next week still autocompletes even before they
                  are added to the crew. */}
              {[...new Set([...effectiveCrew, ...names])]
                .map((n) => <option key={n} value={n} />)}
            </datalist>
          </div>

          {/* Today's crew. One tap opens that walker's day instead of retyping
              the name, and a logged walker is ticked so the list doubles as a
              progress board: who is done, who is outstanding.

              Editable on EVERY date, not just seeded ones — that was the gap.
              A seeded date starts from the manifest roster; any other date
              starts empty and gets filled from previous walkers or new names. */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {seed ? `${seed.btr} crew` : 'Crew'} ({effectiveCrew.length})
                {effectiveCrew.length > 0 && (
                  <span className="ml-1 font-normal normal-case tracking-normal text-muted-foreground/70">
                    tap to open a day
                  </span>
                )}
              </p>
              {crew !== null && crewFor(date).length > 0 && (
                <button
                  type="button" onClick={() => void saveCrew([...crewFor(date)])}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                  title="Restore the crew from the manifest"
                >
                  reset
                </button>
              )}
            </div>

            {effectiveCrew.length > 0 && (
              /* A ROSTER, not a chip cloud. The old flat grid of same-sized
                 pills said only "these names exist" — it could not show who is
                 open, who is done, or how much each has logged, which is the
                 whole question at 9am. Each row now carries the walker's route
                 count and a tick when they have a saved day, so the list reads
                 as a progress board. */
              <div className="mb-2 -mx-1 space-y-0.5">
                {effectiveCrew.map((n) => {
                  const theirDay = dayList.find((d) => d.name.toLowerCase() === n.toLowerCase());
                  const logged = !!theirDay;
                  const open = day?.name.toLowerCase() === n.toLowerCase();
                  return (
                    <div
                      key={n}
                      className={`group flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${
                        open ? 'bg-primary/10 ring-1 ring-primary/30' : 'hover:bg-muted'
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold ${
                          logged ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground'
                        }`}
                      >
                        {logged ? <Check className="h-3 w-3" /> : n.trim().charAt(0).toUpperCase()}
                      </span>

                      <button
                        type="button"
                        onClick={() => { setName(n); void openDay(date, n); }}
                        className="min-w-0 flex-1 cursor-pointer truncate text-left"
                        title={`Open ${n}'s day`}
                      >
                        <span className={open ? 'font-semibold' : ''}>{n}</span>
                      </button>

                      {theirDay && theirDay.routes.length > 0 && (
                        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                          {theirDay.routes.length} rt
                        </span>
                      )}

                      <button
                        type="button" onClick={() => void removeFromCrew(n)}
                        title={logged ? `Remove ${n} and delete their day` : `Remove ${n} from the crew`}
                        className="shrink-0 rounded-md p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-danger focus:opacity-100 group-hover:opacity-100"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            <WalkerPicker
              crew={[]} previous={[...previousWalkers]}
              placeholder="Add a walker to the crew"
              onPick={(n) => { addToCrew(n); setName(n); }}
              onAddToCrew={addToCrew}
            />
          </div>
          {/* Disabled until a name is typed. The crew list below is the normal
              way in — tapping a name opens that walker's day directly — and a
              live button that only ever errors is worse than one that is
              visibly waiting for input. */}
          <button
            onClick={() => void openDay(date, name)}
            disabled={!name.trim()}
            title={name.trim() ? undefined : 'Type a name, or tap someone in the crew list'}
            className="btn-primary w-full text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
          >
            <Footprints className="w-4 h-4" /> Open / start day
          </button>
          {!name.trim() && effectiveCrew.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              Tap a walker below to open their day.
            </p>
          )}

          <div className="pt-2 border-t border-border">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                On {date} ({dayList.length})
              </p>
              {/* Clears the whole date in one action. Deleting walkers one at a
                  time is right for a single mistake and wrong for "start this
                  day over" — and the crew-removal error sends you here, so the
                  bulk action has to be here too. */}
              {/* Three levels of destruction, each with its own reach:
                    per-walker trash (below) — one person
                    Clear walkers          — every person, load sheet kept
                    Clear day              — everything, load sheet included */}
              {/* ALWAYS rendered, disabled when there is nothing to remove.
                  They used to be hidden unless a stored row existed — and on a
                  SEEDED date that hid them at exactly the wrong moment: the
                  first clear emptied the stored rows, the buttons vanished, and
                  the compile-time seed kept supplying 34 bags and an 8-person
                  crew that could no longer be cleared. A control that
                  disappears mid-task reads as a broken feature. */}
              <div className="flex items-center gap-2">
                <button
                  type="button" onClick={() => void clearWalkersToday()}
                  disabled={!hasWalkerData}
                  title={hasWalkerData ? 'Delete every walker, keep the load sheet' : 'No walkers to clear'}
                  className="text-[11px] text-muted-foreground hover:text-danger disabled:opacity-40 disabled:hover:text-muted-foreground"
                >
                  Clear walkers
                </button>
                <button
                  type="button" onClick={() => void clearDayToday()}
                  /* `seed` covers the BUNDLED fixture too, not just imports.
                     Checking imported.length alone disabled this on a seeded
                     date whose stored rows were already empty — the exact case
                     where the fixture was still showing 34 bags. */
                  disabled={!hasWalkerData && imported.length === 0 && !seed}
                  title="Delete everything for this date, load sheet included"
                  className="text-[11px] text-muted-foreground hover:text-danger disabled:opacity-40 disabled:hover:text-muted-foreground"
                >
                  Clear day
                </button>
              </div>
            </div>
            {dayList.length === 0 ? (
              <p className="text-sm text-muted-foreground">No walkers logged.</p>
            ) : (
              <ul className="space-y-1">
                {dayList.map((d) => (
                  <li key={d.id} className="flex items-center gap-1">
                    <button
                      onClick={() => void openDay(d.date, d.name)}
                      className={`flex-1 text-left rounded-md px-2 py-1.5 text-sm hover:bg-muted ${day?.id === d.id ? 'bg-muted font-medium' : ''}`}
                    >
                      {d.name}
                      <span className="text-muted-foreground"> · {d.routes.length} rt</span>
                    </button>
                    <button onClick={() => void removeDay(d.id)} title="Delete walker-day" className="p-1.5 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <div className="space-y-6">
        {/* Built-but-unclaimed routes. Above the walker editor because at the
            dock this is the first thing that happens: routes exist before the
            crew does. */}
        {(unclaimed.length > 0 || manifestDay) && (
          <UnclaimedRoutes
            routes={unclaimed}
            pool={pool}
            crew={effectiveCrew}
            previous={previousWalkers}
            onAddToCrew={addToCrew}
            onAdd={() => void addUnclaimedRoute()}
            onPatch={(rid, p) => void patchUnclaimed(rid, p)}
            onDelete={(rid) => void delUnclaimed(rid)}
            onClaim={(rid, w) => void claimRoute(rid, w)}
          />
        )}

        {/* ── The day being edited ─────────────────────────────────────── */}
        {!day ? (
          <div className="card p-10 text-center text-muted-foreground">
            <Footprints className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm">Pick a date and walker, then <strong>Open / start day</strong>.</p>
            <p className="text-xs mt-1">An existing entry opens for editing; a new name starts a fresh day.</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="card p-5 space-y-4">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                  <h2 className="text-lg font-semibold">{day.name}</h2>
                  <p className="text-sm text-muted-foreground">{day.date}</p>
                </div>
                <button
                  onClick={() => void save()} disabled={!dirty}
                  className="btn-primary text-sm inline-flex items-center gap-1.5 disabled:opacity-40"
                >
                  <Save className="w-4 h-4" /> {dirty ? 'Save' : 'Saved'}
                </button>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <TimeField
                  label="Arrival" value={day.arrival_time} resetKey={day.id}
                  hint="Reached the AP"
                  onChange={(v) => edit((d) => ({ ...d, arrival_time: v }))}
                  onNow={() => edit((d) => ({ ...d, arrival_time: nowHM() }))}
                />
                <TimeField
                  label="Departure" value={day.departure_time} resetKey={day.id}
                  hint="Left for the day"
                  onChange={(v) => edit((d) => ({ ...d, departure_time: v }))}
                  onNow={() => edit((d) => ({ ...d, departure_time: nowHM() }))}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-border">
                <Stat label="Routes" value={String(day.routes.length)} />
                <Stat label="On clock" value={fmtDuration(dayMinutes)} />
                <Stat
                  label="On route"
                  value={fmtDuration(routedMinutes || null)}
                  hint={dayMinutes ? `${Math.round((routedMinutes / dayMinutes) * 100)}% of day` : undefined}
                />
                <Stat label="Totes · RTS" value={`${totalTotes} · ${totalRTS}`} />
              </div>
            </div>

            {day.routes.map((r) => (
              <RouteCard
                key={r.route_id}
                route={r}
                open={openRoutes.has(r.route_id)}
                onToggle={() => toggleOpen(r.route_id)}
                onDelete={() => delRoute(r.route_id)}
                onPatch={(p) => patchRoute(r.route_id, p)}
                /* `pool` already excludes every assigned bag INCLUDING this
                   route's own, so a bag cannot be offered twice anywhere. The
                   card adds its own totes back for its selects to display. */
                pool={pool}
                crew={effectiveCrew.filter((w) => w !== day.name)}
                previous={previousWalkers}
                onAddToCrew={addToCrew}
                onReassign={(to) => void reassignRoute(r.route_id, day, to)}
              />
            ))}

            <button onClick={addRoute} className="btn-secondary w-full text-sm inline-flex items-center justify-center gap-1.5 py-3">
              <Plus className="w-4 h-4" /> Add route {day.routes.length + 1}
            </button>

            {manifestDay && (
              <BagPool
                btr={seed.btr}
                total={seed.bags.length}
                pool={pool}
                stops={poolStops}
                query={bagQuery}
                onQuery={setBagQuery}
                routes={day.routes}
                target={assignTarget}
                onTarget={setAssignTarget}
                onAssign={assignBags}
              />
            )}
          </div>
        )}
        </div>
      </div>
      )}
      </div>
    </div>
  );
}

/* ── Small presentational pieces ─────────────────────────────────────── */

/** Routes built before anyone picked them up.
 *
 *  This is the general case at the dock: the truck arrives, routes get built
 *  and loaded, and walkers claim them as they show up. The walker-first path
 *  (open a walker, add routes under them) still exists unchanged for the
 *  reverse — crew waiting on a late truck.
 *
 *  Deliberately a THIN editor: totes, times and difficulty, no arrival or
 *  departure, because those belong to a person and this route has none yet.
 *  Everything else about the route is filled in after it is claimed.
 */
function UnclaimedRoutes({ routes, pool, crew, previous, onAddToCrew, onAdd, onPatch, onDelete, onClaim }: {
  routes: LogRoute[];
  pool: SeedBag[];
  crew: string[];
  previous: string[];
  onAddToCrew: (name: string) => void;
  onAdd: () => void;
  onPatch: (rid: number, p: Partial<LogRoute>) => void;
  onDelete: (rid: number) => void;
  onClaim: (rid: number, walker: string) => void;
}) {
  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold text-sm inline-flex items-center gap-1.5">
            <Route className="w-4 h-4" /> Unclaimed routes
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {routes.length === 0
              ? 'Build routes now, hand them to walkers as they arrive.'
              : `${routes.length} built, waiting for a walker.`}
          </p>
        </div>
        <button onClick={onAdd} className="btn-secondary text-xs px-2.5 py-1 inline-flex items-center gap-1.5" type="button">
          <Plus className="w-3.5 h-3.5" /> Build route
        </button>
      </div>

      {/* By number, so a released route returns to its place on the board
          rather than to the bottom of the list. */}
      {[...routes].sort((a, b) => a.route_id - b.route_id).map((r) => {
        const m = manifestLoad(r);
        return (
          <div key={r.route_id} className="rounded-lg border border-border p-3 space-y-2.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm">Route {r.route_id}</span>
              <span className="text-xs text-muted-foreground">
                {r.totes.length} tote{r.totes.length === 1 ? '' : 's'}
                {m.packages !== null && ` · ~${m.packages} pkg · ${m.stops.join(', ')}`}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={() => onDelete(r.route_id)} type="button"
                  title="Delete route. Its totes return to the pool."
                  className="p-1.5 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Full tote editor, addresses included. A route is usually built
                and addressed BEFORE anyone claims it — the truck arrives first
                — so deferring address entry to the claimed card would mean
                holding the addresses in your head until a walker turns up. */}
            <ToteList
              totes={r.totes}
              pool={pool}
              onChange={(totes) => onPatch(r.route_id, { totes })}
              dense
            />

            <OVList
              ovs={r.ovs ?? []}
              expected={m.ovs}
              onChange={(ovs) => onPatch(r.route_id, { ovs })}
            />

            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground shrink-0">Claimed by</span>
              <div className="flex-1 min-w-0">
                <WalkerPicker
                  crew={crew} previous={previous}
                  placeholder="Pick a walker"
                  onPick={(w) => onClaim(r.route_id, w)}
                  onAddToCrew={onAddToCrew}
                />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}


/** The day's unassigned bags, grouped by their manifest stop.
 *
 *  Stops are assignable as a unit AND splittable: "Assign all" takes the whole
 *  stop, each bag row takes one. That matters because a stop is the manifest's
 *  grouping, not the walker's — WE111 is four bags and 84 packages, which two
 *  walkers may well split, and a whole-stop-only control would force that to be
 *  recorded as a lie.
 *
 *  The pool is derived, so a bag removed from a route reappears here on its own.
 */
function BagPool({ btr, total, pool, stops, query, onQuery, routes, target, onTarget, onAssign }: {
  btr: string;
  total: number;
  pool: SeedBag[];
  stops: { stop: string; bags: SeedBag[] }[];
  query: string;
  onQuery: (v: string) => void;
  routes: LogRoute[];
  target: number | null;
  onTarget: (r: number | null) => void;
  onAssign: (rid: number, bags: SeedBag[]) => void;
}) {
  // Default to the last route — the one just added is nearly always the one
  // being filled — but never invent a target when there are no routes yet.
  const effective = target !== null && routes.some((r) => r.route_id === target)
    ? target
    : routes.length > 0 ? routes[routes.length - 1].route_id : null;

  const assigned = total - pool.length;

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold text-sm inline-flex items-center gap-1.5">
            <Layers className="w-4 h-4" /> {btr} bags
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {pool.length} unassigned · {assigned} of {total} placed across all walkers today
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Assign to</span>
          <Dropdown
            className="w-40"
            value={effective !== null ? String(effective) : ''}
            placeholder={routes.length === 0 ? 'Add a route first' : 'Route'}
            ariaLabel="Assign totes to route"
            disabled={routes.length === 0}
            onChange={(v) => onTarget(v ? Number(v) : null)}
            align="right"
            options={routes.map((r) => ({
              value: String(r.route_id),
              label: `Route ${r.route_id}`,
              hint: `${r.totes.length} tote${r.totes.length === 1 ? '' : 's'}`,
            }))}
          />
        </div>
      </div>

      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          value={query} onChange={(e) => onQuery(e.target.value)}
          placeholder="Filter by bag, stop (WE93) or sort zone (A-16.3E)"
          className={`${TEXT_INPUT} pl-9`}
        />
      </div>

      {pool.length === 0 ? (
        <p className="text-sm text-success">All {total} bags assigned.</p>
      ) : stops.length === 0 ? (
        <p className="text-sm text-muted-foreground">No bags match “{query}”.</p>
      ) : (
        <div className="max-h-[26rem] overflow-y-auto pr-1 space-y-2">
          {stops.map(({ stop, bags }) => {
            const b0 = bags[0];
            const partial = bags.length < b0.stop_bag_count;
            return (
              <div key={stop} className="rounded-lg border border-border p-2.5">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">
                      {stop}
                      {partial && (
                        <span className="ml-1.5 text-[11px] font-normal text-warning">
                          split · {bags.length} of {b0.stop_bag_count} left
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {b0.stop_package_count} pkg · {b0.stop_ov_count} OV
                    </p>
                  </div>
                  <button
                    type="button" disabled={effective === null}
                    onClick={() => effective !== null && onAssign(effective, bags)}
                    className="btn-secondary text-xs px-2 py-1 shrink-0 disabled:opacity-40"
                  >
                    Assign all {bags.length}
                  </button>
                </div>
                <div className="space-y-1">
                  {bags.map((b) => (
                    <button
                      key={b.bag_id} type="button" disabled={effective === null}
                      onClick={() => effective !== null && onAssign(effective, [b])}
                      className="w-full flex items-center gap-2 text-left rounded-md px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-40 disabled:hover:bg-transparent"
                    >
                      <CornerDownLeft className="w-3 h-3 text-muted-foreground shrink-0" />
                      <span className="font-medium">{b.bag_id}</span>
                      <span className="text-muted-foreground ml-auto">{b.sort_zone}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-base font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** A timestamp field: one tap to stamp it, always editable afterwards.
 *
 *  EMPTY is a single "Stamp now" button — the live path is the common one, so
 *  it is the obvious one. Typing a time by hand is reached by clicking the same
 *  control's pencil, not by a permanent "or set manually" link cluttering every
 *  field.
 *
 *  SET is the time itself, large and legible, with the edit and clear actions
 *  revealed on hover/focus rather than parked on screen. A stamped time must
 *  stay correctable — the walker arrived while you were busy and the stamp is
 *  five minutes late — but the correction is rare and should not outweigh the
 *  value it is correcting.
 *
 *  `manual` RESETS when the value changes identity. Without that reset the flag
 *  survived switching walkers (React reuses the component instance at the same
 *  position), leaving Arrival showing an empty input plus a "clear" link for a
 *  value that did not exist — visible in the 2026-09-12 screenshots.
 */
function TimeField({ label, value, onChange, onNow, hint, resetKey }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onNow: () => void;
  hint?: string;
  /** Changes when the field is pointed at a different record. */
  resetKey?: string;
}) {
  const [manual, setManual] = useState(false);

  // Point at a different walker/route and the hand-entry state is stale.
  useEffect(() => { setManual(false); }, [resetKey]);

  const empty = !value;
  const editing = manual || !empty;

  return (
    <div className="min-w-0">
      <label className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </label>

      {!editing ? (
        <button
          type="button" onClick={onNow}
          className="mt-1.5 w-full group inline-flex items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-transparent px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:border-primary/60 hover:bg-primary/5 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
        >
          <Clock className="w-4 h-4 transition-transform group-hover:scale-110" />
          Stamp now
          <span
            role="button" tabIndex={0}
            onClick={(e) => { e.stopPropagation(); setManual(true); }}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); setManual(true); } }}
            title={`Type ${label.toLowerCase()} by hand`}
            className="ml-auto rounded-md p-1 text-muted-foreground/70 hover:bg-muted hover:text-foreground"
          >
            <Pencil className="w-3.5 h-3.5" />
          </span>
        </button>
      ) : (
        <div className="mt-1.5 group flex items-center gap-1.5 rounded-xl border border-border bg-surface px-2.5 py-1.5 focus-within:ring-2 focus-within:ring-primary/40">
          <Clock className="w-4 h-4 text-muted-foreground shrink-0" />
          <input
            type="time" value={value} autoFocus={manual && empty}
            onChange={(e) => onChange(e.target.value)}
            aria-label={label}
            className="min-w-0 flex-1 bg-transparent py-1 text-base tabular-nums outline-none"
          />
          <button
            type="button" onClick={onNow}
            title={`Re-stamp ${label.toLowerCase()} as now`}
            className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus:opacity-100 group-hover:opacity-100"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => { onChange(''); setManual(false); }}
            title={`Clear ${label.toLowerCase()}`}
            className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-danger/10 hover:text-danger focus:opacity-100 group-hover:opacity-100"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function RouteCard({ route, open, onToggle, onDelete, onPatch, pool, crew, previous, onAddToCrew, onReassign }: {
  route: LogRoute;
  open: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onPatch: (p: Partial<LogRoute>) => void;
  /** Bags no route has claimed today. ToteList adds this route's own totes back
   *  so each row's dropdown can render its current value. */
  pool: SeedBag[];
  /** Other walkers this route could be handed to. '' releases it. */
  crew: string[];
  previous: string[];
  onAddToCrew: (name: string) => void;
  onReassign: (to: string) => void;
}) {
  const mins = durationMin(route.route_start, route.route_end);
  const addressCount = route.totes.reduce((n, t) => n + t.addresses.length, 0);
  const m = manifestLoad(route);

  // A route is one of three things, and the header should say which without
  // being read word by word: not started, running, or finished.
  const status = !route.route_start ? 'pending' : !route.route_end ? 'running' : 'done';

  return (
    /* NO overflow-hidden — it clips the tote dropdown inside ToteList the
       same way it clipped the building-type list on the Addresses tab. A
       clipping box cannot be escaped with z-index. Nothing here scrolls;
       the padding keeps the corners clean on its own. */
    <div className={`card transition-shadow ${status === 'running' ? 'ring-1 ring-primary/30' : ''}`}>
      <div className="flex items-center gap-3 p-4">
        <button onClick={onToggle} className="p-1 rounded-md hover:bg-muted shrink-0" type="button" aria-expanded={open}>
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-sm">Route {route.route_id}</span>
            {/* The live route is the one that needs an action, so it is the one
                that gets colour. A finished route recedes. */}
            {status === 'running' && (
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" /> On route
              </span>
            )}
            {status === 'done' && mins !== null && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {fmtDuration(mins)}
              </span>
            )}
            {route.difficulty && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                {route.difficulty}
              </span>
            )}
          </div>

          {/* Counts as separate units rather than one dash-joined sentence —
              "0 totes / 0 addr" read as noise in the 09-12 screenshots. */}
          {/* flex-wrap + whitespace-nowrap: on a phone this row collapsed into a
              vertical column of stray dashes, because "--:-- → --:--" was being
              broken between its own characters. */}
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <span className="whitespace-nowrap tabular-nums">
              {route.route_start || '--:--'} → {route.route_end || '--:--'}
            </span>
            <span className="whitespace-nowrap tabular-nums">{route.totes.length} totes</span>
            <span className="whitespace-nowrap tabular-nums">{addressCount} addr</span>
            {(route.ovs ?? []).length > 0 && (
              <span className="whitespace-nowrap tabular-nums">{(route.ovs ?? []).length} OV</span>
            )}
            {route.rts.length > 0 && (
              <span className="whitespace-nowrap tabular-nums text-warning">{route.rts.length} RTS</span>
            )}
          </div>

          {m.packages !== null && (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground/80">
              manifest ~{m.packages} pkg · ~{m.ovs} OV · {m.stops.join(', ')}
              {m.splitStops.length > 0 && ` · split ${m.splitStops.join(', ')}`}
            </p>
          )}
        </div>

        {/* One primary action, matching the route's state. Previously a
            "Start now" button sat beside a "— → —" summary and a separate
            "Stamp now" field inside, three controls for one timestamp. */}
        {status === 'pending' && (
          <button
            onClick={() => onPatch({ route_start: nowHM() })} type="button"
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:brightness-110"
          >
            <Clock className="w-3.5 h-3.5" /> Start
          </button>
        )}
        {status === 'running' && (
          <button
            onClick={() => onPatch({ route_end: nowHM() })} type="button"
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
          >
            <Clock className="w-3.5 h-3.5" /> End
          </button>
        )}

        <button onClick={onDelete} title="Delete route" className="p-1.5 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10 shrink-0" type="button">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {open && (
        <div className="border-t border-border p-4 space-y-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <TimeField
              label="Route start" value={route.route_start} resetKey={String(route.route_id)}
              onChange={(v) => onPatch({ route_start: v })} onNow={() => onPatch({ route_start: nowHM() })} />
            <TimeField
              label="Route end" value={route.route_end} resetKey={String(route.route_id)}
              onChange={(v) => onPatch({ route_end: v })} onNow={() => onPatch({ route_end: nowHM() })} />
            <DifficultyPicker
              value={route.difficulty}
              onChange={(v) => onPatch({ difficulty: v })}
            />
          </div>

          {/* Same editor the unclaimed builder uses — one implementation, so
              the two paths cannot drift. */}
          <ToteList
            totes={route.totes}
            pool={pool}
            onChange={(totes) => onPatch({ totes })}
          />

          <OVList
            ovs={route.ovs ?? []}
            expected={m.ovs}
            onChange={(ovs) => onPatch({ ovs })}
          />

          {/* RTS — one card per returned package: TBA, a code from the system's
              own RTS_TYPES, and free text.

              Was three inputs crammed on one line with a "— code —" select so
              narrow the reasons were unreadable, which is why it was hard to
              find and harder to fill. Now each package is its own labelled
              block, and the reattemptable flag is shown because it is what
              decides whether the package goes back out today. */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground inline-flex items-center gap-1.5">
                <RotateCcw className="w-3.5 h-3.5" /> RTS
                {route.rts.length > 0 && (
                  <span className="normal-case tracking-normal text-muted-foreground">
                    · {route.rts.length} package{route.rts.length === 1 ? '' : 's'}
                  </span>
                )}
              </h4>
              <button
                onClick={() => onPatch({ rts: [...route.rts, { tba: '', code: '', reason: '' }] })}
                className="btn-secondary text-xs px-2.5 py-1 inline-flex items-center gap-1.5" type="button"
              >
                <Plus className="w-3.5 h-3.5" /> Add RTS package
              </button>
            </div>

            {route.rts.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Nothing returned. Add a package for each TBA that came back.
              </p>
            )}

            {route.rts.map((x, xi) => {
              const spec = RTS_CODES.find((c) => c.value === x.code);
              const patchRts = (patch: Partial<typeof x>) =>
                onPatch({ rts: route.rts.map((v, i) => (i === xi ? { ...v, ...patch } : v)) });
              return (
                <div key={xi} className="rounded-lg border border-border p-3 space-y-2">
                  <div className="flex gap-2 items-center">
                    <span className="text-[11px] font-semibold text-muted-foreground shrink-0 w-8">
                      #{xi + 1}
                    </span>
                    <input
                      value={x.tba} placeholder="TBA (e.g. TBA303912...)"
                      onChange={(e) => patchRts({ tba: e.target.value })}
                      className={`${TEXT_INPUT} font-mono text-xs`}
                    />
                    <button
                      onClick={() => onPatch({ rts: route.rts.filter((_, i) => i !== xi) })}
                      className="p-2 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10 shrink-0" type="button"
                      title="Remove this RTS package"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Scanner on its OWN row, not beside the TBA input.
                      Inside that flex row its results panel — two labelled
                      inputs, a candidate list, warnings — could not shrink, so
                      it pushed the row wider than the card and everything to
                      the right of the address field was clipped. */}
                  <LabelScanner
                    compact
                    onAccept={({ tba }) => { if (tba) patchRts({ tba }); }}
                  />

                  <div>
                    <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      Reason code
                    </label>
                    <div className="mt-1">
                      <Dropdown
                        value={x.code}
                        placeholder="Pick a reason"
                        ariaLabel="RTS reason code"
                        onChange={(v) => patchRts({ code: v })}
                        options={RTS_CODES.map((c) => ({
                          value: c.value,
                          label: c.label,
                          // The consequence, not a restatement of the label —
                          // it is what decides whether the package goes back
                          // out today, and it is the reason the code matters.
                          description: c.reattemptable
                            ? 'Reattemptable, can go back out the same day'
                            : 'Not reattemptable, returns to station',
                        }))}
                      />
                    </div>
                    {spec && (
                      <p className="text-[11px] mt-1 text-muted-foreground">
                        {spec.reattemptable
                          ? 'Reattemptable. Can go back out the same day.'
                          : 'Not reattemptable. Returns to station.'}
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      What happened
                    </label>
                    <textarea
                      rows={2} value={x.reason}
                      placeholder="Free text: the explanation in the walker's words"
                      onChange={(e) => patchRts({ reason: e.target.value })}
                      className={`${TEXT_INPUT} mt-1`}
                    />
                  </div>
                </div>
              );
            })}
          </section>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Notes</label>
            <textarea
              rows={2} value={route.notes} placeholder="Anything worth remembering about this route"
              onChange={(e) => onPatch({ notes: e.target.value })}
              className={`${TEXT_INPUT} mt-1`}
            />
          </div>

          {/* Custody, not identity: the route keeps its number and its totes.
              Reassign covers a walker going home mid-day; release puts it back
              on the board for whoever picks it up next. */}
          <div className="flex items-center gap-2 pt-1 border-t border-border">
            <span className="text-xs text-muted-foreground shrink-0">Hand off</span>
            <div className="flex-1 min-w-0">
              <WalkerPicker
                crew={crew} previous={previous}
                placeholder="Keep with this walker"
                onPick={onReassign}
                onAddToCrew={onAddToCrew}
                align="right"
              />
            </div>
            <button
              type="button" onClick={() => onReassign('')}
              className="btn-secondary text-xs px-2.5 py-1.5 shrink-0"
              title="Put this route back on the unclaimed board"
            >
              Release
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
