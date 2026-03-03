/**
 * API для связи с локальным агентом печати FBS Print Agent
 */
const AGENT_URL = import.meta.env.VITE_PRINT_AGENT_URL || 'http://127.0.0.1:9199';

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      const base64 = result.split(',')[1] ?? '';
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export async function isPrintAgentAvailable(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 500);
    const r = await fetch(`${AGENT_URL}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    return r.ok;
  } catch {
    return false;
  }
}

export async function getPrintAgentPrinters(): Promise<string[]> {
  try {
    const r = await fetch(`${AGENT_URL}/health`);
    if (!r.ok) return [];
    const data = await r.json();
    return Array.isArray(data.printers) ? data.printers : [];
  } catch {
    return [];
  }
}

const PRINT_TIMEOUT_MS = 60000; // 60 сек — печать может занять время

export async function printViaAgent(blob: Blob, printer?: string): Promise<boolean> {
  try {
    const base64 = await blobToBase64(blob);
    const mime = blob.type || 'application/pdf';
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PRINT_TIMEOUT_MS);
    const r = await fetch(`${AGENT_URL}/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: base64, printer: printer || undefined, mime }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return r.ok;
  } catch {
    return false;
  }
}
