import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, X, RotateCw } from 'lucide-react';

/** Frame the label before OCR runs.
 *
 *  WHY MANUAL. Automatic label detection was tried three ways on a real field
 *  photo (IMG_3942) and all three failed: a brightness profile cropped the
 *  label to its left third, saturation-based paper detection found a plausible
 *  box that still read as noise, and a 3x2 rotation/scale sweep produced zero
 *  usable reads. A HAND-DRAWN box on the same photo read the address cleanly at
 *  56% confidence — "Phyllicia Eligon / 104 W MEADOW WIND LN / NEWBURGH NY".
 *
 *  The difference is that a camera frame is mostly cardboard, and Tesseract
 *  spends its effort there. A person can see the label instantly; a brightness
 *  heuristic cannot. So the person draws the box.
 *
 *  It also removes the rotation sweep. Four rotations cost ~8.7s on a laptop
 *  and would be 30-40s on a phone; with the crop framed, one pass suffices and
 *  the explicit rotate button covers a sideways label.
 *
 *  TOUCH-FIRST. This runs on a phone in a van, so the whole thing is sized off
 *  the viewport, the handles are 44px (iOS HIG), and it drives Pointer Events —
 *  one code path for finger and mouse rather than two.
 */

interface Box { x: number; y: number; w: number; h: number }

const HANDLE = 44;      // iOS Human Interface Guidelines minimum touch target

