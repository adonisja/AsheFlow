import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import Navbar from './Navbar';
import FeedbackModal from '../FeedbackModal';
import CommandPalette from '../CommandPalette';

const Layout = () => {
  const location = useLocation();

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

      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
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
