import React from 'react';
import { Link } from 'react-router-dom';
import { Lock } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="bg-footer-bg text-footer-text border-t border-border mt-auto">
      <div className="max-w-container mx-auto px-4 sm:px-6 py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-12">
          {/* Brand & Closing tagline */}
          <div className="space-y-4 md:col-span-1">
            <div className="flex items-center gap-2">
              <img
                src="/logo.png"
                alt="ClearGate Logo"
                className="w-6 h-6 rounded object-cover shadow-sm"
              />
              <span className="font-heading font-bold text-lg text-footer-text">
                ClearGate
              </span>
            </div>
            <p className="text-sm font-medium text-gray-200">
              Verified before it reaches the model.
            </p>
            <p className="text-xs text-gray-400 leading-relaxed">
              Enterprise privacy gate isolating sensitive enterprise documents from AI models through deterministic detection, redaction, and independent verification.
            </p>
          </div>

          {/* Product links */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-300">
              Product
            </h2>
            <ul className="space-y-2 text-sm text-gray-400">
              <li>
                <Link to="/" className="hover:text-footer-text transition-colors">
                  Upload & Gate
                </Link>
              </li>
              <li>
                <Link to="/jobs" className="hover:text-footer-text transition-colors">
                  Job Tracking
                </Link>
              </li>
              <li>
                <Link to="/jobs?view=review" className="hover:text-footer-text transition-colors">
                  Review Queue
                </Link>
              </li>
              <li>
                <Link to="/connect" className="hover:text-footer-text transition-colors">
                  Connect & Health
                </Link>
              </li>
            </ul>
          </div>

          {/* Documentation links */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-300">
              Documentation
            </h2>
            <ul className="space-y-2 text-sm text-gray-400">
              <li>
                <Link to="/how-it-works" className="hover:text-footer-text transition-colors">
                  Pipeline Architecture
                </Link>
              </li>
              <li>
                <Link to="/how-it-works#states" className="hover:text-footer-text transition-colors">
                  Job State Transitions
                </Link>
              </li>
              <li>
                <Link to="/how-it-works#fail-closed" className="hover:text-footer-text transition-colors">
                  Fail-Closed Verification
                </Link>
              </li>
            </ul>
          </div>

          {/* Governance / Legal links */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-300">
              Governance & Safety
            </h2>
            <ul className="space-y-2 text-sm text-gray-400">
              <li>
                <Link to="/how-it-works#limitations" className="hover:text-footer-text transition-colors flex items-center gap-1.5">
                  <Lock className="w-3.5 h-3.5 text-accent" />
                  <span>Prototype Limitations</span>
                </Link>
              </li>
              <li>
                <span className="text-gray-400 text-xs block pt-1">
                  Zero privacy logic in frontend client.
                </span>
              </li>
            </ul>
          </div>
        </div>

        {/* Legal baseline row per Section 9.4 & R8 */}
        <div className="border-t border-neutral-800 pt-6 flex flex-col sm:flex-row items-center justify-between text-xs text-gray-400 gap-4">
          <p>
            Prototype built for the Optiv Consulting case study PS-2. Not for production use.
          </p>
          <div className="flex items-center gap-6">
            <span>WCAG 2.1 AA Compliant</span>
            <span>Local Offline Isolation</span>
            <span>v0.1 Prototype</span>
          </div>
        </div>
      </div>
    </footer>
  );
};