export default function CropDialog({ file, onCancel, onCrop }: {
  file: Blob;
  onCancel: () => void;
  /** Receives the cropped, rotated, upscaled image ready for OCR. */
  onCrop: (blob: Blob) => void;
}) {
  const [bmp, setBmp] = useState<ImageBitmap | null>(null);
  const [rot, setRot] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ mode: string; sx: number; sy: number; start: Box } | null>(null);

  useEffect(() => {
    let dead = false;
    createImageBitmap(file).then((b) => { if (!dead) setBmp(b); });
    return () => { dead = true; };
  }, [file]);

  // Draw the photo into a canvas sized to fit the viewport, and start with a
  // generous default box — most of the frame, so a careless user who just taps
  // "Use crop" is no worse off than before.
  useEffect(() => {
    if (!bmp || !imgRef.current || !wrapRef.current) return;
    const swap = rot === 90 || rot === 270;
    const iw = swap ? bmp.height : bmp.width;
    const ih = swap ? bmp.width : bmp.height;
    const avail = wrapRef.current.clientWidth;
    // Leave room for the header and buttons on a short phone screen.
    const maxH = Math.max(240, window.innerHeight - 220);
    const scale = Math.min(avail / iw, maxH / ih);
    const c = imgRef.current;
    c.width = Math.round(iw * scale);
    c.height = Math.round(ih * scale);
    const ctx = c.getContext('2d')!;
    ctx.imageSmoothingQuality = 'high';
    ctx.save();
    ctx.translate(c.width / 2, c.height / 2);
    ctx.rotate((rot * Math.PI) / 180);
    ctx.drawImage(bmp, -(bmp.width * scale) / 2, -(bmp.height * scale) / 2,
      bmp.width * scale, bmp.height * scale);
    ctx.restore();
    setBox({ x: c.width * 0.08, y: c.height * 0.08, w: c.width * 0.84, h: c.height * 0.84 });
  }, [bmp, rot]);

  const onDown = useCallback((mode: string) => (e: React.PointerEvent) => {
    if (!box) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { mode, sx: e.clientX, sy: e.clientY, start: { ...box } };
  }, [box]);

  const onMove = useCallback((e: React.PointerEvent) => {
    const d = drag.current;
    const c = imgRef.current;
    if (!d || !c) return;
    const dx = e.clientX - d.sx;
    const dy = e.clientY - d.sy;
    const s = d.start;
    const MIN = 60;
    let n: Box;
    if (d.mode === 'move') {
      n = { ...s, x: s.x + dx, y: s.y + dy };
    } else {
      // Corner handles: nw/ne/sw/se each move one corner, opposite edge fixed.
      const left = d.mode.includes('w'), top = d.mode.includes('n');
      const x = left ? s.x + dx : s.x;
      const y = top ? s.y + dy : s.y;
      const w = left ? s.w - dx : s.w + dx;
      const h = top ? s.h - dy : s.h + dy;
      n = { x, y, w: Math.max(MIN, w), h: Math.max(MIN, h) };
      if (left && w < MIN) n.x = s.x + s.w - MIN;
      if (top && h < MIN) n.y = s.y + s.h - MIN;
    }
    // Keep it on the image.
    n.w = Math.min(n.w, c.width); n.h = Math.min(n.h, c.height);
    n.x = Math.max(0, Math.min(n.x, c.width - n.w));
    n.y = Math.max(0, Math.min(n.y, c.height - n.h));
    setBox(n);
  }, []);

  const onUp = useCallback(() => { drag.current = null; }, []);

  const confirm = useCallback(async () => {
    if (!bmp || !box || !imgRef.current) return;
    const c = imgRef.current;
    const swap = rot === 90 || rot === 270;
    const iw = swap ? bmp.height : bmp.width;
    const ih = swap ? bmp.width : bmp.height;
    const k = iw / c.width;                    // preview px -> source px

    const cw = Math.round(box.w * k);
    const ch = Math.round(box.h * k);
    // UPSCALE toward ~2200px on the long edge. Measured: the same crop at
    // native size read at 37% and at 2x at 43-56%. Capped so a huge crop does
    // not blow up memory on a phone.
    const up = Math.min(2.5, Math.max(1, 2200 / Math.max(cw, ch)));

    const out = document.createElement('canvas');
    out.width = Math.round(cw * up);
    out.height = Math.round(ch * up);
    const ctx = out.getContext('2d')!;
    ctx.imageSmoothingQuality = 'high';
    // Render the rotated full image into a scratch canvas, then take the box
    // from it — simpler and less error-prone than composing the transforms.
    const scratch = document.createElement('canvas');
    scratch.width = iw; scratch.height = ih;
    const sctx = scratch.getContext('2d')!;
    sctx.translate(iw / 2, ih / 2);
    sctx.rotate((rot * Math.PI) / 180);
    sctx.drawImage(bmp, -bmp.width / 2, -bmp.height / 2);
    ctx.drawImage(scratch, box.x * k, box.y * k, cw, ch, 0, 0, out.width, out.height);

    const blob: Blob = await new Promise((r) => out.toBlob((b) => r(b!), 'image/png'));
    onCrop(blob);
  }, [bmp, box, rot, onCrop]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/90 p-3">
      <div className="flex items-center justify-between text-white">
        <p className="text-sm font-medium">Frame the label</p>
        <button type="button" onClick={onCancel} className="rounded-lg p-2 hover:bg-white/10" aria-label="Cancel">
          <X className="h-5 w-5" />
        </button>
      </div>
      <p className="mt-1 text-[11px] text-white/60">
        Drag the corners so the box holds the address and the TBA, and as little
        cardboard as possible.
      </p>

      <div ref={wrapRef} className="relative mt-3 flex-1 overflow-hidden">
        <div className="relative inline-block touch-none select-none">
          <canvas ref={imgRef} className="block max-w-full" />
          {box && (
            <>
              {/* Dim everything outside the box so the crop reads at a glance. */}
              <div className="pointer-events-none absolute inset-0 bg-black/55"
                   style={{ clipPath: `polygon(0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${box.x}px ${box.y}px, ${box.x}px ${box.y + box.h}px, ${box.x + box.w}px ${box.y + box.h}px, ${box.x + box.w}px ${box.y}px, ${box.x}px ${box.y}px)` }} />
              <div
                onPointerDown={onDown('move')} onPointerMove={onMove} onPointerUp={onUp}
                className="absolute cursor-move border-2 border-primary"
                style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
              />
              {(['nw', 'ne', 'sw', 'se'] as const).map((m) => (
                <div
                  key={m}
                  onPointerDown={onDown(m)} onPointerMove={onMove} onPointerUp={onUp}
                  className="absolute flex items-center justify-center"
                  style={{
                    width: HANDLE, height: HANDLE,
                    left: (m.includes('w') ? box.x : box.x + box.w) - HANDLE / 2,
                    top: (m.includes('n') ? box.y : box.y + box.h) - HANDLE / 2,
                    touchAction: 'none',
                  }}
                >
                  <span className="h-5 w-5 rounded-full border-2 border-white bg-primary shadow" />
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button" onClick={() => setRot((r) => (r + 90) % 360)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/25 px-3 py-2.5 text-sm text-white hover:bg-white/10"
        >
          <RotateCw className="h-4 w-4" /> Rotate
        </button>
        <button
          type="button" onClick={() => void confirm()} disabled={!box}
          className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-40"
        >
          <Check className="h-4 w-4" /> Read this
        </button>
      </div>
    </div>
  );
}
