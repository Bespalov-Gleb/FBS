import { apiClient } from './client';
import type { Warehouse } from '../types/api';

export const warehousesApi = {
  listAll: async (marketplaceType?: 'ozon' | 'wildberries'): Promise<Warehouse[]> => {
    const { data } = await apiClient.get<Warehouse[]>('/warehouses', {
      params: marketplaceType ? { marketplace_type: marketplaceType } : undefined,
    });
    return data;
  },

  listByMarketplace: async (marketplaceId: number): Promise<Warehouse[]> => {
    const { data } = await apiClient.get<Warehouse[]>(
      `/warehouses/marketplace/${marketplaceId}`,
    );
    return data;
  },

  sync: async (marketplaceId: number): Promise<{ synced: number }> => {
    const { data } = await apiClient.post<{ synced: number }>(
      `/warehouses/marketplace/${marketplaceId}/sync`,
    );
    return data;
  },

  updateColor: async (warehouseId: number, color: string): Promise<Warehouse> => {
    const { data } = await apiClient.patch<Warehouse>(`/warehouses/${warehouseId}/color`, {
      color,
    });
    return data;
  },
};
