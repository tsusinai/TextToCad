/* Lucian UX/UI Prompt #002 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#002 */
import { useEffect, useRef } from 'react';
import './lucian-002.css';

interface Props {
  generating: boolean;
  disabled?: boolean;
  onGenerate: () => void;
}

export default function MagneticGenerateButton({ generating, disabled, onGenerate }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const generatingRef = useRef(generating);
  const onGenerateRef = useRef(onGenerate);
  useEffect(() => { generatingRef.current = generating; }, [generating]);
  useEffect(() => { onGenerateRef.current = onGenerate; }, [onGenerate]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const btn = root.querySelector<HTMLButtonElement>('.u002-btn')!;
    const mag = root.querySelector<HTMLElement>('.u002-mag')!;
    const txt = root.querySelector<HTMLElement>('.u002-txt')!;
    const orb = root.querySelector<HTMLElement>('.u002-orb')!;
    const live = root.querySelector<HTMLElement>('.u002-live')!;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let rm = motionQuery.matches;
    let timer = 0;

    const onMove = (event: PointerEvent) => {
      if (rm) return;
      const rect = btn.getBoundingClientRect();
      const dx = event.clientX - (rect.left + rect.width / 2);
      const dy = event.clientY - (rect.top + rect.height / 2);
      const proximity = Math.max(0, 1 - Math.hypot(dx, dy) / 240);
      mag.style.translate = `${(dx * .12 * proximity).toFixed(1)}px ${(dy * .22 * proximity).toFixed(1)}px`;
      txt.style.translate = `${(dx * .05 * proximity).toFixed(1)}px ${(dy * .08 * proximity).toFixed(1)}px`;
      orb.style.translate = `${(dx * .1 * proximity).toFixed(1)}px ${(dy * .14 * proximity).toFixed(1)}px`;
    };
    const onLeave = () => { mag.style.translate = txt.style.translate = orb.style.translate = '0px 0px'; };
    const onClick = () => {
      if (generatingRef.current || btn.disabled) return;
      window.clearTimeout(timer);
      root.dataset.state = 'idle';
      void btn.offsetWidth;
      root.dataset.state = 'go';
      live.textContent = '已提交几何编译任务';
      onGenerateRef.current();
      timer = window.setTimeout(() => {
        if (root.isConnected) { root.dataset.state = 'idle'; live.textContent = ''; }
      }, rm ? 900 : 1900);
    };
    const onMotion = (event: MediaQueryListEvent) => { rm = event.matches; };
    root.addEventListener('pointermove', onMove);
    root.addEventListener('pointerleave', onLeave);
    btn.addEventListener('click', onClick);
    motionQuery.addEventListener('change', onMotion);
    return () => {
      window.clearTimeout(timer);
      root.removeEventListener('pointermove', onMove);
      root.removeEventListener('pointerleave', onLeave);
      btn.removeEventListener('click', onClick);
      motionQuery.removeEventListener('change', onMotion);
    };
  }, []);

  return (
    <div ref={rootRef} className="ux u002" data-state={generating ? 'go' : 'idle'}>
      <span className="u002-glow" aria-hidden="true" />
      <div className="u002-mag">
        <button className="u002-btn" type="button" disabled={disabled || generating} aria-label={generating ? '正在生成模型' : '生成三维模型'}>
          <span className="u002-fill" aria-hidden="true" />
          <span className="u002-txt">
            <span>{generating ? '正在构筑几何' : '让想象成形'}</span>
            <span aria-hidden="true">{generating ? '编译 B-REP 中' : '进入三维世界'}</span>
          </span>
          <span className="u002-orb" aria-hidden="true">
            {generating ? <span className="u002-spinner" /> : (
              <>
                <svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
                <svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
              </>
            )}
          </span>
        </button>
      </div>
      <span className="u002-live" aria-live="polite" />
    </div>
  );
}
