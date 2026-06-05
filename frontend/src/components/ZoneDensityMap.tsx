import React, { useEffect, useRef, useState } from 'react';
import { GoogleMapsOverlay } from '@deck.gl/google-maps';
import { PolygonLayer } from '@deck.gl/layers';
import { ScatterplotLayer } from '@deck.gl/layers';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ZonePolygon {
  id: string;
  zone_label: string;
  truck_polygon: { lat: number; lng: number }[];
}

export interface Centroid {
  centroid_lat: number;
  centroid_lng: number;
  package_count: number;
  truck_zone_label: string | null;
}

interface Props {
  zones: ZonePolygon[];
  centroids: Centroid[];
  className?: string;
}

// ---------------------------------------------------------------------------
// Zone colour palette — one per zone, cycles
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    initGoogleMaps?: () => void;
  }
}

export default function ZoneDensityMap({ zones, centroids, className = '' }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [loadError, setLoadError] = useState(false);

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

    overlayRef.current = new GoogleMapsOverlay({});
    overlayRef.current.setMap(mapInstanceRef.current);
  }, [mapReady]);

  // Update layers whenever data changes
  useEffect(() => {
    if (!overlayRef.current || !mapInstanceRef.current) return;

    const polygonLayer = new PolygonLayer({
      id: 'zones',
      data: zones,
      getPolygon: (d: ZonePolygon) => polygonToCoords(d.truck_polygon),
      getFillColor: (_: ZonePolygon, { index }: { index: number }) =>
        ZONE_COLORS[index % ZONE_COLORS.length],
      getLineColor: (_: ZonePolygon, { index }: { index: number }) =>
        ZONE_STROKE_COLORS[index % ZONE_STROKE_COLORS.length],
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

    overlayRef.current.setProps({ layers: [polygonLayer, centroidLayer] });

    // Auto-fit bounds to zones
    if (zones.length > 0) {
      const bounds = new window.google.maps.LatLngBounds();
      zones.forEach(z => z.truck_polygon.forEach(p => bounds.extend({ lat: p.lat, lng: p.lng })));
      mapInstanceRef.current!.fitBounds(bounds, 40);
    }
  }, [zones, centroids]);

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
      {mapReady && zones.length > 0 && (
        <div className="absolute bottom-3 left-3 bg-card/90 backdrop-blur border border-border rounded-xl px-3 py-2 space-y-1 max-w-[180px]">
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Zones</p>
          {zones.slice(0, 8).map((z, i) => {
            const [r, g, b] = ZONE_COLORS[i % ZONE_COLORS.length];
            return (
              <div key={z.id} className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: `rgb(${r},${g},${b})`, border: `1.5px solid rgb(${ZONE_STROKE_COLORS[i % ZONE_STROKE_COLORS.length].slice(0, 3).join(',')})` }} />
                <span className="text-[11px] text-foreground truncate">{z.zone_label}</span>
              </div>
            );
          })}
          {zones.length > 8 && (
            <p className="text-[10px] text-muted-foreground">+{zones.length - 8} more</p>
          )}
        </div>
      )}
    </div>
  );
}
