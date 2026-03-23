import { apiClient } from './client';
import type { Order } from '../types/api';

export interface OrdersParams {
  skip?: number;
  limit?: number;
  marketplace_ids?: number[];
  marketplace_types?: ('ozon' | 'wildberries')[];
  warehouse_ids?: number[];
  status?: string;
  search?: string;
  sort_by?: string;
  sort_desc?: boolean;
}

export interface OrderCompletePayload {
  /** Один КИЗ (для заказа с 1 товаром) */
  kiz_code?: string;
  /** Массив КИЗ — по одному на каждый товар (для заказов с 2+ товарами) */
  kiz_codes?: string[];
}

export interface OrdersStats {
  total: number;
  total_items?: number;
  on_assembly: number;
  on_assembly_items?: number;
  completed: number;
  completed_items?: number;
  completed_today: number;
  completed_today_items?: number;
  completed_week?: number;
  completed_week_items?: number;
  completed_month?: number;
  completed_month_items?: number;
  speed_items_per_hour_week?: number;
  by_marketplace: Array<{
    marketplace_id: number;
    name: string;
    type: string | null;
    total: number;
    completed: number;
    total_items?: number;
    completed_items?: number;
  }>;
}

export interface OrdersListResponse {
  items: Order[];
  total: number;
}

/** Сериализация params с массивами: marketplace_ids=1&marketplace_ids=2 для FastAPI */
function stringifyOrdersParams(params: OrdersParams): string {
  const pairs: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      value.forEach((v) => pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`));
    } else {
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  return pairs.join('&');
}

export const ordersApi = {
  list: async (params?: OrdersParams): Promise<OrdersListResponse> => {
    const query = params ? stringifyOrdersParams(params) : '';
    const url = query ? `/orders?${query}` : '/orders';
    const { data } = await apiClient.get<OrdersListResponse>(url);
    return data;
  },

  /** Список собранных заказов (отмечены «Собрано» в приложении). */
  listCompleted: async (
    params?: Omit<OrdersParams, 'status'> & { sort_by?: string },
  ): Promise<OrdersListResponse> => {
    const p = { ...params, sort_by: params?.sort_by ?? 'completed_at' };
    const query = p ? stringifyOrdersParams(p as OrdersParams) : '';
    const url = query ? `/orders/completed?${query}` : '/orders/completed';
    const { data } = await apiClient.get<OrdersListResponse>(url);
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

  getLabelBlob: async (id: number, format = 'pdf', labelWidth?: number, labelHeight?: number): Promise<Blob> => {
    const params: Record<string, string | number> = { format, _: Date.now() };
    if (labelWidth) params.width = labelWidth;
    if (labelHeight) params.height = labelHeight;
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

  /** Количество отсканированных КИЗ в таблице пользователя. */
  getKizScansCount: async (): Promise<{ count: number }> => {
    const { data } = await apiClient.get<{ count: number }>('/orders/kiz-scans');
    return data;
  },

  /** Очистить таблицу отсканированных КИЗ (начать новый рабочий день). */
  clearKizScans: async (): Promise<{ ok: boolean; deleted: number }> => {
    const { data } = await apiClient.delete<{ ok: boolean; deleted: number }>('/orders/kiz-scans');
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

  /** Штрихкод товара (только Ozon). 404 для WB. PNG. */
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

  /** PDF с обоими штрихкодами (товар + ШК ФБС) для качественной печати. Только Ozon. */
  getBarcodesPdfBlob: async (orderId: number, labelWidth?: number): Promise<Blob | null> => {
    try {
      const params = labelWidth ? { label_width: labelWidth } : {};
      const { data } = await apiClient.get(`/orders/${orderId}/barcodes-pdf`, {
        params,
        responseType: 'blob',
      });
      return data;
    } catch {
      return null;
    }
  },
};
