import React, { createContext, useContext, useState, useEffect } from "react";
import axios from "axios";

const AuthContext = createContext(null);
const API = process.env.REACT_APP_BACKEND_URL + "/api";

axios.defaults.withCredentials = true;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading

  useEffect(() => {
    // Try cookie auth first, then localStorage token
    const token = localStorage.getItem("supervision_token");
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    axios.get(`${API}/auth/me`, config)
      .then(r => setUser(r.data))
      .catch(() => setUser(null));
  }, []);

  const login = async (email, password) => {
    const { data } = await axios.post(`${API}/auth/login`, { email, password });
    if (data.token) localStorage.setItem("supervision_token", data.token);
    setUser(data);
    return data;
  };

  const register = async (email, password, name, role) => {
    const { data } = await axios.post(`${API}/auth/register`, { email, password, name, role });
    if (data.token) localStorage.setItem("supervision_token", data.token);
    setUser(data);
    return data;
  };

  const logout = async () => {
    try { await axios.post(`${API}/auth/logout`); } catch {}
    localStorage.removeItem("supervision_token");
    setUser(null);
  };

  const getAuthConfig = () => {
    const token = localStorage.getItem("supervision_token");
    return token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  };

  return (
    <AuthContext.Provider value={{ user, login, register, logout, getAuthConfig, API }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
