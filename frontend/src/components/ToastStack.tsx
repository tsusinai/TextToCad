/* Lucian UX/UI Prompt #070 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#070 */
import { useEffect, useRef } from 'react';
import type { ToastItem } from '../types';
import './lucian-070.css';

interface Props {
  items: ToastItem[];
  onDismiss: (id: number) => void;
  onAction?: (item: ToastItem) => void;
}

const ICON = {
  ok: '<svg viewBox="0 0 18 18"><path d="M4 9.4l3.2 3.2L14 5.6"/></svg>',
  err: '<svg viewBox="0 0 18 18"><path d="M9 5v5M9 13h.01"/></svg>',
  info: '<svg viewBox="0 0 18 18"><path d="M3.5 4.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>',
  wait: '<i></i>',
};
const colors = { ok: 'var(--ux-mint)', err: 'var(--ux-danger)', info: 'var(--ux-accent)', wait: 'var(--ux-warn)' };
const DUR = 4500;

interface InternalToast {
  el: HTMLElement;
  item: ToastItem;
  left: number;
}

export default function ToastStack({ items, onDismiss, onAction }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const syncRef = useRef<(next: ToastItem[]) => void>(() => {});
  const dismissRef = useRef(onDismiss);
  const actionRef = useRef(onAction);
  dismissRef.current = onDismiss;
  actionRef.current = onAction;

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const zone = root.querySelector<HTMLElement>('.u070-zone')!;
    const live = root.querySelector<HTMLElement>('.u070-live')!;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let list: InternalToast[] = [];
    let open = false;
    let raf = 0;
    const timers = new Set<number>();

    const layout = () => {
      let accumulated = 0;
      list.forEach((toast, index) => {
        const el = toast.el;
        el.classList.toggle('back', !open && index > 0);
        if (open) {
          el.style.setProperty('--y', `${-accumulated}px`);
          el.style.setProperty('--s', '1');
          el.style.setProperty('--o', '1');
          accumulated += el.offsetHeight + 8;
        } else {
          el.style.setProperty('--y', `${-(index * 14)}px`);
          el.style.setProperty('--s', (1 - index * .06).toFixed(2));
          el.style.setProperty('--o', index > 2 ? '0' : '1');
        }
        el.style.zIndex = String(50 - index);
        el.inert = !open && index > 0;
      });
    };

    const remove = (toast: InternalToast, direction = 0, notify = true) => {
      const index = list.indexOf(toast);
      if (index < 0) return;
      list.splice(index, 1);
      toast.el.classList.add('leave');
      if (direction) {
        toast.el.style.setProperty('--dir', String(direction));
        toast.el.classList.add('side');
      }
      const timer = window.setTimeout(() => { toast.el.remove(); timers.delete(timer); }, 450);
      timers.add(timer);
      if (notify) dismissRef.current(toast.item.id);
      layout();
    };

    const push = (item: ToastItem) => {
      const el = document.createElement('div');
      el.className = 'u070-t enter';
      el.style.setProperty('--c', colors[item.kind]);
      el.setAttribute('role', item.kind === 'err' ? 'alert' : 'status');
      el.innerHTML = `<span class="u070-ic" aria-hidden="true">${ICON[item.kind]}</span><span class="u070-tx"><b></b><small></small></span>${item.action ? '<button class="u070-act" type="button"></button>' : ''}<button class="u070-x" type="button" aria-label="关闭通知"><svg viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7"/></svg></button><span class="u070-bar" aria-hidden="true"></span>`;
      el.querySelector('b')!.textContent = item.title;
      el.querySelector('small')!.textContent = item.detail;
      if (item.action) el.querySelector('.u070-act')!.textContent = item.action;
      const toast: InternalToast = { el, item, left: item.kind === 'wait' ? Infinity : DUR };
      zone.appendChild(el);
      list.unshift(toast);
      void el.offsetWidth;
      el.classList.remove('enter');
      layout();
      live.textContent = item.title;
      el.querySelector('.u070-x')!.addEventListener('click', () => remove(toast));
      el.querySelector('.u070-act')?.addEventListener('click', () => { actionRef.current?.(item); remove(toast); });

      let startX = 0;
      let deltaX = 0;
      let down = false;
      el.addEventListener('pointerdown', (event) => {
        if ((event.target as HTMLElement).closest('button')) return;
        down = true;
        startX = event.clientX;
        deltaX = 0;
        el.setPointerCapture(event.pointerId);
        el.classList.add('drag');
      });
      el.addEventListener('pointermove', (event) => {
        if (!down) return;
        deltaX = event.clientX - startX;
        el.style.setProperty('--dx', `${deltaX}px`);
        el.style.setProperty('--o', String(Math.max(.2, 1 - Math.abs(deltaX) / 260)));
      });
      const end = () => {
        if (!down) return;
        down = false;
        el.classList.remove('drag');
        if (Math.abs(deltaX) > 90) remove(toast, deltaX > 0 ? 1 : -1);
        else { el.style.setProperty('--dx', '0px'); layout(); }
      };
      el.addEventListener('pointerup', end);
      el.addEventListener('pointercancel', end);
      if (list.length > 4) remove(list[list.length - 1], 0, true);
    };

    syncRef.current = (next) => {
      const ids = new Set(next.map((item) => item.id));
      list.slice().forEach((toast) => { if (!ids.has(toast.item.id)) remove(toast, 0, false); });
      next.forEach((item) => { if (!list.some((toast) => toast.item.id === item.id)) push(item); });
      layout();
    };

    let last = performance.now();
    const loop = (now: number) => {
      const dt = now - last;
      last = now;
      if (!open && !document.hidden) list.slice().forEach((toast, index) => {
        if (index > 0 || toast.left === Infinity) return;
        toast.left -= dt;
        toast.el.style.setProperty('--left', Math.max(0, toast.left / DUR).toFixed(3));
        if (toast.left <= 0) remove(toast);
      });
      raf = requestAnimationFrame(loop);
    };
    const setOpen = (value: boolean) => { if (open === value) return; open = value; layout(); };
    const pointerEnter = (event: PointerEvent) => { if (event.pointerType === 'mouse') setOpen(true); };
    const pointerLeave = (event: PointerEvent) => { if (event.pointerType === 'mouse' && !zone.contains(document.activeElement)) setOpen(false); };
    const focusIn = () => setOpen(true);
    const focusOut = (event: FocusEvent) => { if (!zone.contains(event.relatedTarget as Node)) setOpen(false); };
    const click = (event: MouseEvent) => { if (!(event.target as HTMLElement).closest('button') && list.length > 1) setOpen(!open); };
    zone.addEventListener('pointerenter', pointerEnter);
    zone.addEventListener('pointerleave', pointerLeave);
    zone.addEventListener('focusin', focusIn);
    zone.addEventListener('focusout', focusOut);
    zone.addEventListener('click', click);
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      timers.forEach((timer) => window.clearTimeout(timer));
      zone.removeEventListener('pointerenter', pointerEnter);
      zone.removeEventListener('pointerleave', pointerLeave);
      zone.removeEventListener('focusin', focusIn);
      zone.removeEventListener('focusout', focusOut);
      zone.removeEventListener('click', click);
      list.forEach((toast) => toast.el.remove());
      list = [];
      syncRef.current = () => {};
    };
  }, []);

  useEffect(() => { syncRef.current(items); }, [items]);

  return (
    <div ref={rootRef} className="ux u070">
      <div className="u070-zone" role="region" aria-label="通知" tabIndex={-1}>
        <div className="u070-live" aria-live="polite" />
      </div>
    </div>
  );
}
