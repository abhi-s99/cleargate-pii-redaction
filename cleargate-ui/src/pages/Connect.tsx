import React, { useState } from 'react';
import { useAuth } from '../app/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useHealthQuery } from '../api/queries';
import { HealthCard } from '../components/HealthCard';
import { UserRole } from '../domain/states';
import { KeyRound, Shield, UserCheck, ArrowRight } from 'lucide-react';

export const ConnectPage: React.FC = () => {
  const { login, token: existingToken, role: existingRole } = useAuth();
  const navigate = useNavigate();
  const { data: health, isLoading: healthLoading, error: healthError } = useHealthQuery();

  const [inputToken, setInputToken] = useState(existingToken || '');
  const [selectedRole, setSelectedRole] = useState<UserRole>(existingRole || 'submitter');
  const [persistInTab, setPersistInTab] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!inputToken.trim()) {
      setErrorMessage('Please enter an authentication bearer token.');
      return;
    }

    // Connect user and persist in memory (and session storage if checked)
    login(inputToken.trim(), selectedRole, persistInTab);
    navigate('/');
  };

  return (
    <div className="max-w-container mx-auto px-4 sm:px-6 py-12 flex-1">
      <div className="max-w-xl mx-auto space-y-8">
        <div>
          <span className="text-xs font-mono text-accent font-semibold uppercase tracking-wider">
            ClearGate Gateway Session
          </span>
          <h1 className="text-3xl font-heading font-extrabold text-text mt-1">
            Connect to Privacy Gate
          </h1>
          <p className="text-sm text-text-muted mt-2">
            Supply your role bearer token to interact with the privacy enforcement service. No document data is stored locally.
          </p>
        </div>

        {/* Backend health status card */}
        <HealthCard
          health={health}
          isLoading={healthLoading}
          error={healthError ? healthError.message : null}
        />

        {/* Authentication form */}
        <form
          onSubmit={handleSubmit}
          className="bg-surface border border-border rounded-lg p-6 space-y-6 shadow-card"
        >
          {errorMessage && (
            <div className="p-3 rounded bg-status-failed-bg text-status-failed border border-status-failed/30 text-xs">
              {errorMessage}
            </div>
          )}

          {/* Role selector */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-text uppercase tracking-wider block">
              Select Role Context
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSelectedRole('submitter')}
                className={`p-3.5 rounded-md border text-left flex flex-col justify-between transition-all ${
                  selectedRole === 'submitter'
                    ? 'border-accent bg-accent/15 text-text ring-1 ring-accent'
                    : 'border-border bg-surface-raised text-text-muted hover:border-text-muted'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <UserCheck className="w-4 h-4 text-accent" />
                  <span className="font-semibold text-sm text-text">Submitter</span>
                </div>
                <span className="text-[11px] text-text-muted">
                  Upload documents, track batches, download verified outputs.
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedRole('reviewer')}
                className={`p-3.5 rounded-md border text-left flex flex-col justify-between transition-all ${
                  selectedRole === 'reviewer'
                    ? 'border-accent bg-accent/15 text-text ring-1 ring-accent'
                    : 'border-border bg-surface-raised text-text-muted hover:border-text-muted'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Shield className="w-4 h-4 text-accent" />
                  <span className="font-semibold text-sm text-text">Privacy Reviewer</span>
                </div>
                <span className="text-[11px] text-text-muted">
                  Inspect candidate PII findings and resolve uncertain masks.
                </span>
              </button>
            </div>
          </div>

          {/* Bearer token input */}
          <div className="space-y-1.5">
            <label
              htmlFor="bearerToken"
              className="text-xs font-semibold text-text uppercase tracking-wider block"
            >
              Bearer Token
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
                <KeyRound className="w-4 h-4" />
              </div>
              <input
                id="bearerToken"
                type="password"
                value={inputToken}
                onChange={(e) => setInputToken(e.target.value)}
                placeholder="Paste bearer token..."
                className="w-full pl-10 pr-4 py-2.5 bg-bg-alt border border-border rounded-md text-text text-sm focus:ring-2 focus:ring-focus-ring focus:border-accent"
              />
            </div>
            <p className="text-[11px] text-text-muted">
              Use the tokens from the server&apos;s <code>.env</code>: <code>CLEARGATE_SUBMITTER_TOKEN</code> for Submitter,
              <code>CLEARGATE_REVIEWER_TOKEN</code> for Privacy Reviewer. (Mock mode accepts any token containing <code>reviewer</code>.)
            </p>
          </div>

          {/* Session Storage Opt-in */}
          <div className="flex items-center gap-2 pt-1">
            <input
              id="persistInTab"
              type="checkbox"
              checked={persistInTab}
              onChange={(e) => setPersistInTab(e.target.checked)}
              className="rounded border-border text-accent focus:ring-accent w-4 h-4 bg-bg-alt"
            />
            <label htmlFor="persistInTab" className="text-xs text-text-muted cursor-pointer select-none">
              Keep token for this browser tab only (cleared on tab close)
            </label>
          </div>

          <button
            type="submit"
            className="w-full bg-accent hover:bg-accent-hover text-text-on-accent font-semibold py-2.5 px-4 rounded-md transition-colors shadow flex items-center justify-center gap-2"
          >
            <span>Connect & Authorize</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};
