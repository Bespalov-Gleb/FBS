import axios from 'axios';
import { apiClient } from './client';

type BuildTableResponse = {
  blob: Blob;
  filename: string;
};

const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

function parseFilename(contentDisposition?: string): string {
  if (!contentDisposition) return 'table.xlsx';

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const simpleMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1];
  }

  return 'table.xlsx';
}

export const tableBuilderApi = {
  async build(files: File[]): Promise<BuildTableResponse> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    try {
      const response = await apiClient.post('/table-builder/build', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        responseType: 'blob',
      });

      const filename = parseFilename(response.headers['content-disposition']);
      const blob = new Blob([response.data], { type: XLSX_MIME });
      return { blob, filename };
    } catch (error: unknown) {
      if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
        const text = await error.response.data.text();
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed.detail) {
            throw new Error(parsed.detail);
          }
        } catch {
          // leave generic error message below
        }
      }
      throw error;
    }
  },
};
