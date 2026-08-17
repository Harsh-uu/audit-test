import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { clearCache } from "@/utils/apiCache";

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL + "/api";

axios.defaults.withCredentials = false;

// ── Token helpers ────────────────────────────────────────────────────────────
const getStoredToken = () => localStorage.getItem("supervision_token");
const getStoredRefresh = () => localStorage.getItem("supervision_refresh_token");

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading
  const isRefreshing = useRef(false);
  const refreshQueue = useRef([]); // pending requests waiting for refresh

  // Silent token refresh using stored refresh token
  const silentRefresh = async () => {
    const refreshToken = getStoredRefresh();
    if (!refreshToken) throw new Error("No refresh token");
    const { data } = await axios.post(
      `${API}/auth/refresh`,
      {},
      { headers: { Authorization: `Bearer ${refreshToken}` } }
    );
    localStorage.setItem("supervision_token", data.access_token);
    if (data.refresh_token) localStorage.setItem("supervision_refresh_token", data.refresh_token);
    return data.access_token;
  };

  // Axios response interceptor: auto-refresh on 401, then replay original request
  useEffect(() => {
    const id = axios.interceptors.response.use(
      res => res,
      async err => {
        const original = err.config;
        // Only retry once; skip auth endpoints to avoid loops
        if (
          err.response?.status === 401 &&
          !original._retry &&
          original.url &&
          !original.url.includes("/auth/")
        ) {
          if (isRefreshing.current) {
            // Queue this request until the ongoing refresh finishes
            return new Promise((resolve, reject) => {
              refreshQueue.current.push({ resolve, reject });
            }).then(newToken => {
              original.headers.Authorization = `Bearer ${newToken}`;
              return axios(original);
            });
          }

          original._retry = true;
          isRefreshing.current = true;

          try {
            const newToken = await silentRefresh();
            isRefreshing.current = false;
            refreshQueue.current.forEach(p => p.resolve(newToken));
            refreshQueue.current = [];
            original.headers = original.headers || {};
            original.headers.Authorization = `Bearer ${newToken}`;
            return axios(original);
          } catch {
            isRefreshing.current = false;
            refreshQueue.current.forEach(p => p.reject());
            refreshQueue.current = [];
            localStorage.removeItem("supervision_token");
            localStorage.removeItem("supervision_refresh_token");
            setUser(null);
            return Promise.reject(err);
          }
        }
        return Promise.reject(err);
      }
    );
    return () => axios.interceptors.response.eject(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const token = getStoredToken();
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    axios.get(`${API}/auth/me`, config)
      .then(r => setUser(r.data))
      .catch(() => setUser(null));
  }, []);

  const login = async (email, password) => {
    const { data } = await axios.post(`${API}/auth/login`, { email, password });
    if (data.requires_mfa) return data; // MFA pending — caller handles OTP flow
    if (data.token) localStorage.setItem("supervision_token", data.token);
    if (data.refresh_token) localStorage.setItem("supervision_refresh_token", data.refresh_token);
    setUser(data); // Set immediately so routes and navigation work right away
    // Fetch full profile (includes org_branding, org_name) in the background
    try {
      const { data: profile } = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${data.token}` },
      });
      setUser(profile);
      return profile;
    } catch {
      return data;
    }
  };

  const completeLogin = async (data) => {
    if (data.token) localStorage.setItem("supervision_token", data.token);
    if (data.refresh_token) localStorage.setItem("supervision_refresh_token", data.refresh_token);
    setUser(data); // Set immediately so navigation in the caller works without await
    // Fetch full profile so org_branding is populated
    try {
      const { data: profile } = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${data.token}` },
      });
      setUser(profile);
    } catch {
      // Keep login data as fallback
    }
  };

  const updateMfaStatus = (mfa_enabled) => {
    setUser(u => u ? { ...u, mfa_enabled } : u);
  };

  const register = async (email, password, name, role) => {
    const { data } = await axios.post(`${API}/auth/register`, { email, password, name, role });
    if (data.token) localStorage.setItem("supervision_token", data.token);
    if (data.refresh_token) localStorage.setItem("supervision_refresh_token", data.refresh_token);
    setUser(data);
    return data;
  };

  const logout = async () => {
    try { await axios.post(`${API}/auth/logout`); } catch {}
    localStorage.removeItem("supervision_token");
    localStorage.removeItem("supervision_refresh_token");
    clearCache();
    setUser(null);
  };

  const getAuthConfig = () => {
    const token = getStoredToken();
    return token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  };

  // Mutates the in-memory user.org_branding without a round-trip to /me
  const updateOrgBranding = (branding) => {
    setUser(u => u ? { ...u, org_branding: branding } : u);
  };

  // Mutates the in-memory user.org_name without a round-trip to /me
  const updateOrgName = (name) => {
    setUser(u => u ? { ...u, org_name: name } : u);
  };

  // Inject CSS variable whenever brand color changes
  useEffect(() => {
    const color = user?.org_branding?.primary_color;
    let el = document.getElementById("org-brand-vars");
    if (!el) {
      el = document.createElement("style");
      el.id = "org-brand-vars";
      document.head.appendChild(el);
    }
    el.textContent = `:root { --org-primary: ${color || "#1E3A8A"}; }`;
  }, [user?.org_branding?.primary_color]);

  const contextValue = useMemo(
    () => ({ user, login, register, logout, getAuthConfig, silentRefresh, API, updateOrgBranding, updateOrgName, completeLogin, updateMfaStatus }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user]
  );

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
