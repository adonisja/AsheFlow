import React, { useEffect, useMemo, useRef, useState } from 'react';
import { GoogleMapsOverlay } from '@deck.gl/google-maps';
import { PolygonLayer } from '@deck.gl/layers';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { CompanyZone } from '../api/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ZonePolygon {
  id: string;
  truck_id: string;
  zone_label: string;
  truck_polygon: { lat: number; lng: number }[];
  tote_count?: number | null;
  package_count?: number;
}

export interface Centroid {
  centroid_lat: number;
  centroid_lng: number;
  package_count: number;
  truck_zone_label: string | null;
}

export interface AnchorPin {
  truck_id: string;
  truck_name: string;
  lat: number;
  lng: number;
  which: 1 | 2; // primary or secondary anchor
}

export interface OutlierToteMarker {
  tote_id: string;
  centroid_lat: number | null;
  centroid_lng: number | null;
  package_count: number;
}

interface Props {
  zones: ZonePolygon[];
  centroids: Centroid[];
  companyZone?: CompanyZone | null;
  anchors?: AnchorPin[];
  outlierTotes?: OutlierToteMarker[];
  className?: string;
}

// ---------------------------------------------------------------------------
// Zone colour palette — keyed by truck so a truck keeps its colour day-to-day
// ---------------------------------------------------------------------------

const ZONE_COLORS: [number, number, number, number][] = [
  [99,  102, 241, 60],   // indigo
  [16,  185, 129, 60],   // emerald
  [245, 158,  11, 60],   // amber
  [239,  68,  68, 60],   // red
  [6,   182, 212, 60],   // cyan
  [168,  85, 247, 60],   // purple
  [236,  72, 153, 60],   // pink
  [20,  184, 166, 60],   // teal
];

const ZONE_STROKE_COLORS: [number, number, number, number][] = [
  [99,  102, 241, 200],
  [16,  185, 129, 200],
  [245, 158,  11, 200],
  [239,  68,  68, 200],
  [6,   182, 212, 200],
  [168,  85, 247, 200],
  [236,  72, 153, 200],
  [20,  184, 166, 200],
];

const OUTLIER_RED: [number, number, number, number] = [220, 38, 38, 235];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function polygonToCoords(pts: { lat: number; lng: number }[]): [number, number][] {
  return pts.map(p => [p.lng, p.lat]);
}

function centroidRadius(count: number): number {
  // Scale dot radius from 50m (1 pkg) to 300m (100+ pkgs)
  return Math.min(300, 50 + count * 2.5);
}

/** Stable truck → palette index. Sorted truck ids give the same colour for the
 * same fleet regardless of today's zone ordering; colours only shift when the
 * fleet itself changes (rare) rather than every sort run. */
function buildTruckColorIndex(zones: ZonePolygon[], anchors: AnchorPin[]): Map<string, number> {
  const ids = [...new Set([...zones.map(z => z.truck_id), ...anchors.map(a => a.truck_id)])].sort();
  return new Map(ids.map((id, i) => [id, i % ZONE_COLORS.length]));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    initGoogleMaps?: () => void;
  }
}

