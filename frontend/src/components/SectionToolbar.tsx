import { Scissors, ArrowLeftRight } from 'lucide-react';

interface Props {
  isOpen: boolean;
  axis: 'none' | 'x' | 'y' | 'z';
  depth: number;
  flipped: boolean;
  onAxisChange: (axis: 'none' | 'x' | 'y' | 'z') => void;
  onDepthChange: (depth: number) => void;
  onFlipToggle: () => void;
}

export default function SectionToolbar({
  isOpen,
  axis,
  depth,
  flipped,
  onAxisChange,
  onDepthChange,
  onFlipToggle,
}: Props) {
  if (!isOpen) return null;

  const axes: Array<{ id: 'none' | 'x' | 'y' | 'z'; label: string }> = [
    { id: 'none', label: '关' },
    { id: 'x', label: 'X (YZ面)' },
    { id: 'y', label: 'Y (XZ面)' },
    { id: 'z', label: 'Z (XY面)' },
  ];

  return (
    <div className="absolute top-14 left-4 z-20 flex flex-wrap items-center gap-2.5 p-2 rounded-xl bg-slate-900/90 backdrop-blur-md border border-slate-700/80 shadow-2xl text-xs text-slate-200 animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="flex items-center gap-1.5 text-lime-400 font-mono font-bold pl-1">
        <Scissors className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">剖切审查:</span>
      </div>

      <div className="flex items-center gap-1 bg-slate-800/80 p-0.5 rounded-lg border border-slate-700/50">
        {axes.map((a) => (
          <button
            key={a.id}
            onClick={() => onAxisChange(a.id)}
            className={`px-2 py-1 rounded-md text-[11px] font-mono transition ${
              axis === a.id
                ? 'bg-lime-400 text-slate-950 font-bold shadow-sm'
                : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>

      {axis !== 'none' && (
        <div className="flex items-center gap-2 pl-1 animate-in fade-in duration-150">
          <input
            type="range"
            min={-50}
            max={50}
            step={0.5}
            value={depth}
            onChange={(e) => onDepthChange(parseFloat(e.target.value))}
            className="w-24 sm:w-28 h-1.5 accent-lime-400 bg-slate-700 rounded-lg cursor-pointer"
          />
          <span className="font-mono text-[11px] text-lime-300 min-w-12">
            {depth > 0 ? `+${depth.toFixed(1)}` : depth.toFixed(1)} mm
          </span>
          <button
            onClick={onFlipToggle}
            className={`p-1.5 rounded-lg border transition ${
              flipped
                ? 'bg-lime-400/20 border-lime-400/50 text-lime-300'
                : 'bg-slate-800 border-slate-700/60 text-slate-400 hover:text-white'
            }`}
            title="反转剖切方向"
          >
            <ArrowLeftRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}
