// ADR-512: the stolen-package report's labels, defaults and value helpers,
// shared by the form and the version comparison.
import { getLocalYMD } from './date';
import type { StolenPackageFields, StolenPackageVersion } from '../api/types';

export const TBA_RE = /^TBA\d{12}$/;
export const MAX_TBAS = 50;

/** The report's own labels, in its own order. Used by the form and the comparison. */
export const FIELD_LABELS: Record<keyof StolenPackageFields, string> = {
  incident_date: 'Date of incident',
  incident_address: 'Incident Address',
  anchor_point_address: 'Anchor Point Address',
  incident_time: 'Time of incident',
  lmet_called: 'Was LMET called?',
  lmet_case_number: 'LMET Case Number',
  bike_locks_used: 'Were bike locks used to anchor totes?',
  cart_cover_used: 'Was a cart cover being used?',
  totes_stolen: 'How many totes were stolen?',
  cart_stolen: 'Was the cart stolen?',
  packages_stolen: 'Number of stolen packages',
  tbas: 'TBAs stolen',
  summary: 'Incident Summary',
};

export function emptyReport(): StolenPackageFields {
  // The owner's defaults: LMET N, bike locks Y, cart cover Y, cart stolen N.
  return {
    incident_date: getLocalYMD(), incident_time: null, incident_address: '',
    anchor_point_address: null, lmet_called: false, lmet_case_number: null,
    bike_locks_used: true, cart_cover_used: true, totes_stolen: 0, cart_stolen: false,
    packages_stolen: 0, tbas: [], summary: '',
  };
}

export function fieldsOf(v: StolenPackageVersion): StolenPackageFields {
  const { incident_date, incident_time, incident_address, anchor_point_address, lmet_called,
    lmet_case_number, bike_locks_used, cart_cover_used, totes_stolen, cart_stolen,
    packages_stolen, tbas, summary } = v;
  return { incident_date, incident_time: incident_time ? incident_time.slice(0, 5) : null,
    incident_address: incident_address ?? '', anchor_point_address, lmet_called, lmet_case_number,
    bike_locks_used, cart_cover_used, totes_stolen, cart_stolen, packages_stolen,
    tbas: tbas ?? [], summary };
}

/** Splits typed or pasted text into TBAs: commas, spaces and newlines all separate. */
export function splitTbas(raw: string): string[] {
  return raw.split(/[\s,;]+/).map(t => t.trim().toUpperCase()).filter(Boolean);
}

export function displayValue(field: keyof StolenPackageFields, v: unknown): string {
  if (v === null || v === undefined || v === '') return 'blank';
  if (typeof v === 'boolean') return v ? 'Y' : 'N';
  if (Array.isArray(v)) return v.length ? v.join(', ') : 'none';
  if (field === 'incident_time' && typeof v === 'string') return v.slice(0, 5);
  return String(v);
}

