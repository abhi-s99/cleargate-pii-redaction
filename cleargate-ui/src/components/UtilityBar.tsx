import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../app/AuthContext';
import { ShieldCheck, LogOut, LogIn } from 'lucide-react';

interface UtilityBarProps {
  apiMode?: string;
  isHealthy?: boolean;
}

export const UtilityBar: React.FC<UtilityBarProps> = ({
  apiMode = import.meta.env.VITE_API_MODE || 'mock',
  isHealthy = true,
}) => {
  const { role, isAuthenticated, logout } = useAuth();

  return (
    <aside aria-label="Environment and status utility bar" className="bg-hero-bg text-gray-300 text-xs border-b border-border py-1.5 px-4 sm:px-6">
      <div className="max-w-container mx-auto flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-mono text-[11px] text-gray-400">
            Prototype · design baseline v0.1
          </span>
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold uppercase ${
              apiMode === 'live'
                ? 'bg-status-safe-bg text-status-safe border border-status-safe/30'
                : 'bg-status-processing-bg text-status-processing border border-status-processing/30'
            }`}
          >
            {apiMode.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                isHealthy ? 'bg-status-safe' : 'bg-status-failed'
              }`}
              title={isHealthy ? 'Backend reachable' : 'Backend unreachable'}
            />
            <span className="hidden sm:inline font-mono text-[11px]">
              {isHealthy ? 'Service healthy' : 'Service offline'}
            </span>
          </div>

          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              <span className="capitalize px-2 py-0.5 rounded bg-surface-raised text-text font-medium text-[11px] border border-border flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-accent" />
                {role}
              </span>
              <button
                type="button"
                onClick={logout}
                className="text-text-muted hover:text-text flex items-center gap-1 text-[11px] transition-colors"
                title="Disconnect session"
              >
                <LogOut className="w-3 h-3" />
                <span className="hidden sm:inline">Disconnect</span>
              </button>
            </div>
          ) : (
            <Link
              to="/connect"
              className="text-link hover:underline flex items-center gap-1 text-[11px]"
            >
              <LogIn className="w-3 h-3" />
              <span>Connect</span>
            </Link>
          )}
        </div>
      </div>
    </aside>
  );
};
