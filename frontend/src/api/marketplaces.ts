import { apiClient } from './client';
import type { Marketplace } from '../types/api';

export interface MarketplaceCreate {
  type: string;
  name: string;
  api_key: string;
  client_id?: string;
  is_kiz_enabled?: boolean;
  save_kiz_to_file?: boolean;
}

export interface MarketplaceUpdate {
  name?: string;
  is_kiz_enabled?: boolean;
  save_kiz_to_file?: boolean;
  is_active?: boolean;
}

export const marketplacesApi = {
  list: async (): Promise<Marketplace[]> => {
    const { data } = await apiClient.get<Marketplace[]>('/marketplaces');
    return data;
  },

  get: async (id: number): Promise<Marketplace> => {
    const { data } = await apiClient.get<Marketplace>(`/marketplaces/${id}`);
    return data;
  },

  create: async (payload: MarketplaceCreate): Promise<Marketplace> => {
    const { data } = await apiClient.post<Marketplace>('/marketplaces', payload);
    return data;
  },

  update: async (id: number, payload: MarketplaceUpdate): Promise<Marketplace> => {
    const { data } = await apiClient.patch<Marketplace>(`/marketplaces/${id}`, payload);
    return data;
  },

  delete: async (id: number): Promise<void> => {
    await apiClient.delete(`/marketplaces/${id}`);
  },

  test: async (id: number): Promise<{ success: boolean }> => {
    const { data } = await apiClient.post<{ success: boolean }>(`/marketplaces/${id}/test`);
    return data;
  },
};
