import { createSlice } from '@reduxjs/toolkit';
import type { UserMe } from '../types/api';

interface AuthState {
  user: UserMe | null;
  accessToken: string | null;
  refreshToken: string | null;
}

const loadTokens = (): { access: string | null; refresh: string | null } => {
  try {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');
    return { access, refresh };
  } catch {
    return { access: null, refresh: null };
  }
};

const { access, refresh } = loadTokens();

const initialState: AuthState = {
  user: null,
  accessToken: access,
  refreshToken: refresh,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials: (state, action) => {
      const { access_token, refresh_token } = action.payload;
      state.accessToken = access_token;
      state.refreshToken = refresh_token ?? state.refreshToken;
      if (access_token) {
        localStorage.setItem('access_token', access_token);
      }
      if (refresh_token) {
        localStorage.setItem('refresh_token', refresh_token);
      }
    },
    setUser: (state, action) => {
      state.user = action.payload;
    },
    logout: (state) => {
      state.user = null;
      state.accessToken = null;
      state.refreshToken = null;
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    },
  },
});

export const { setCredentials, setUser, logout } = authSlice.actions;
export default authSlice.reducer;
