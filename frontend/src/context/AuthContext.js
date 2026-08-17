import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { clearCache } from "@/utils/apiCache";

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL + "/api";

// P3b: withCredentials=true sends HttpOnly cookies on every request.
// Tokens no longer stored in localStorage — cookies are set by the server.
axios.defaults.withCredentials = true;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading
  const isRefreshing = useRef(false);
  const refreshQueue = useRef([]); // pending requests waiting for refresh

  // Silent token refresh — cookie sent automatically; no explicit token needed
  const silentRefresh = async () => {
    // POST to /auth/refresh; supervision_refresh cookie auto-sent by browser.
    // Server sets a new supervision_access cookie on success.
    await axios.post(`${API}/auth/refresh`, {});
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
            }).then(() => {
              // Cookie refreshed — replay without stale Authorization header
              delete original.headers?.Authorization;
              return axios(original);
            });
          }

          original._retry = true;
          isRefreshing.current = true;

          try {
            await silentRefresh();
            isRefreshing.current = false;
            refreshQueue.current.forEach(p => p.resolve());
            refreshQueue.current = [];
            // Cookie is now fresh — replay request; no Authorization header needed
            delete original.headers?.Authorization;
            return axios(original);
          } catch {
            isRefreshing.current = false;
            refreshQueue.current.forEach(p => p.reject());
            refreshQueue.current = [];
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

  // On mount: /auth/me is called with withCredentials=true — cookie auto-sent
  useEffect(() => {
    axios.get(`${API}/auth/me`)
      .then(r => setUser(r.data))
      .catch(() => setUser(null));
  }, []);

  const login = async (email, password) => {
    const { data } = await axios.post(`${API}/auth/login`, { email, password });
    if (data.requires_mfa) return data; // MFA pending — caller handles OTP flow
    // P3b: server sets HttpOnly cookies; no localStorage writes needed
    setUser(data);
    // Fetch full profile (includes org_branding, org_name) via cookie
    try {
      const { data: profile } = await axios.get(`${API}/auth/me`);
      setUser(profile);
      return profile;
    } catch {
      return data;
    }
  };

  const completeLogin = async (data) => {
    // P3b: server set cookies during verify-mfa; just update state
    setUser(data);
    try {
      const { data: profile } = await axios.get(`${API}/auth/me`);
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
    // P3b: server sets cookies
    setUser(data);
    return data;
  };

  const logout = async () => {
    try {
      // Server clears HttpOnly cookies
      await axios.post(`${API}/auth/logout`);
    } catch {}
    // Also clear any legacy localStorage tokens from pre-migration sessions
    localStorage.removeItem("supervision_token");
    localStorage.removeItem("supervision_refresh_token");
    clearCache();
    setUser(null);
  };

  // P3b: returns empty config — HttpOnly cookies are sent automatically via
  // axios.defaults.withCredentials = true. Kept for call-site compatibility.
  const getAuthConfig = () => ({});

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
