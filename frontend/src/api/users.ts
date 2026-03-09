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

export interface StaticInviteCode {
  code: string;
}

export interface MarketplaceAccess {
  marketplace_id: number;
  marketplace_name: string;
}

export interface UserStats {
  orders_last_hour: number;
  orders_today: number;
  orders_total: number;
  avg_minutes_per_order: number | null;
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

  getMyInviteCode: async (): Promise<StaticInviteCode> => {
    const { data } = await apiClient.get<StaticInviteCode>('/users/my-invite-code');
    return data;
  },

  regenerateMyInviteCode: async (): Promise<StaticInviteCode> => {
    const { data } = await apiClient.post<StaticInviteCode>('/users/my-invite-code/regenerate');
    return data;
  },

  getMarketplaceAccess: async (userId: number): Promise<MarketplaceAccess[]> => {
    const { data } = await apiClient.get<MarketplaceAccess[]>(`/users/${userId}/marketplace-access`);
    return data;
  },

  setMarketplaceAccess: async (userId: number, marketplaceIds: number[]): Promise<void> => {
    await apiClient.put(`/users/${userId}/marketplace-access`, { marketplace_ids: marketplaceIds });
  },

  getStats: async (userId: number): Promise<UserStats> => {
    const { data } = await apiClient.get<UserStats>(`/users/${userId}/stats`);
    return data;
  },
};
