import { apiClient } from './client';
import type { TokenResponse, UserMe } from '../types/api';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterCredentials {
  email: string;
  password: string;
  full_name: string;
}

export const authApi = {
  register: async (credentials: RegisterCredentials): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/register', credentials);
    return data;
  },

  login: async (credentials: LoginCredentials): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/login', credentials);
    return data;
  },

  refresh: async (refreshToken: string): Promise<{ access_token: string }> => {
    const { data } = await apiClient.post<{ access_token: string }>('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return data;
  },

  me: async (): Promise<UserMe> => {
    const { data } = await apiClient.get<UserMe>('/auth/me');
    return data;
  },
};
