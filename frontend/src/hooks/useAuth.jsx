import { createContext, useContext, useEffect, useState } from 'react';
import { post, setLogoutHandler, setTokens } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem('isosafe_user');
    return raw ? JSON.parse(raw) : null;
  });

  useEffect(() => {
    setLogoutHandler(() => {
      localStorage.removeItem('isosafe_user');
      setUser(null);
    });
  }, []);

  const login = async (email, password) => {
    const data = await post('/api/auth/login', { email, password });
    setTokens(data.access_token, data.refresh_token);
    const u = { email: data.email, role: data.role };
    localStorage.setItem('isosafe_user', JSON.stringify(u));
    setUser(u);
  };

  const logout = () => {
    setTokens(null, null);
    localStorage.removeItem('isosafe_user');
    setUser(null);
  };

  const roleRank = { viewer: 0, operator: 1, admin: 2 };
  const hasRole = (min) => user && roleRank[user.role] >= roleRank[min];

  return (
    <AuthContext.Provider value={{ user, login, logout, hasRole }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
