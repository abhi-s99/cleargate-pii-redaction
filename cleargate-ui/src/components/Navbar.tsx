import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { PlusCircle, Menu, X } from 'lucide-react';

export const Navbar: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();

  const navLinks = [
    { label: 'Upload', to: '/' },
    { label: 'Jobs', to: '/jobs' },
    { label: 'Review', to: '/jobs?view=review' },
    { label: 'How it works', to: '/how-it-works' },
  ];

  const isLinkActive = (to: string): boolean => {
    if (to === '/') {
      return location.pathname === '/';
    }
    if (to === '/jobs?view=review') {
      return (
        (location.pathname === '/jobs' &&
          new URLSearchParams(location.search).get('view') === 'review') ||
        location.pathname.endsWith('/review')
      );
    }
    if (to === '/jobs') {
      return (
        location.pathname.startsWith('/jobs') &&
        new URLSearchParams(location.search).get('view') !== 'review' &&
        !location.pathname.endsWith('/review')
      );
    }
    return location.pathname === to;
  };

  return (
    <nav className="bg-surface border-b border-border sticky top-0 z-40 shadow-sm">
      <div className="max-w-container mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between h-16">
          {/* Brand Wordmark (Rule R8: No logo image, text wordmark ClearGate) */}
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-2.5 group">
              <img
                src="/logo.png"
                alt="ClearGate Logo"
                className="w-8 h-8 rounded-md object-cover shadow-sm border border-border"
              />
              <span className="font-heading font-bold text-xl tracking-tight text-text">
                ClearGate
              </span>
            </Link>

            {/* Desktop Navigation Links */}
            <div className="hidden md:flex items-center space-x-4">
              {navLinks.map((link) => {
                const active = isLinkActive(link.to);
                return (
                  <Link
                    key={link.to}
                    to={link.to}
                    className={`px-3 py-2 text-sm font-medium transition-colors ${
                      active
                        ? 'text-accent font-semibold border-b-2 border-accent'
                        : 'text-text-muted hover:text-text'
                    }`}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>
          </div>

          {/* Right CTA Button (Optiv "Contact" button position) */}
          <div className="hidden md:flex items-center gap-4">
            <Link
              to="/"
              className="bg-accent hover:bg-accent-hover text-text-on-accent text-sm font-medium px-4 py-2 rounded-md transition-all shadow flex items-center gap-2 focus:ring-2 focus:ring-focus-ring"
            >
              <PlusCircle className="w-4 h-4" />
              <span>New batch</span>
            </Link>
          </div>

          {/* Mobile hamburger button */}
          <div className="md:hidden flex items-center">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="text-text-muted hover:text-text p-2 rounded-md focus:ring-2 focus:ring-focus-ring"
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {/* Mobile menu dropdown */}
        {mobileMenuOpen && (
          <div className="md:hidden py-4 border-t border-border space-y-2">
            {navLinks.map((link) => {
              const active = isLinkActive(link.to);
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`block px-3 py-2 rounded-md text-base font-medium ${
                    active
                      ? 'bg-surface-raised text-accent font-semibold'
                      : 'text-text-muted hover:text-text hover:bg-surface-raised'
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
            <div className="pt-2">
              <Link
                to="/"
                onClick={() => setMobileMenuOpen(false)}
                className="w-full bg-accent hover:bg-accent-hover text-text-on-accent text-center py-2 px-4 rounded-md font-medium flex items-center justify-center gap-2"
              >
                <PlusCircle className="w-4 h-4" />
                <span>New batch</span>
              </Link>
            </div>
          </div>
        )}
      </div>
    </nav>
  );
};
