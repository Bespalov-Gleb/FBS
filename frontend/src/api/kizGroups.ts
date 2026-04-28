import { apiClient } from './client';

export type KizGroup = {
  id: number;
  name: string;
  color?: string | null;
  size?: string | null;
  cut_type?: string | null;
  parser_markers?: Record<string, unknown> | null;
  marketplace_ids: number[];
  free_count: number;
  used_count: number;
  parser_errors_count: number;
};

export type ProductMappingRow = {
  marketplace_id: number;
  marketplace_name: string;
  article: string;
  size: string;
  product_name: string;
  group_id: number | null;
  group_name: string | null;
};

export type KizGroupPayload = {
  name: string;
  color?: string | null;
  size?: string | null;
  cut_type?: string | null;
  parser_markers?: Record<string, unknown> | null;
  marketplace_ids: number[];
};

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const kizGroupsApi = {
  async list(): Promise<KizGroup[]> {
    const { data } = await apiClient.get<KizGroup[]>('/kiz-groups');
    return data;
  },

  async create(payload: KizGroupPayload): Promise<KizGroup> {
    const { data } = await apiClient.post<KizGroup>('/kiz-groups', payload);
    return data;
  },

  async update(groupId: number, payload: KizGroupPayload): Promise<KizGroup> {
    const { data } = await apiClient.patch<KizGroup>(`/kiz-groups/${groupId}`, payload);
    return data;
  },

  async uploadPdf(groupId: number, files: File[]): Promise<{ imported: number; duplicates: number; errors: number }> {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    const { data } = await apiClient.post(`/kiz-groups/${groupId}/upload-pdf`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  async clearGroupItems(groupId: number): Promise<{ ok: boolean; deleted_pool: number; deleted_errors: number }> {
    const { data } = await apiClient.delete(`/kiz-groups/${groupId}/items`);
    return data;
  },

  async deleteGroup(groupId: number): Promise<{ ok: boolean }> {
    const { data } = await apiClient.delete(`/kiz-groups/${groupId}`);
    return data;
  },

  async upsertProductMapping(payload: {
    marketplace_id: number;
    article: string;
    size?: string;
    group_id: number;
  }): Promise<void> {
    await apiClient.post('/kiz-groups/product-mappings', payload);
  },

  async listProducts(search: string): Promise<ProductMappingRow[]> {
    const { data } = await apiClient.get<ProductMappingRow[]>('/kiz-groups/products', {
      params: { search },
    });
    return data;
  },

  async downloadReport(type: 'free' | 'used' | 'errors'): Promise<void> {
    const { data } = await apiClient.get('/kiz-groups/reports', {
      params: { report_type: type },
      responseType: 'blob',
    });
    downloadBlob(data, `kiz-report-${type}.xlsx`);
  },

  async downloadProductsExport(): Promise<void> {
    const { data } = await apiClient.get('/kiz-groups/products/export', { responseType: 'blob' });
    downloadBlob(data, 'kiz-product-mapping.xlsx');
  },

  async importProductsFile(file: File): Promise<{ created: number; updated: number; skipped: number }> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await apiClient.post('/kiz-groups/products/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },
};
