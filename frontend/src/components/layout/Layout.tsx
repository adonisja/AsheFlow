import React from 'react';
import { Outlet } from 'react-router-dom';
import Navbar from './Navbar';
import FeedbackModal from '../FeedbackModal';

const Layout = () => {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Navbar />
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="animate-fade-in">
          <Outlet />
        </div>
      </main>
      <FeedbackModal />
    </div>
  );
};

export default Layout;
