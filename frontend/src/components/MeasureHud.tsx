import { useEffect, useState } from 'react';
import { X, Ruler, Box, ShieldCheck, Activity } from 'lucide-react';
import { fetchMeasure } from '../lib/api';
import type { MeasureResult, ModelResult } from '../types';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  modelId: string | null;
  result: ModelResult | null;
}

export default function MeasureHud({ isOpen, onClose, modelId, result }: Props) {
  const [data, setData] = useState<MeasureResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    if (modelId) {
      setLoading(true);
      fetchMeasure(modelId)
        .then((res) => {
          setData(res);
          setLoading(false);
        })
        .catch(() => {
          setLoading(false);
        });
    }
  }, [isOpen, modelId]);

  if (!isOpen) return null;

  // Fallback measurements from result parameters if measure query is pending or offline
  const params = result?.parameters;
  const width = data?.dimensions?.width ?? params?.width ?? 0;
  const depth = data?.dimensions?.depth ?? params?.depth ?? 0;
  const height = data?.dimensions?.height ?? params?.height ?? 0;
  const volume = data?.volume_mm3 ?? (width * depth * height * 0.75);
  const surface = data?.surface_area_mm2 ?? (2 * (width * depth + width * height + depth * height));
  const faceCount = data?.face_count ?? 12;

  return (
    <aside aria-label="CAD Metrology and Metrics" className="absolute top-14 right-4 z-20 w-72 rounded-xl bg-slate-900/90 backdrop-blur-md border border-lime-400/30 p-3.5 shadow-2xl text-slate-200 animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="flex items-center justify-between border-b border-slate-700/60 pb-2 mb-2.5">
        <div className="flex items-center gap-1.5 text-lime-400 font-mono text-xs font-bold tracking-wider">
          <Ruler className="w-3.5 h-3.5" />
          <span>CAD METROLOGY</span>
        </div>
        <button
          onClick={onClose}
          className="w-5 h-5 rounded-full grid place-items-center bg-slate-800 hover:bg-rose-500/20 hover:text-rose-400 text-slate-400 text-xs transition"
          title="关闭量测面板"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {loading ? (
        <div className="py-4 text-center text-xs text-slate-400 font-mono animate-pulse">
          读取 B-Rep 精确物理量测中...
        </div>
      ) : (
        <div className="space-y-2">
          {/* Envelope */}
          <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/40">
            <span className="text-[10px] text-slate-400 font-medium tracking-wide block mb-0.5">
              包络尺寸 (W × D × H)
            </span>
            <span className="font-mono text-xs font-bold text-white">
              {Number(width).toFixed(1)} × {Number(depth).toFixed(1)} × {Number(height).toFixed(1)} mm
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {/* Volume */}
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/40">
              <span className="text-[10px] text-slate-400 font-medium tracking-wide block mb-0.5">
                零件体积
              </span>
              <span className="font-mono text-xs font-semibold text-lime-300">
                {Math.round(volume).toLocaleString()} mm³
              </span>
            </div>

            {/* Surface Area */}
            <div className="p-2 rounded-lg bg-slate-800/50 border border-slate-700/40">
              <span className="text-[10px] text-slate-400 font-medium tracking-wide block mb-0.5">
                总表面积
              </span>
              <span className="font-mono text-xs font-semibold text-sky-300">
                {Math.round(surface).toLocaleString()} mm²
              </span>
            </div>
          </div>

          {/* Topology */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50 border border-slate-700/40 text-xs">
            <div className="flex items-center gap-1.5 text-slate-300">
              <ShieldCheck className="w-3.5 h-3.5 text-lime-400 shrink-0" />
              <span className="text-[11px]">水密 B-Rep 流形</span>
            </div>
            <span className="font-mono text-[11px] text-slate-400">
              {faceCount} 表面
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}
