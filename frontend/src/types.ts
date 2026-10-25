export type GenerationStatus = 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type ProcessType = 'fdm' | 'sla' | 'cnc' | 'injection';
export type MaterialType = 'pla' | 'petg' | 'abs' | 'resin' | 'aluminum';
export type GenerationMode = 'standard' | 'advanced' | 'agent';
export type ToastKind = 'ok' | 'err' | 'info' | 'wait';

export interface ModelParameters {
  kind: string;
  width: number;
  depth: number;
  height: number;
  compartments: number;
  chamfer: number;
  wall: number;
  bottom: number;
  drainage_holes?: number;
  cable_channel?: boolean;
  process: string;
  tolerance?: number;
  clearance?: number;
  material: string;
  edge_style?: string;
}

export interface ModelResult {
  model_id: string;
  title: string;
  parameters: ModelParameters;
  checks: Record<string, unknown>;
  artifacts: Record<string, string>;
  process: string;
  profile?: Record<string, unknown>;
  analysis?: Record<string, unknown>;
  step_schema?: string;
  mode?: string;
  generation_strategy?: string;
  llm_used?: boolean;
  assumptions?: string[];
  provenance?: Record<string, unknown>;
  design_ir?: Record<string, unknown>;
  generation_trace?: Array<Record<string, unknown>>;
  agent_summary?: Record<string, unknown>;
}

export interface GenerationProgress {
  stage?: string;
  current_step?: string | null;
  elapsed_ms?: number;
  events?: Array<Record<string, unknown>>;
}

export interface HistoryItem {
  id: string;
  title: string;
  prompt: string;
  createdAt: number;
  process: ProcessType;
  material: MaterialType;
  result?: ModelResult;
}

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  detail: string;
  action?: string;
  createdAt: number;
}

export interface MeasureResult {
  model_id: string;
  valid_brep: boolean;
  solid_count: number;
  face_count: number;
  volume_mm3: number;
  surface_area_mm2: number;
  bbox_mm: { x: number; y: number; z: number };
  units: string;
  dimensions: { width: number; depth: number; height: number };
}

export interface GenerateSettings {
  units: 'mm' | 'cm' | 'm' | 'in';
  process: ProcessType;
  mode: GenerationMode;
  material: MaterialType;
  include_steps: boolean;
  generation_strategy: 'ir' | 'auto' | 'legacy';
  mold_pull_direction?: number[];
}
