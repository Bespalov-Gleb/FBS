import { apiClient } from './client';
import type { User } from '../types/api';

export interface UserCreate {
  email: string;
  password: string;
  full_name: string;
  role?: string;
}

export interface UserUpdate {
  full_name?: string;
  role?: string;
  is_active?: boolean;
}

export const usersApi = {
  list: async (params?: { skip?: number; limit?: number }): Promise<User[]> => {
    const { data } = await apiClient.get<User[]>('/users', { params });
    return data;
  },

  get: async (id: number): Promise<User> => {
    const { data } = await apiClient.get<User>(`/users/${id}`);
    return data;
  },

  create: async (payload: UserCreate): Promise<User> => {
    const { data } = await apiClient.post<User>('/users', payload);
    return data;
  },

  update: async (id: number, payload: UserUpdate): Promise<User> => {
    const { data } = await apiClient.patch<User>(`/users/${id}`, payload);
    return data;
  },

  deactivate: async (id: number): Promise<void> => {
    await apiClient.delete(`/users/${id}`);
  },
};
