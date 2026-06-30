import React, { useEffect, useRef, useState } from 'react';

interface Bounds {
  sw_lat: number;
  sw_lng: number;
  ne_lat: number;
  ne_lng: number;
}

interface Props {
  bounds: Bounds;
  className?: string;
}

declare global {
  interface Window {
    initGoogleMaps?: () => void;
  }
}

export default function OperatingZoneMap({ bounds, className = '' }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const rectRef = useRef<google.maps.Rectangle | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [loadError, setLoadError] = useState(false);

  // Load Google Maps script once (shared gmap-script tag with other map components)
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

    mapInstanceRef.current = new window.google.maps.Map(mapRef.current, {
      center: { lat: (bounds.sw_lat + bounds.ne_lat) / 2, lng: (bounds.sw_lng + bounds.ne_lng) / 2 },
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
  }, [mapReady]); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw/update the rectangle and fit bounds whenever the map is ready or bounds change
  useEffect(() => {
    if (!mapInstanceRef.current) return;

    const map = mapInstanceRef.current;
    const rectBounds = {
      south: bounds.sw_lat,
      west:  bounds.sw_lng,
      north: bounds.ne_lat,
      east:  bounds.ne_lng,
    };

    if (rectRef.current) {
      rectRef.current.setBounds(rectBounds);
      map.fitBounds(rectBounds, 32);
    } else {
      rectRef.current = new window.google.maps.Rectangle({
        bounds: rectBounds,
        strokeColor: '#6366f1',
        strokeOpacity: 0.9,
        strokeWeight: 2.5,
        fillColor: '#6366f1',
        fillOpacity: 0.10,
        map,
        clickable: false,
      });
      // fitBounds after first idle so the map has painted and has a real pixel size
      window.google.maps.event.addListenerOnce(map, 'idle', () => {
        map.fitBounds(rectBounds, 32);
      });
    }
  }, [mapReady, bounds]);

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
        <div className="absolute inset-0 flex items-center justify-center bg-accent/20">
          <p className="text-xs text-muted-foreground">Loading map…</p>
        </div>
      )}
    </div>
  );
}
