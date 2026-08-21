import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import Navbar from './Navbar';
import FeedbackModal from '../FeedbackModal';
import CommandPalette from '../CommandPalette';
import NotificationBanner from '../NotificationBanner';

/**
 * Page width by route. TWO widths only (see `.layout-wide` / `.layout-form` in
 * index.css). Anything not listed gets `layout-wide`.
 *
 * `layout-form` is for single-column forms and reading — stretching those to
 * 1280px hurts legibility. Everything else is tables and dense operational
 * data, which wants the room.
 *
 * This lives here rather than in each page so the NOTIFICATION BANNER can take
 * the same width. That alignment is the whole point of the change: previously
 * the banner used main's 1280px while pages used their own 672-1152px.
 */
/* `/schedule-changes` and `/field-ops` were both here and moved out: seen
   rendered, each is a KPI dashboard — a 4-stat row plus data sections — not a
   form. The lesson, twice over: classify from the RENDERED page, not the file
   name or a guess about what the page "is".

   `/scorecard-entry` stays on the list but is UNVERIFIED: it is gated to
   admin/management and renders "Access Denied" for dispatch, so nobody has
   seen its real layout. It is named "entry", which suggests a form; that is an
   assumption, not an observation. */
const FORM_WIDTH_ROUTES = [
  '/account',
  '/preferences',
  '/notifications',
  '/scorecard-entry',
  '/graduation-quiz',
];

function widthClassFor(pathname: string): string {
  return FORM_WIDTH_ROUTES.some(r => pathname.startsWith(r)) ? 'layout-form' : 'layout-wide';
}

const Layout = () => {
  const location = useLocation();
  const widthClass = widthClassFor(location.pathname);

  return (
    <div className="relative min-h-screen bg-background flex flex-col">
      {/* Ambient backdrop — subtle in light, richer in dark */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      >
        <div
          className="absolute -top-32 -left-32 w-[640px] h-[640px] rounded-full opacity-[0.18] dark:opacity-[0.22]"
          style={{ background: 'radial-gradient(circle, hsl(var(--primary) / 0.55), transparent 70%)' }}
        />
        <div
          className="absolute top-[40%] -right-40 w-[520px] h-[520px] rounded-full opacity-[0.14] dark:opacity-[0.20]"
          style={{ background: 'radial-gradient(circle, hsl(var(--gold) / 0.5), transparent 70%)' }}
        />
      </div>

      <Navbar />

      {/* `main` no longer sets the width. Each page picks `layout-wide` or
          `layout-form`, and the banner takes the SAME width so the two always
          align — previously the banner used main's 1280px while pages used
          their own 672-1152px, leaving content visibly indented from it. */}
      {/* `pb-14` (56px), not `py-6`. 24px left the last control of a page flush
          against the end of the document, which reads as content being cut off,
          and the floating support widget sits in that corner covering it. 96px
          was tried first and overshot — the page then ended in obvious dead
          space. 56px clears the widget without looking empty. */}
      <main className="flex-1 w-full px-4 sm:px-6 lg:px-8 pt-6 pb-14">
        <div className={`${widthClass} mb-4`}>
          <NotificationBanner />
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            className={widthClass}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>

      <CommandPalette />
      <FeedbackModal />
    </div>
  );
};

export default Layout;
