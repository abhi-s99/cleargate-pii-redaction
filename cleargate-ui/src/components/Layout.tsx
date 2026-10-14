import React from 'react';
import { Outlet } from 'react-router-dom';
import { UtilityBar } from './UtilityBar';
import { Navbar } from './Navbar';
import { Footer } from './Footer';

export const Layout: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-bg text-text">
      <UtilityBar />
      <Navbar />
      <main className="flex-1 flex flex-col">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
};
