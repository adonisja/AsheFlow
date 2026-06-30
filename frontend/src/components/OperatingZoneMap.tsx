import React, { useEffect, useRef, useState, useCallback } from 'react';
import type { CompanyZone, CornerPoint } from '../api/types';

// ---------------------------------------------------------------------------
// View-mode props (read-only display of a saved zone)
// ---------------------------------------------------------------------------

interface ViewProps {
  mode: 'view';
  bounds: CompanyZone;
  className?: string;
}

// ---------------------------------------------------------------------------
// Draw-mode props (interactive polygon editor)
// ---------------------------------------------------------------------------

interface DrawProps {
  mode: 'draw';
  initialCorners?: CornerPoint[];
  onSave: (corners: CornerPoint[]) => void;
  onCancel: () => void;
  className?: string;
}

type Props = ViewProps | DrawProps;

declare global {
  interface Window {
    initGoogleMaps?: () => void;
  }
}

const SHAPE_STYLE = {
  strokeColor:   '#6366f1',
  strokeOpacity: 0.9,
  strokeWeight:  2.5,
  fillColor:     '#6366f1',
  fillOpacity:   0.10,
  clickable:     false,
};

export default function OperatingZoneMap(props: Props) {
  const mapRef         = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const shapeRef       = useRef<google.maps.Polygon | google.maps.Rectangle | null>(null);
  const markersRef     = useRef<google.maps.Marker[]>([]);
  const previewRef     = useRef<google.maps.Polygon | null>(null);
  const clickListenerRef = useRef<google.maps.MapsEventListener | null>(null);

  const [mapReady, setMapReady]     = useState(false);
  const [loadError, setLoadError]   = useState(false);
  const [vertices, setVertices]     = useState<CornerPoint[]>(
    props.mode === 'draw' ? (props.initialCorners ?? []) : []
  );

  // -------------------------------------------------------------------------
  // Load Maps SDK (shared gmap-script tag)
  // -------------------------------------------------------------------------

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
    const script   = document.createElement('script');
    script.id      = 'gmap-script';
    script.src     = `https://maps.googleapis.com/maps/api/js?key=${key}&callback=initGoogleMaps`;
    script.async   = true;
    script.defer   = true;
    script.onerror = () => setLoadError(true);
    document.head.appendChild(script);
  }, []);

  // -------------------------------------------------------------------------
  // Init map instance
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!mapReady || !mapRef.current || mapInstanceRef.current) return;

    let center = { lat: 40.7128, lng: -74.006 };
    let zoom   = 13;

    if (props.mode === 'view') {
      center = {
        lat: (props.bounds.sw_lat + props.bounds.ne_lat) / 2,
        lng: (props.bounds.sw_lng + props.bounds.ne_lng) / 2,
      };
    } else if (props.mode === 'draw' && props.initialCorners && props.initialCorners.length > 0) {
      center = { lat: props.initialCorners[0].lat, lng: props.initialCorners[0].lng };
      zoom   = 14;
    }

    mapInstanceRef.current = new window.google.maps.Map(mapRef.current, {
      center,
      zoom,
      mapTypeId: 'roadmap',
      disableDefaultUI: false,
      zoomControl: true,
      streetViewControl: false,
      mapTypeControl: false,
      fullscreenControl: props.mode === 'view',
      styles: [
        { featureType: 'poi',     elementType: 'labels', stylers: [{ visibility: 'off' }] },
        { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      ],
    });
  }, [mapReady]); // eslint-disable-line react-hooks/exhaustive-deps

  // -------------------------------------------------------------------------
  // VIEW MODE — draw saved polygon / rectangle and fit
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (props.mode !== 'view' || !mapInstanceRef.current) return;

    const map     = mapInstanceRef.current;
    const corners = props.bounds.corners ?? [];
    const hasCorners = corners.length >= 3;

    if (shapeRef.current) { shapeRef.current.setMap(null); shapeRef.current = null; }

    if (hasCorners) {
      shapeRef.current = new window.google.maps.Polygon({
        paths: corners.map(p => ({ lat: p.lat, lng: p.lng })),
        map, ...SHAPE_STYLE,
      });
    } else {
      shapeRef.current = new window.google.maps.Rectangle({
        bounds: {
          south: props.bounds.sw_lat, west: props.bounds.sw_lng,
          north: props.bounds.ne_lat, east: props.bounds.ne_lng,
        },
        map, ...SHAPE_STYLE,
      });
    }

    window.google.maps.event.addListenerOnce(map, 'idle', () => {
      if (hasCorners) {
        const b = new window.google.maps.LatLngBounds();
        corners.forEach(p => b.extend({ lat: p.lat, lng: p.lng }));
        map.fitBounds(b, 8);
      } else {
        map.fitBounds({
          south: props.bounds.sw_lat, west: props.bounds.sw_lng,
          north: props.bounds.ne_lat, east: props.bounds.ne_lng,
        }, 8);
      }
    });
  }, [mapReady, props.mode === 'view' && props.bounds]); // eslint-disable-line react-hooks/exhaustive-deps

  // -------------------------------------------------------------------------
  // DRAW MODE — click listener + vertex markers + live preview polygon
  // -------------------------------------------------------------------------

  const clearDrawOverlays = useCallback(() => {
    markersRef.current.forEach(m => m.setMap(null));
    markersRef.current = [];
    if (previewRef.current) { previewRef.current.setMap(null); previewRef.current = null; }
  }, []);

  // Rebuild markers + preview polygon whenever vertices change (draw mode only)
  useEffect(() => {
    if (props.mode !== 'draw' || !mapInstanceRef.current) return;

    const map = mapInstanceRef.current;
    clearDrawOverlays();

    // Redraw vertex markers
    vertices.forEach((v, i) => {
      const marker = new window.google.maps.Marker({
        position: { lat: v.lat, lng: v.lng },
        map,
        draggable: true,
        title: `Vertex ${i + 1}`,
        icon: {
          path: window.google.maps.SymbolPath.CIRCLE,
          scale: i === 0 ? 8 : 6,
          fillColor:    i === 0 ? '#f59e0b' : '#6366f1',
          fillOpacity:  1,
          strokeColor:  '#ffffff',
          strokeWeight: 2,
        },
      });

      marker.addListener('drag', (e: google.maps.MapMouseEvent) => {
        if (!e.latLng) return;
        setVertices(prev => {
          const next = [...prev];
          next[i] = { lat: e.latLng!.lat(), lng: e.latLng!.lng() };
          return next;
        });
      });

      // Click on first marker closes the polygon
      if (i === 0) {
        marker.addListener('click', () => {
          if (vertices.length >= 3) {
            // polygon is already closed by having first === last in the preview;
            // clicking the first vertex when ≥3 points is just a UX confirmation — no-op here
          }
        });
      }

      markersRef.current.push(marker);
    });

    // Live preview polygon (3+ vertices)
    if (vertices.length >= 3) {
      previewRef.current = new window.google.maps.Polygon({
        paths: vertices.map(v => ({ lat: v.lat, lng: v.lng })),
        map,
        ...SHAPE_STYLE,
        clickable: false,
      });
    } else if (vertices.length === 2) {
      // Draw a line while fewer than 3 points
      previewRef.current = new window.google.maps.Polygon({
        paths: vertices.map(v => ({ lat: v.lat, lng: v.lng })),
        map,
        strokeColor:  '#6366f1',
        strokeOpacity: 0.6,
        strokeWeight: 2,
        fillOpacity:  0,
        clickable:    false,
      });
    }
  }, [mapReady, vertices, props.mode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Attach / detach click listener for adding vertices
  useEffect(() => {
    if (props.mode !== 'draw' || !mapInstanceRef.current) return;

    const map = mapInstanceRef.current;
    if (clickListenerRef.current) {
      window.google.maps.event.removeListener(clickListenerRef.current);
    }

    clickListenerRef.current = map.addListener('click', (e: google.maps.MapMouseEvent) => {
      if (!e.latLng) return;
      setVertices(prev => [...prev, { lat: e.latLng!.lat(), lng: e.latLng!.lng() }]);
    });

    return () => {
      if (clickListenerRef.current) {
        window.google.maps.event.removeListener(clickListenerRef.current);
        clickListenerRef.current = null;
      }
    };
  }, [mapReady, props.mode]);

  // Cleanup draw overlays when unmounting or switching modes
  useEffect(() => {
    return () => {
      clearDrawOverlays();
      if (clickListenerRef.current) {
        window.google.maps.event.removeListener(clickListenerRef.current);
      }
    };
  }, [clearDrawOverlays]);

  // -------------------------------------------------------------------------
  // Fit map to initial corners when draw mode opens with existing data
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (props.mode !== 'draw' || !mapInstanceRef.current) return;
    const initial = props.initialCorners;
    if (!initial || initial.length < 2) return;

    window.google.maps.event.addListenerOnce(mapInstanceRef.current, 'idle', () => {
      const b = new window.google.maps.LatLngBounds();
      initial.forEach(p => b.extend({ lat: p.lat, lng: p.lng }));
      mapInstanceRef.current!.fitBounds(b, 40);
    });
  }, [mapReady]); // eslint-disable-line react-hooks/exhaustive-deps

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (loadError) {
    return (
      <div className={`flex items-center justify-center bg-accent/20 rounded-xl border border-dashed border-border ${props.className ?? ''}`}>
        <p className="text-sm text-muted-foreground">Map failed to load. Check VITE_GOOGLE_MAPS_KEY.</p>
      </div>
    );
  }

  return (
    <div className={`relative rounded-xl overflow-hidden border border-border ${props.className ?? ''}`}>
      <div ref={mapRef} className="w-full h-full" />

      {!mapReady && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent/20">
          <p className="text-xs text-muted-foreground">Loading map…</p>
        </div>
      )}

      {/* Draw mode overlays */}
      {props.mode === 'draw' && mapReady && (
        <>
          {/* Instruction banner */}
          <div className="absolute top-2 left-1/2 -translate-x-1/2 bg-card/95 backdrop-blur border border-border rounded-xl px-3 py-1.5 text-xs text-foreground shadow-lg whitespace-nowrap pointer-events-none">
            {vertices.length === 0 && 'Click on the map to place the first vertex'}
            {vertices.length === 1 && 'Click to add more vertices'}
            {vertices.length === 2 && 'Click to add more vertices (need at least 3)'}
            {vertices.length >= 3  && `${vertices.length} vertices — drag to adjust, or keep clicking to add more`}
          </div>

          {/* Vertex count + action buttons */}
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-2 pointer-events-auto">
            {vertices.length > 0 && (
              <button
                onClick={() => setVertices(prev => prev.slice(0, -1))}
                className="bg-card/95 backdrop-blur border border-border rounded-lg px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors shadow"
              >
                Undo last
              </button>
            )}
            {vertices.length > 0 && (
              <button
                onClick={() => setVertices([])}
                className="bg-card/95 backdrop-blur border border-border rounded-lg px-2.5 py-1 text-xs text-destructive hover:bg-destructive/10 transition-colors shadow"
              >
                Clear all
              </button>
            )}
            {vertices.length >= 3 && (
              <button
                onClick={() => props.mode === 'draw' && props.onSave(vertices)}
                className="bg-primary text-primary-foreground rounded-lg px-3 py-1 text-xs font-medium hover:bg-primary/90 transition-colors shadow"
              >
                Use this shape
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
