import { apiClient } from './client';
import type { PrintSettings } from '../types/api';

export interface LabelSizeUpdate {
  width_mm?: number;
  height_mm?: number;
}

export interface PrintSettingsUpdate {
  default_printer?: string;
  label_format?: string;
  auto_print_on_click?: boolean;
  auto_print_kiz_duplicate?: boolean;
  ozon_labels?: LabelSizeUpdate;
  wb_labels?: LabelSizeUpdate;
}

export const printSettingsApi = {
  get: async (): Promise<PrintSettings> => {
    const { data } = await apiClient.get<PrintSettings>('/print-settings');
    return data;
  },

  update: async (payload: PrintSettingsUpdate): Promise<PrintSettings> => {
    const { data } = await apiClient.patch<PrintSettings>('/print-settings', payload);
    return data;
  },

  getTestLabelBlob: async (): Promise<Blob> => {
    const { data } = await apiClient.get('/print-settings/test-label', {
      responseType: 'blob',
    });
    return data;
  },
};
