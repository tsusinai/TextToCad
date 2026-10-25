import { useEffect, useState } from 'react';
import { Download, Printer, X, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';
import { fetchDrawingSvg } from '../lib/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  modelId: string | null;
  title: string;
}

export default function DrawingModal({ isOpen, onClose, modelId, title }: Props) {
  const [svgContent, setSvgContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    if (!isOpen || !modelId) {
      setSvgContent('');
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setZoom(1);

    fetchDrawingSvg(modelId, controller.signal)
      .then((svg) => {
        setSvgContent(svg);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') {
          setError(err.message || '获取工程图纸失败');
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [isOpen, modelId]);

  if (!isOpen) return null;

  const handleDownload = () => {
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `blueprint-${(modelId || 'cad').slice(0, 8)}.svg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const handlePrint = () => {
    if (!svgContent) return;
    const printWindow = window.open('', '_blank');
    if (!printWindow) return;
    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
        <head>
          <title>${title} · ISO 2D Blueprint</title>
          <style>
            body { margin: 0; padding: 20px; display: grid; place-items: center; background: #fff; }
            svg { width: 95vw; height: auto; max-height: 92vh; }
            @media print {
              body { padding: 0; }
              svg { width: 100%; height: 100%; }
            }
          </style>
        </head>
        <body>
          ${svgContent}
        </body>
      </html>
    `);
    printWindow.document.close();
    setTimeout(() => printWindow.print(), 300);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-10">
      <div
        className="fixed inset-0 bg-black/80 backdrop-blur-md transition-opacity"
        onClick={onClose}
      />
      <div className="relative w-full max-w-5xl h-[88vh] bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl flex flex-col overflow-hidden z-10 text-slate-100">
        {/* Header */}
        <div className="h-14 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-950/60 shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-lime-400 font-mono text-lg font-bold">📐</span>
            <div>
              <h2 className="text-sm font-semibold text-slate-100 font-mono">
                ISO 2D TECHNICAL DRAWING
              </h2>
              <p className="text-xs text-slate-400 truncate max-w-sm sm:max-w-md">
                {title} {modelId ? `· ID: ${modelId.slice(0, 8)}` : ''}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setZoom((z) => Math.max(0.6, z - 0.2))}
              className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white transition"
              title="缩小"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button
              onClick={() => setZoom(1)}
              className="px-2 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-mono transition"
              title="重置缩放"
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              onClick={() => setZoom((z) => Math.min(2.5, z + 0.2))}
              className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white transition"
              title="放大"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <span className="w-px h-5 bg-slate-700 mx-1" />
            <button
              onClick={handlePrint}
              disabled={!svgContent}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition disabled:opacity-50"
              title="打印工程制图"
            >
              <Printer className="w-3.5 h-3.5 text-slate-300" />
              <span className="hidden sm:inline">打印</span>
            </button>
            <button
              onClick={handleDownload}
              disabled={!svgContent}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-lime-400/20 hover:bg-lime-400/30 text-lime-300 border border-lime-400/30 text-xs font-medium transition disabled:opacity-50"
              title="下载 SVG 矢量蓝图"
            >
              <Download className="w-3.5 h-3.5" />
              <span>下载 SVG</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-rose-500/20 hover:text-rose-300 text-slate-400 transition ml-2"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-auto p-4 sm:p-8 flex items-center justify-center bg-slate-950/40 relative">
          {loading && (
            <div className="flex flex-col items-center gap-3 text-slate-400">
              <div className="w-7 h-7 border-2 border-lime-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-xs font-mono">正在渲染 ISO 标准三视图蓝图...</p>
            </div>
          )}

          {error && (
            <div className="text-center p-6 bg-rose-950/30 border border-rose-800/50 rounded-xl text-rose-300 max-w-md">
              <p className="text-sm font-semibold mb-1">工程图纸加载失败</p>
              <p className="text-xs text-rose-400/80 font-mono">{error}</p>
            </div>
          )}

          {!loading && !error && svgContent && (
            <div
              className="w-full h-full flex items-center justify-center transition-transform duration-200 ease-out"
              style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
