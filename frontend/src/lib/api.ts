import type { GenerateSettings, GenerationProgress, ModelResult } from '../types';

const queryBackend = new URLSearchParams(window.location.search).get('backend');
const globalConfig = window as Window & {
  FORMA_BACKEND_URL?: string;
  FORM_CAD_BACKEND_URL?: string;
  FORM_CAD_BACKEND_API_KEY?: string;
};
export const BACKEND_URL = globalConfig.FORMA_BACKEND_URL
  || globalConfig.FORM_CAD_BACKEND_URL
  || queryBackend
  || import.meta.env.VITE_BACKEND_URL
  || (['localhost', '127.0.0.1'].includes(window.location.hostname) ? 'http://localhost:8787' : '/cad');
const API_KEY = globalConfig.FORM_CAD_BACKEND_API_KEY || import.meta.env.VITE_BACKEND_API_KEY || localStorage.getItem('forma-api-key') || '';

export function resolveBackendUrl(path: string) {
  if (/^https?:\/\//.test(path)) return path;
  return `${BACKEND_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
}

async function backendFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (API_KEY) headers.set('x-api-key', API_KEY);
  return fetch(resolveBackendUrl(path), { ...init, headers });
}

function detail(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback;
  const value = payload as Record<string, unknown>;
  if (typeof value.detail === 'string') return value.detail;
  if (value.error && typeof value.error === 'object') {
    const error = value.error as Record<string, unknown>;
    if (typeof error.detail === 'string') return error.detail;
  }
  return fallback;
}

async function errorFrom(response: Response) {
  const payload = await response.json().catch(() => null);
  return new Error(detail(payload, `几何引擎返回 ${response.status}`));
}

function wait(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}

export async function checkHealth(signal?: AbortSignal) {
  const response = await backendFetch('/health', { signal });
  if (!response.ok) throw await errorFrom(response);
  return response.json();
}

export async function generateModel(
  prompt: string,
  settings: GenerateSettings,
  signal: AbortSignal,
  onProgress: (progress: GenerationProgress) => void,
): Promise<ModelResult> {
  const payload = { prompt, ...settings };
  const jobResponse = await backendFetch('/v1/jobs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });

  if (jobResponse.status === 404) {
    const response = await backendFetch('/v1/models', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok) throw await errorFrom(response);
    return response.json();
  }
  if (!jobResponse.ok) throw await errorFrom(jobResponse);
  const job = await jobResponse.json() as { job_id: string };
  const cancelRemote = () => { void backendFetch(`/v1/jobs/${job.job_id}`, { method: 'DELETE', keepalive: true }).catch(() => {}); };
  signal.addEventListener('abort', cancelRemote, { once: true });

  try {
    onProgress({ stage: 'queued', current_step: null, elapsed_ms: 0, events: [] });
    while (true) {
      const response = await backendFetch(`/v1/jobs/${job.job_id}`, { signal });
      if (!response.ok) throw await errorFrom(response);
      const status = await response.json();
      if (status.progress) onProgress(status.progress);
      if (status.status === 'succeeded') return status.result as ModelResult;
      if (status.status === 'cancelled') throw new DOMException('Cancelled', 'AbortError');
      if (status.status === 'failed') throw new Error(detail(status.error, '模型生成失败'));
      await wait(350, signal);
    }
  } finally {
    signal.removeEventListener('abort', cancelRemote);
  }
}

export async function fetchGlb(modelId: string, signal?: AbortSignal) {
  const response = await backendFetch(`/v1/models/${modelId}/download?format=glb`, { signal });
  if (!response.ok) throw await errorFrom(response);
  return response.arrayBuffer();
}

export async function downloadModel(modelId: string, format: 'step' | 'stl' | '3mf' | 'glb') {
  const response = await backendFetch(`/v1/models/${modelId}/download?format=${format}`);
  if (!response.ok) throw await errorFrom(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `FORMA-${modelId.slice(0, 8)}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fetchDrawingSvg(modelId: string, signal?: AbortSignal): Promise<string> {
  const response = await backendFetch(`/v1/models/${modelId}/drawing`, { signal });
  if (!response.ok) throw await errorFrom(response);
  return response.text();
}

export async function fetchMeasure(modelId: string, signal?: AbortSignal): Promise<import('../types').MeasureResult> {
  const response = await backendFetch(`/v1/models/${modelId}/measure`, { signal });
  if (!response.ok) throw await errorFrom(response);
  return response.json();
}