export default function ZoneDensityMap({
  zones,
  centroids,
  companyZone = null,
  anchors = [],
  outlierTotes = [],
  className = '',
}: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);
  const companyShapeRef = useRef<google.maps.Polygon | null>(null);
  const companyOutlineRef = useRef<google.maps.Polyline | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const colorIndex = useMemo(() => buildTruckColorIndex(zones, anchors), [zones, anchors]);
  const zoneColor = (truckId: string) => ZONE_COLORS[colorIndex.get(truckId) ?? 0];
  const zoneStroke = (truckId: string) => ZONE_STROKE_COLORS[colorIndex.get(truckId) ?? 0];

  const mappableOutliers = useMemo(
    () => outlierTotes.filter(t => t.centroid_lat != null && t.centroid_lng != null),
    [outlierTotes],
  );

  // Load Google Maps script once
  useEffect(() => {
    const key = import.meta.env.VITE_GOOGLE_MAPS_KEY;
    if (!key) { setLoadError(true); return; }
    if (window.google?.maps) { setMapReady(true); return; }

    const existing = document.getElementById('gmap-script');
    if (existing) {
      existing.addEventListener('load', () => setMapReady(true));
      return;
    }

    window.initGoogleMaps = () => setMapReady(true);
    const script = document.createElement('script');
    script.id = 'gmap-script';
    script.src = `https://maps.googleapis.com/maps/api/js?key=${key}&callback=initGoogleMaps`;
    script.async = true;
    script.defer = true;
    script.onerror = () => setLoadError(true);
    document.head.appendChild(script);
  }, []);

  // Init map instance once script is ready
  useEffect(() => {
    if (!mapReady || !mapRef.current || mapInstanceRef.current) return;

    // Default center: NYC (common DSP territory — will auto-fit to zones)
    mapInstanceRef.current = new window.google.maps.Map(mapRef.current, {
      center: { lat: 40.7128, lng: -74.006 },
      zoom: 13,
      mapTypeId: 'roadmap',
      disableDefaultUI: false,
      zoomControl: true,
      streetViewControl: false,
      mapTypeControl: false,
      fullscreenControl: true,
      styles: [
        { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
        { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      ],
    });

    overlayRef.current = new GoogleMapsOverlay({
      getTooltip: ({ object, layer }) => {
        if (!object || !layer) return null;
        if (layer.id === 'zones') {
          const z = object as ZonePolygon;
          const counts = [
            z.tote_count != null ? `${z.tote_count} totes` : null,
            z.package_count != null ? `${z.package_count.toLocaleString()} pkgs` : null,
          ].filter(Boolean).join(' · ');
          return { text: counts ? `${z.zone_label}\n${counts}` : z.zone_label };
        }
        if (layer.id === 'anchors') {
          const a = object as AnchorPin;
          return { text: `${a.truck_name} — anchor${a.which === 2 ? ' 2' : ''}` };
        }
        if (layer.id === 'outlier-totes') {
          const t = object as OutlierToteMarker;
          return { text: `Unplaced tote ${t.tote_id}\n${t.package_count} pkg(s) — needs dispatch` };
        }
        if (layer.id === 'centroids') {
          const c = object as Centroid;
          return { text: `${c.truck_zone_label ?? 'Zone'} centroid\n${c.package_count.toLocaleString()} pkgs` };
        }
        return null;
      },
    });
    overlayRef.current.setMap(mapInstanceRef.current);
  }, [mapReady]);

  // Draw/update the company zone shape whenever it changes.
  // The territory boundary renders as a faint fill + DASHED outline so it reads
  // as "the fence", visually distinct from today's solid-stroked truck zones.
  useEffect(() => {
    if (!mapInstanceRef.current) return;

    const map = mapInstanceRef.current;

    // Always tear down existing shapes when zone changes
    if (companyShapeRef.current) {
      companyShapeRef.current.setMap(null);
      companyShapeRef.current = null;
    }
    if (companyOutlineRef.current) {
      companyOutlineRef.current.setMap(null);
      companyOutlineRef.current = null;
    }

    if (companyZone) {
      const corners = companyZone.corners ?? [];
      const hasCorners = corners.length >= 3;
      const path = hasCorners
        ? corners.map(p => ({ lat: p.lat, lng: p.lng }))
        : [
            { lat: companyZone.sw_lat, lng: companyZone.sw_lng },
            { lat: companyZone.ne_lat, lng: companyZone.sw_lng },
            { lat: companyZone.ne_lat, lng: companyZone.ne_lng },
            { lat: companyZone.sw_lat, lng: companyZone.ne_lng },
          ];

      companyShapeRef.current = new window.google.maps.Polygon({
        paths: path,
        map,
        strokeOpacity: 0,           // outline drawn by the dashed polyline below
        fillColor: '#6366f1',
        fillOpacity: 0.05,
        clickable: false,
        zIndex: 0,
      });

      companyOutlineRef.current = new window.google.maps.Polyline({
        path: [...path, path[0]],   // close the loop
        map,
        strokeOpacity: 0,
        clickable: false,
        zIndex: 1,
        icons: [{
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.9, strokeColor: '#6366f1', strokeWeight: 3, scale: 3 },
          offset: '0',
          repeat: '16px',
        }],
      });

      if (zones.length === 0) {
        const fitZone = () => {
          const b = new window.google.maps.LatLngBounds();
          path.forEach(p => b.extend(p));
          map.fitBounds(b, 32);
        };
        window.google.maps.event.addListenerOnce(map, 'idle', fitZone);
      }
    }
  }, [mapReady, companyZone, zones.length]);

  // Update deck.gl layers whenever zone / centroid / anchor / outlier data changes
  useEffect(() => {
    if (!overlayRef.current || !mapInstanceRef.current) return;

    const polygonLayer = new PolygonLayer({
      id: 'zones',
      data: zones,
      getPolygon: (d: ZonePolygon) => polygonToCoords(d.truck_polygon),
      getFillColor: (d: ZonePolygon) => zoneColor(d.truck_id),
      getLineColor: (d: ZonePolygon) => zoneStroke(d.truck_id),
      getLineWidth: 2,
      lineWidthUnits: 'pixels',
      pickable: true,
      stroked: true,
      filled: true,
    });

    const centroidLayer = new ScatterplotLayer({
      id: 'centroids',
      data: centroids,
      getPosition: (d: Centroid) => [d.centroid_lng, d.centroid_lat],
      getRadius: (d: Centroid) => centroidRadius(d.package_count),
      getFillColor: [255, 255, 255, 180],
      getLineColor: [255, 255, 255, 220],
      stroked: true,
      lineWidthUnits: 'pixels',
      getLineWidth: 1.5,
      radiusUnits: 'meters',
      pickable: true,
    });

    // Anchor pins: the truck's territorial post. Colour-matched to the zone,
    // white ring, fixed pixel size so they stay legible at any zoom.
    const anchorLayer = new ScatterplotLayer({
      id: 'anchors',
      data: anchors,
      getPosition: (d: AnchorPin) => [d.lng, d.lat],
      getRadius: (d: AnchorPin) => (d.which === 1 ? 8 : 6),
      radiusUnits: 'pixels',
      getFillColor: (d: AnchorPin) => {
        const [r, g, b] = zoneStroke(d.truck_id);
        return [r, g, b, 255] as [number, number, number, number];
      },
      getLineColor: [255, 255, 255, 255],
      stroked: true,
      lineWidthUnits: 'pixels',
      getLineWidth: 2.5,
      pickable: true,
    });

    // Unplaced (outlier) totes: red diamonds — the things dispatch must act on.
    const outlierLayer = new TextLayer({
      id: 'outlier-totes',
      data: mappableOutliers,
      getPosition: (d: OutlierToteMarker) => [d.centroid_lng as number, d.centroid_lat as number],
      getText: () => '◆',
      getColor: OUTLIER_RED,
      getSize: 22,
      sizeUnits: 'pixels',
      fontFamily: 'system-ui, sans-serif',
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      outlineWidth: 2,
      outlineColor: [255, 255, 255, 255],
      fontSettings: { sdf: true },
      pickable: true,
    });

    overlayRef.current.setProps({
      layers: [polygonLayer, centroidLayer, anchorLayer, outlierLayer],
    });

    // Auto-fit: prefer truck zone bounds when available, fall back to company zone polygon
    if (zones.length > 0) {
      const b = new window.google.maps.LatLngBounds();
      zones.forEach(z => z.truck_polygon.forEach(p => b.extend({ lat: p.lat, lng: p.lng })));
      mappableOutliers.forEach(t => b.extend({ lat: t.centroid_lat as number, lng: t.centroid_lng as number }));
      mapInstanceRef.current!.fitBounds(b, 40);
    } else if (companyZone) {
      const b = new window.google.maps.LatLngBounds();
      if (companyZone.corners && companyZone.corners.length >= 3) {
        companyZone.corners.forEach(p => b.extend({ lat: p.lat, lng: p.lng }));
      } else {
        b.extend({ lat: companyZone.sw_lat, lng: companyZone.sw_lng });
        b.extend({ lat: companyZone.ne_lat, lng: companyZone.ne_lng });
      }
      mapInstanceRef.current!.fitBounds(b, 40);
    }
  }, [zones, centroids, companyZone, anchors, mappableOutliers, colorIndex]);

  if (loadError) {
    return (
      <div className={`flex items-center justify-center bg-accent/20 rounded-xl border border-dashed border-border ${className}`}>
        <p className="text-sm text-muted-foreground">Map failed to load. Check VITE_GOOGLE_MAPS_KEY.</p>
      </div>
    );
  }

  return (
    <div className={`relative rounded-xl overflow-hidden border border-border ${className}`}>
      <div ref={mapRef} className="w-full h-full" />
      {!mapReady && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent/40">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}
      {/* Legend */}
      {mapReady && (zones.length > 0 || mappableOutliers.length > 0) && (
        <div className="absolute bottom-3 left-3 bg-card/90 backdrop-blur border border-border rounded-xl px-3 py-2 space-y-1 max-w-[220px]">
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Zones</p>
          {zones.slice(0, 8).map(z => {
            const [r, g, b] = zoneColor(z.truck_id);
            const [sr, sg, sb] = zoneStroke(z.truck_id);
            const counts = [
              z.tote_count != null ? `${z.tote_count}t` : null,
              z.package_count != null ? `${z.package_count.toLocaleString()}p` : null,
            ].filter(Boolean).join(' · ');
            return (
              <div key={z.id} className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: `rgb(${r},${g},${b})`, border: `1.5px solid rgb(${sr},${sg},${sb})` }} />
                <span className="text-[11px] text-foreground truncate">{z.zone_label}</span>
                {counts && (
                  <span className="text-[10px] tabular-nums text-muted-foreground ml-auto shrink-0">{counts}</span>
                )}
              </div>
            );
          })}
          {zones.length > 8 && (
            <p className="text-[10px] text-muted-foreground">+{zones.length - 8} more</p>
          )}
          {anchors.length > 0 && (
            <div className="flex items-center gap-1.5 pt-0.5 border-t border-border/60">
              <div className="w-3 h-3 rounded-full shrink-0 bg-foreground/80 border-2 border-white shadow" />
              <span className="text-[10px] text-muted-foreground">Truck anchors</span>
            </div>
          )}
          {mappableOutliers.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[13px] leading-none shrink-0" style={{ color: 'rgb(220,38,38)' }}>◆</span>
              <span className="text-[10px] text-muted-foreground">
                {mappableOutliers.length} unplaced tote{mappableOutliers.length === 1 ? '' : 's'}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
