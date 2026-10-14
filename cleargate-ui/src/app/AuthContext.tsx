import React, { createContext, useContext, useState, useEffect } from 'react';
import { UserRole } from '../domain/states';

interface AuthState {
  token: string | null;
  role: UserRole;
  isAuthenticated: boolean;
  persistInSession: boolean;
  login: (token: string, role: UserRole, persistInSession?: boolean) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

const SESSION_TOKEN_KEY = 'cleargate_auth_token';
const SESSION_ROLE_KEY = 'cleargate_auth_role';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // ASSUMPTION[A-2]: Token held in memory, with optional tab-only sessionStorage opt-in.
  const [token, setToken] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(SESSION_TOKEN_KEY);
    } catch {
      return null;
    }
  });

  const [role, setRole] = useState<UserRole>(() => {
    try {
      const stored = sessionStorage.getItem(SESSION_ROLE_KEY);
      return stored === 'reviewer' ? 'reviewer' : 'submitter';
    } catch {
      return 'submitter';
    }
  });

  const [persistInSession, setPersistInSession] = useState<boolean>(() => {
    try {
      return Boolean(sessionStorage.getItem(SESSION_TOKEN_KEY));
    } catch {
      return false;
    }
  });

  const login = (newToken: string, newRole: UserRole, shouldPersist = false) => {
    setToken(newToken);
    setRole(newRole);
    setPersistInSession(shouldPersist);
    if (shouldPersist) {
      try {
        sessionStorage.setItem(SESSION_TOKEN_KEY, newToken);
        sessionStorage.setItem(SESSION_ROLE_KEY, newRole);
      } catch {
        // Ignore session storage errors
      }
    } else {
      try {
        sessionStorage.removeItem(SESSION_TOKEN_KEY);
        sessionStorage.removeItem(SESSION_ROLE_KEY);
      } catch {
        // Ignore session storage errors
      }
    }
  };

  const logout = () => {
    setToken(null);
    setRole('submitter');
    setPersistInSession(false);
    try {
      sessionStorage.removeItem(SESSION_TOKEN_KEY);
      sessionStorage.removeItem(SESSION_ROLE_KEY);
    } catch {
      // Ignore session storage errors
    }
  };

  useEffect(() => {
    // Synchronize if tab storage changes
    const handleStorage = () => {
      const stored = sessionStorage.getItem(SESSION_TOKEN_KEY);
      if (!stored && token) {
        logout();
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [token]);

  return (
    <AuthContext.Provider
      value={{
        token,
        role,
        isAuthenticated: Boolean(token),
        persistInSession,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
