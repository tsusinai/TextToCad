/* Lucian UX/UI Prompt #039 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#039 */
import { useEffect, useRef } from 'react';
import type { HistoryItem } from '../types';
import './lucian-039.css';

interface Props {
  items: HistoryItem[];
  activeId: string;
  onSelect: (item: HistoryItem) => void;
}

const filters = [
  { label: '全部', match: () => true },
  { label: 'FDM', match: (item: HistoryItem) => item.process === 'fdm' || item.process === 'sla' },
  { label: 'CNC', match: (item: HistoryItem) => item.process === 'cnc' || item.process === 'injection' },
] satisfies Array<{ label: string; match: (item: HistoryItem) => boolean }>;

const gradients = [
  'linear-gradient(140deg,#d7ff43,#587d48)',
  'linear-gradient(140deg,#dde3d7,#617065)',
  'linear-gradient(140deg,#9dd9b4,#273c30)',
  'linear-gradient(140deg,#e6e0cc,#8c896f)',
];

export default function VersionTabs({ items, activeId, onSelect }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const refreshRef = useRef<() => void>(() => {});
  const itemsRef = useRef(items);
  const activeIdRef = useRef(activeId);
  const onSelectRef = useRef(onSelect);
  itemsRef.current = items;
  activeIdRef.current = activeId;
  onSelectRef.current = onSelect;

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const tabs = Array.from(root.querySelectorAll<HTMLButtonElement>('.u039-tab'));
    const pill = root.querySelector<HTMLElement>('.u039-pill')!;
    const panel = root.querySelector<HTMLElement>('.u039-panel')!;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let current = 0;
    let list: HTMLUListElement | null = null;
    let removeTimer = 0;

    const movePill = (animate: boolean) => {
      const tab = tabs[current];
      if (!animate) pill.style.transition = 'none';
      pill.style.setProperty('--x', `${tab.offsetLeft}px`);
      pill.style.setProperty('--w', `${tab.offsetWidth}px`);
      if (!animate) { void pill.offsetWidth; pill.style.transition = ''; }
    };

    const make = (filterIndex: number) => {
      const ul = document.createElement('ul');
      ul.className = 'u039-list';
      const filtered = itemsRef.current.filter(filters[filterIndex].match).slice(0, 4);
      if (!filtered.length) {
        const empty = document.createElement('li');
        empty.className = 'u039-empty';
        empty.innerHTML = '<span>∅</span><b>此处尚无模型</b><small>切换分类或生成一个新版本</small>';
        ul.appendChild(empty);
        return ul;
      }
      filtered.forEach((item, index) => {
        const row = document.createElement('li');
        row.className = 'u039-row';
        row.style.transitionDelay = `${index * 45}ms`;
        row.tabIndex = 0;
        row.setAttribute('role', 'button');
        row.setAttribute('aria-label', `打开版本 ${item.title}`);
        if (item.id === activeIdRef.current) row.dataset.active = 'true';
        const art = document.createElement('span');
        art.className = 'u039-art';
        art.style.setProperty('--g', gradients[index % gradients.length]);
        art.setAttribute('aria-hidden', 'true');
        const copy = document.createElement('span');
        copy.className = 'u039-copy';
        const title = document.createElement('b');
        title.textContent = item.title;
        if (item.id === activeIdRef.current) {
          const badge = document.createElement('span');
          badge.className = 'u039-badge';
          badge.textContent = 'CURRENT';
          title.appendChild(badge);
        }
        const subtitle = document.createElement('small');
        subtitle.textContent = `${item.process.toUpperCase()} · ${item.material.toUpperCase()}`;
        copy.append(title, subtitle);
        const version = document.createElement('em');
        version.textContent = item.id.startsWith('demo') ? `V.0${index + 1}` : 'NEW';
        row.append(art, copy, version);
        const select = () => onSelectRef.current(item);
        row.addEventListener('click', select);
        row.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
        });
        ul.appendChild(row);
      });
      return ul;
    };

    const select = (index: number, focus = false, force = false) => {
      if (index === current && list && !force) return;
      const direction = index >= current ? 1 : -1;
      current = index;
      tabs.forEach((tab, tabIndex) => {
        tab.setAttribute('aria-selected', String(tabIndex === index));
        tab.tabIndex = tabIndex === index ? 0 : -1;
      });
      if (focus) tabs[index].focus();
      movePill(true);
      const next = make(index);
      const old = list;
      list = next;
      if (!old || motionQuery.matches) {
        old?.remove();
        panel.appendChild(next);
        return;
      }
      Array.from(next.children).forEach((child) => {
        (child as HTMLElement).style.transform = `translateX(${direction * 70}%)`;
        (child as HTMLElement).style.opacity = '0';
      });
      panel.appendChild(next);
      void next.offsetWidth;
      Array.from(next.children).forEach((child) => {
        (child as HTMLElement).style.transform = '';
        (child as HTMLElement).style.opacity = '';
      });
      if (old) Array.from(old.children).forEach((child) => {
        (child as HTMLElement).style.transform = `translateX(${-direction * 60}%)`;
        (child as HTMLElement).style.opacity = '0';
      });
      window.clearTimeout(removeTimer);
      removeTimer = window.setTimeout(() => old?.remove(), 700);
    };

    refreshRef.current = () => select(current, false, true);
    const listeners = tabs.map((tab, index) => {
      const click = () => select(index);
      const keydown = (event: KeyboardEvent) => {
        const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (direction) { event.preventDefault(); select((index + direction + tabs.length) % tabs.length, true); }
      };
      tab.addEventListener('click', click);
      tab.addEventListener('keydown', keydown);
      return () => { tab.removeEventListener('click', click); tab.removeEventListener('keydown', keydown); };
    });
    const uid = 'u039-versions';
    panel.id = uid;
    tabs.forEach((tab) => tab.setAttribute('aria-controls', uid));
    select(0, false, true);
    const observer = new ResizeObserver(() => movePill(false));
    observer.observe(root.querySelector('.u039-tabs')!);

    return () => {
      window.clearTimeout(removeTimer);
      listeners.forEach((cleanup) => cleanup());
      observer.disconnect();
      panel.replaceChildren();
    };
  }, []);

  useEffect(() => { refreshRef.current(); }, [items, activeId]);

  return (
    <div ref={rootRef} className="ux u039">
      <div className="u039-tabs" role="tablist" aria-label="模型版本分类">
        <span className="u039-pill" aria-hidden="true" />
        {filters.map((filter, index) => (
          <button key={filter.label} className="u039-tab" type="button" role="tab" aria-selected={index === 0}>{filter.label}</button>
        ))}
      </div>
      <div className="u039-panel" role="tabpanel" aria-label="模型版本列表" />
    </div>
  );
}
