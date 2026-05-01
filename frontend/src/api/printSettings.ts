import { apiClient } from './client';
import type { PrintSettings } from '../types/api';

export interface LabelSizeUpdate {
  width_mm?: number;
  height_mm?: number;
}

export interface LabelSizeWithRotateUpdate extends LabelSizeUpdate {
  rotate?: number;  // 0 / 90 / 180 / 270
}

export interface OzonLabelSizeUpdate extends LabelSizeWithRotateUpdate {}

export interface BarcodeLabelsUpdate {
  rotate?: number;  // 0 / 90 / 180 / 270
}

export interface PrintSettingsUpdate {
  default_printer?: string;
  label_format?: string;
  auto_print_on_click?: boolean;
  auto_print_kiz_duplicate?: boolean;
  auto_kiz_autofill?: boolean;
  printer_dpi?: number;  // 203 или 300
  label_print_mode?: 'as_is_fit' | 'standard_58x40_noscale';
  label_scale_factor?: number;  // 1.0–1.5
  ozon_labels?: LabelSizeWithRotateUpdate;
  wb_labels?: LabelSizeWithRotateUpdate;
  kiz_labels?: LabelSizeWithRotateUpdate;
  barcode_labels?: BarcodeLabelsUpdate;
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
