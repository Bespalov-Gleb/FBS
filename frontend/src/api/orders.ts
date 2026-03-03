import { apiClient } from './client';
import type { Order } from '../types/api';

export interface OrdersParams {
  skip?: number;
  limit?: number;
  marketplace_id?: number;
  marketplace_type?: 'ozon' | 'wildberries';
  warehouse_id?: number;
  status?: string;
  search?: string;
  sort_by?: string;
  sort_desc?: boolean;
}

export interface OrderCompletePayload {
  kiz_code?: string;
}

export interface OrdersStats {
  total: number;
  on_assembly: number;
  completed: number;
  completed_today: number;
  by_marketplace: Array<{
    marketplace_id: number;
    name: string;
    type: string | null;
    total: number;
    completed: number;
  }>;
}

export interface OrdersListResponse {
  items: Order[];
  total: number;
}

export const ordersApi = {
  list: async (params?: OrdersParams): Promise<OrdersListResponse> => {
    const { data } = await apiClient.get<OrdersListResponse>('/orders', { params });
    return data;
  },

  get: async (id: number): Promise<Order> => {
    const { data } = await apiClient.get<Order>(`/orders/${id}`);
    return data;
  },

  claim: async (id: number): Promise<{ ok: boolean }> => {
    const { data } = await apiClient.post<{ ok: boolean }>(`/orders/${id}/claim`);
    return data;
  },

  release: async (id: number): Promise<{ ok: boolean }> => {
    const { data } = await apiClient.post<{ ok: boolean }>(`/orders/${id}/release`);
    return data;
  },

  complete: async (id: number, payload?: OrderCompletePayload): Promise<{ ok: boolean }> => {
    const { data } = await apiClient.post<{ ok: boolean }>(`/orders/${id}/complete`, payload);
    return data;
  },

  getStats: async (): Promise<OrdersStats> => {
    const { data } = await apiClient.get<OrdersStats>('/orders/stats');
    return data;
  },

  syncAll: async (): Promise<{ total_synced: number }> => {
    const { data } = await apiClient.post<{ total_synced: number }>('/orders/sync/all');
    return data;
  },

  syncMarketplace: async (marketplaceId: number): Promise<{ synced: number }> => {
    const { data } = await apiClient.post<{ synced: number }>(
      `/orders/sync/marketplace/${marketplaceId}`,
    );
    return data;
  },

  getLabelUrl: (id: number, format = 'pdf'): string => {
    const base = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
    const token = localStorage.getItem('access_token');
    return `${base}/orders/${id}/label?format=${format}${token ? `&token=${token}` : ''}`;
  },

  getLabelBlob: async (id: number, format = 'pdf', labelWidth?: number): Promise<Blob> => {
    const params: Record<string, string | number> = { format };
    if (labelWidth) params.width = labelWidth;
    const { data } = await apiClient.get(`/orders/${id}/label`, {
      params,
      responseType: 'blob',
    });
    return data;
  },

  getKizLabelBlob: async (kizCode: string): Promise<Blob> => {
    const { data } = await apiClient.get('/orders/kiz-label', {
      params: { kiz_code: kizCode.trim() },
      responseType: 'blob',
    });
    return data;
  },

  /** Выгрузка КИЗ собранных заказов (Excel или TXT). */
  getKizExportBlob: async (
    options?: { marketplace_id?: number; format?: 'xlsx' | 'txt' },
  ): Promise<Blob> => {
    const params: Record<string, string | number> = {
      export_format: options?.format ?? 'xlsx',
    };
    if (options?.marketplace_id != null) params.marketplace_id = options.marketplace_id;
    const { data } = await apiClient.get('/orders/kiz-export', {
      params,
      responseType: 'blob',
    });
    return data;
  },

  /** Штрихкод товара (только Ozon). 404 для WB. */
  getProductBarcodeBlob: async (orderId: number): Promise<Blob | null> => {
    try {
      const { data } = await apiClient.get(`/orders/${orderId}/product-barcode`, {
        responseType: 'blob',
      });
      return data;
    } catch {
      return null;
    }
  },
};
