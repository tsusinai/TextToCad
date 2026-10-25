import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, ArrowDownToLine, ArrowUpRight, Box, Braces, Check, ChevronDown,
  CircleHelp, Command, Cuboid, Download, Expand, FileBox, FileText, Gauge, Grid3X3,
  Layers3, Maximize2, Moon, MousePointer2, Orbit, Pause, Play, RotateCcw, Ruler,
  ScanLine, Scissors, Settings2, ShieldCheck, Sparkles, Sun, X, Zap, ZoomIn, ZoomOut,
} from 'lucide-react';
import GenerativeBackground from './components/GenerativeBackground';
import CadViewport from './components/CadViewport';
import type { CadViewportHandle } from './components/CadViewport';
import MagneticGenerateButton from './components/MagneticGenerateButton';
import VersionTabs from './components/VersionTabs';
import ToastStack from './components/ToastStack';
import DrawingModal from './components/DrawingModal';
import MeasureHud from './components/MeasureHud';
import SectionToolbar from './components/SectionToolbar';
import { checkHealth, downloadModel, generateModel } from './lib/api';
import type {
  GenerateSettings, GenerationProgress, HistoryItem, MaterialType,
  ModelResult, ProcessType, ToastItem, ToastKind,
} from './types';

const DEFAULT_PROMPT = '一个模块化桌面收纳器，宽120mm、深80mm，带3个分区、2mm圆角和隐藏式理线槽。';
const DEFAULT_SETTINGS: GenerateSettings = {
  units: 'mm', process: 'fdm', mode: 'standard', material: 'pla',
  include_steps: true, generation_strategy: 'ir',
};
const DEMO_HISTORY: HistoryItem[] = [
  { id: 'demo-01', title: '模块收纳器', prompt: DEFAULT_PROMPT, createdAt: Date.now(), process: 'fdm', material: 'pla' },
  { id: 'demo-02', title: '蜂窝散热外壳', prompt: '一个160×100mm的电子设备外壳，带蜂窝散热孔、3mm壁厚和圆角。', createdAt: Date.now() - 1000, process: 'fdm', material: 'petg' },
  { id: 'demo-03', title: '铝合金支架', prompt: '一个CNC铝合金L形支架，宽80mm，带两个M6安装孔和加强筋。', createdAt: Date.now() - 2000, process: 'cnc', material: 'aluminum' },
  { id: 'demo-04', title: '注塑卡扣', prompt: '一个注塑卡扣结构，带1.5度脱模斜度、均匀壁厚和弹性卡臂。', createdAt: Date.now() - 3000, process: 'injection', material: 'abs' },
];
const PROMPT_PRESETS = [
  { label: '桌面收纳', prompt: DEFAULT_PROMPT },
  { label: '散热外壳', prompt: DEMO_HISTORY[1].prompt },
  { label: '机械支架', prompt: DEMO_HISTORY[2].prompt },
];
const STAGE_LABELS: Record<string, string> = {
  queued: '等待几何内核', parsing: '解析自然语言', planning: '规划语义特征',
  compile: '编译参数化 IR', geometry: '求解 B-Rep 几何', analysis: '执行可制造性分析',
  export: '封装工业格式', complete: '几何编译完成',
};
const GENERATION_STEPS = ['语义解析', 'IR 规划', 'B-Rep 求解', '制造校验'];

function readDraft() {
  try {
    const raw = localStorage.getItem('forma-draft');
    return raw ? JSON.parse(raw) as { prompt?: string; settings?: GenerateSettings } : {};
  } catch { return {}; }
}

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}

function App() {
  const draft = useRef(readDraft()).current;
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const requested = new URLSearchParams(window.location.search).get('theme');
    if (requested === 'light' || requested === 'dark') return requested;
    return localStorage.getItem('forma-theme') === 'light' ? 'light' : 'dark';
  });
  const [prompt, setPrompt] = useState(draft.prompt || DEFAULT_PROMPT);
  const [settings, setSettings] = useState<GenerateSettings>({ ...DEFAULT_SETTINGS, ...draft.settings });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [backend, setBackend] = useState<'checking' | 'online' | 'offline'>('checking');
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('等待创作指令');
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<ModelResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>(DEMO_HISTORY);
  const [activeId, setActiveId] = useState('demo-01');
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [wireframe, setWireframe] = useState(false);
  const [xray, setXray] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [autoRotate, setAutoRotate] = useState(false);
  const [view, setView] = useState<'iso' | 'top' | 'front' | 'right'>('iso');
  const [modelLoading, setModelLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [sectionOpen, setSectionOpen] = useState(false);
  const [sectionAxis, setSectionAxis] = useState<'none' | 'x' | 'y' | 'z'>('none');
  const [sectionDepth, setSectionDepth] = useState(0);
  const [sectionFlipped, setSectionFlipped] = useState(false);
  const [measureOpen, setMeasureOpen] = useState(false);
  const [drawingOpen, setDrawingOpen] = useState(false);
  const viewportRef = useRef<CadViewportHandle>(null);
  const stageRef = useRef<HTMLElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const generationRef = useRef<AbortController | null>(null);
  const generationSeq = useRef(0);
  const toastSeq = useRef(0);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);
  const notify = useCallback((kind: ToastKind, title: string, detail: string, action?: string) => {
    const id = ++toastSeq.current;
    setToasts((current) => [...current, { id, kind, title, detail, action, createdAt: Date.now() }].slice(-4));
    return id;
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0b0d0c' : '#e5e7de');
    localStorage.setItem('forma-theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('forma-draft', JSON.stringify({ prompt, settings }));
  }, [prompt, settings]);

  const verifyHealth = useCallback(async (announce = false, silent = false) => {
    if (!silent) setBackend('checking');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3000);
    try {
      await checkHealth(controller.signal);
      setBackend('online');
      if (announce) notify('ok', '几何引擎已连接', 'OCCT 内核就绪，可开始参数化编译');
      return true;
    } catch {
      setBackend('offline');
      if (announce) notify('info', '当前为交互演示模式', '启动 FastAPI 后端后即可生成真实 CAD');
      return false;
    } finally { window.clearTimeout(timeout); }
  }, [notify]);

  useEffect(() => {
    void verifyHealth();
    const poll = window.setInterval(() => { void verifyHealth(false, true); }, 15000);
    const onFocus = () => { void verifyHealth(false, true); };
    window.addEventListener('focus', onFocus);
    return () => { window.clearInterval(poll); window.removeEventListener('focus', onFocus); };
  }, [verifyHealth]);

  useEffect(() => {
    if (!generating) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 100);
    return () => window.clearInterval(timer);
  }, [generating]);

  const onGenerationProgress = useCallback((update: GenerationProgress) => {
    const name = update.stage || 'queued';
    const eventCount = update.events?.length || 0;
    const base = name === 'queued' ? 6 : Math.min(92, 14 + eventCount * 9);
    setProgress((current) => Math.max(current, base));
    setStage(STAGE_LABELS[name] || update.current_step || name.replaceAll('_', ' ').toUpperCase());
  }, []);

  const handleGenerate = useCallback(async () => {
    const cleanPrompt = prompt.trim();
    if (cleanPrompt.length < 3) {
      notify('err', '再多描述一点', '至少输入 3 个字符，包含形状或尺寸会更准确');
      promptRef.current?.focus();
      return;
    }
    generationRef.current?.abort();
    const controller = new AbortController();
    generationRef.current = controller;
    const sequence = ++generationSeq.current;
    const online = backend === 'online' || await verifyHealth();
    if (controller.signal.aborted || sequence !== generationSeq.current) return;
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, settings.mode === 'agent' ? 120000 : 90000);
    setGenerating(true);
    setResult(null);
    setProgress(4);
    setElapsed(0);
    setStage('建立语义 CAD 会话');
    const waitingToast = notify('wait', online ? '正在编译真实几何' : '正在构建演示样品', online ? 'Semantic IR → OCCT B-Rep' : '后端未连接 · 不会生成工业文件');

    try {
      if (online) {
        const generated = await generateModel(cleanPrompt, settings, controller.signal, onGenerationProgress);
        if (sequence !== generationSeq.current) return;
        setResult(generated);
        setActiveId(generated.model_id);
        setHistory((current) => [{
          id: generated.model_id,
          title: generated.title || '未命名参数化模型',
          prompt: cleanPrompt,
          createdAt: Date.now(),
          process: settings.process,
          material: settings.material,
          result: generated,
        }, ...current.filter((item) => item.id !== generated.model_id)].slice(0, 12));
        setProgress(100);
        setStage('几何编译完成');
        dismissToast(waitingToast);
        notify('ok', '模型已完成编译', `${generated.title} · STEP / STL / 3MF 可导出`);
      } else {
        for (let index = 0; index < GENERATION_STEPS.length; index += 1) {
          await delay(650, controller.signal);
          if (sequence !== generationSeq.current) return;
          setStage(GENERATION_STEPS[index]);
          setProgress((index + 1) * 23);
        }
        await delay(450, controller.signal);
        if (sequence !== generationSeq.current) return;
        const id = `demo-${Date.now()}`;
        setActiveId(id);
        setHistory((current) => [{ id, title: '本地演示样品', prompt: cleanPrompt, createdAt: Date.now(), process: settings.process, material: settings.material }, ...current].slice(0, 12));
        setProgress(100);
        setStage('交互演示完成 · 非工业文件');
        dismissToast(waitingToast);
        notify('ok', '演示样品已完成', '启动后端并重新生成，即可获得可制造 CAD');
      }
    } catch (error) {
      if (sequence !== generationSeq.current) return;
      dismissToast(waitingToast);
      if (error instanceof DOMException && error.name === 'AbortError') {
        setStage(timedOut ? '生成超时，可重试' : '已取消生成');
        notify('info', timedOut ? '几何编译超时' : '已停止生成', timedOut ? '可切换标准模式或稍后重试' : '当前样品已保留');
      } else {
        console.error('Generation failed', error);
        setStage('几何编译未完成');
        notify('err', '模型生成失败', error instanceof Error ? error.message : '请检查后端连接后重试', '重试');
      }
    } finally {
      window.clearTimeout(timeout);
      if (sequence === generationSeq.current) setGenerating(false);
    }
  }, [backend, dismissToast, notify, onGenerationProgress, prompt, settings, verifyHealth]);

  const cancelGeneration = useCallback(() => {
    generationRef.current?.abort();
    generationSeq.current += 1;
    setGenerating(false);
    setStage('已取消生成');
    setToasts((current) => current.filter((toast) => toast.kind !== 'wait'));
    notify('info', '已停止当前任务', '参数与提示词已保留');
  }, [notify]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        if (!generating) void handleGenerate();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        promptRef.current?.focus();
      }
      if (event.key === 'Escape') { setHelpOpen(false); setSettingsOpen(false); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [generating, handleGenerate]);

  useEffect(() => () => generationRef.current?.abort(), []);

  const selectHistory = (item: HistoryItem) => {
    if (generating) cancelGeneration();
    setPrompt(item.prompt);
    setSettings((current) => ({ ...current, process: item.process, material: item.material }));
    setResult(item.result || null);
    setActiveId(item.id);
    setStage(item.result ? '历史几何已载入' : '模板已载入 · 等待真实编译');
    setProgress(item.result ? 100 : 0);
    viewportRef.current?.reset();
    notify('info', item.result ? '版本已恢复' : '创作模板已载入', item.result ? item.title : '点击生成以编译此参数组合');
  };

  const changeView = (next: 'iso' | 'top' | 'front' | 'right') => {
    setView(next);
    viewportRef.current?.setView(next);
  };

  const exportModel = async (format: 'step' | 'stl' | '3mf' | 'glb') => {
    if (!result) {
      notify('info', '工业导出需要真实几何', '连接后端并生成模型后，可导出 STEP / STL / 3MF');
      return;
    }
    const pending = notify('wait', `正在准备 ${format.toUpperCase()}`, '正在从几何引擎读取工业文件');
    try {
      await downloadModel(result.model_id, format);
      dismissToast(pending);
      notify('ok', '导出已开始', `${format.toUpperCase()} 文件已交给浏览器下载`);
    } catch (error) {
      dismissToast(pending);
      notify('err', '导出失败', error instanceof Error ? error.message : '请稍后重试');
    }
  };

  const capture = () => {
    const image = viewportRef.current?.capture();
    if (!image) return;
    const anchor = document.createElement('a');
    anchor.href = image;
    anchor.download = `FORMA-${Date.now()}.png`;
    anchor.click();
    notify('ok', '视口快照已保存', 'PNG 图像已交给浏览器下载');
  };

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) await stageRef.current?.requestFullscreen();
      else await document.exitFullscreen();
    } catch { notify('err', '无法进入全屏', '当前浏览器限制了全屏显示'); }
  };
  useEffect(() => {
    const listener = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', listener);
    return () => document.removeEventListener('fullscreenchange', listener);
  }, []);

  const parameters = result?.parameters;
  const modelTitle = result?.title || (activeId === 'demo-01' ? '模块化桌面收纳器' : '程序化概念样品');
  const dfmScore = result?.analysis && typeof result.analysis === 'object'
    ? Number((result.analysis as Record<string, unknown>).score || 96) : 96;
  const completedSteps = generating ? Math.min(3, Math.floor(progress / 25)) : progress === 100 ? 4 : 1;

  return (
    <div className="app-shell min-h-screen">
      <GenerativeBackground generating={generating} theme={theme} />
      <div className="grain" aria-hidden="true" />

      <header className="site-header">
        <a className="brand" href="#studio" aria-label="FORMA 首页">
          <span className="brand-mark" aria-hidden="true"><span>F</span><i /></span>
          <span className="brand-word">FORMA<sup>®</sup></span>
          <span className="brand-edition">TEXT—TO—CAD<br />STUDIO / 01</span>
        </a>
        <nav className="main-nav" aria-label="主导航">
          <a href="#studio" className="active"><span>01</span> 创作台</a>
          <a href="#process"><span>02</span> 制造逻辑</a>
          <button type="button" onClick={() => setHelpOpen(true)}><span>03</span> 操作指南</button>
        </nav>
        <div className="header-actions">
          <button className={`engine-status ${backend}`} type="button" onClick={() => void verifyHealth(true)} aria-label="检查几何引擎连接">
            <i /> <span>{backend === 'online' ? 'ENGINE ONLINE' : backend === 'checking' ? 'CONNECTING' : 'DEMO MODE'}</span>
          </button>
          <button className="icon-button theme-toggle" type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={theme === 'dark' ? '切换浅色主题' : '切换深色主题'}>
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <main>
        <section id="studio" className="hero-section">
          <div className="hero-heading rise-in">
            <div>
              <div className="eyebrow"><span>GENERATIVE MANUFACTURING SYSTEM</span><i /><span>V 0.2</span></div>
              <h1><span>语言，</span><span className="outline-word">即刻</span><span>成形<em>。</em></span></h1>
            </div>
            <div className="hero-aside">
              <p>不是另一场图像幻觉。<br />是尺寸精确、结构真实、<strong>可以被制造</strong>的几何。</p>
              <div className="hero-stats">
                <div><b>0.2<small>mm</small></b><span>默认公差</span></div>
                <div><b>04<small>fmt</small></b><span>工业输出</span></div>
              </div>
            </div>
          </div>

          <div className="workspace-grid">
            <section className="composer-panel rise-in delay-1" aria-labelledby="composer-title">
              <div className="panel-heading">
                <div><span className="section-index">01 / INPUT</span><h2 id="composer-title">描述你的造物</h2></div>
                <Sparkles size={20} strokeWidth={1.5} />
              </div>
              <div className="prompt-field">
                <textarea
                  ref={promptRef}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  maxLength={4000}
                  spellCheck={false}
                  aria-label="模型描述"
                  placeholder="例如：一个 120mm 宽的桌面收纳器，带三个分区……"
                />
                <div className="prompt-meta"><span>NATURAL LANGUAGE → SEMANTIC IR</span><span>{prompt.length} / 4000</span></div>
              </div>
              <div className="preset-row" aria-label="提示词预设">
                {PROMPT_PRESETS.map((preset) => <button key={preset.label} type="button" onClick={() => setPrompt(preset.prompt)}>{preset.label}<ArrowUpRight size={12} /></button>)}
              </div>

              <div className={`settings-block ${settingsOpen ? 'open' : ''}`}>
                <button className="settings-trigger" type="button" onClick={() => setSettingsOpen(!settingsOpen)} aria-expanded={settingsOpen}>
                  <span><Settings2 size={15} /> 制造参数</span>
                  <span className="settings-summary">{settings.process.toUpperCase()} · {settings.material.toUpperCase()} <ChevronDown size={15} /></span>
                </button>
                <div className="settings-content">
                  <div className="settings-inner">
                    <label>制造工艺
                      <select value={settings.process} onChange={(event) => setSettings({ ...settings, process: event.target.value as ProcessType })}>
                        <option value="fdm">FDM 熔融沉积</option><option value="sla">SLA 光固化</option>
                        <option value="cnc">CNC 数控加工</option><option value="injection">注塑成型</option>
                      </select>
                    </label>
                    <label>材料
                      <select value={settings.material} onChange={(event) => setSettings({ ...settings, material: event.target.value as MaterialType })}>
                        <option value="pla">PLA</option><option value="petg">PETG</option><option value="abs">ABS</option>
                        <option value="resin">Resin</option><option value="aluminum">Aluminum 6061</option>
                      </select>
                    </label>
                    <div className="mode-control" role="group" aria-label="生成模式">
                      {(['standard', 'advanced', 'agent'] as const).map((mode) => <button key={mode} type="button" className={settings.mode === mode ? 'selected' : ''} onClick={() => setSettings({ ...settings, mode })}>{mode === 'standard' ? '标准' : mode === 'advanced' ? '精细' : 'Agent'}</button>)}
                    </div>
                  </div>
                </div>
              </div>

              {(generating || progress > 0) && (
                <div className="generation-progress" aria-live="polite">
                  <div><span>{stage}</span><b>{String(progress).padStart(2, '0')}%</b></div>
                  <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
                  <div className="progress-foot"><span>{(elapsed / 1000).toFixed(1)} SEC</span><span>{backend === 'online' ? 'OCCT / LIVE' : 'LOCAL / DEMO'}</span></div>
                </div>
              )}

              <div className="composer-generate">
                <MagneticGenerateButton generating={generating} onGenerate={() => void handleGenerate()} />
              </div>
              <div className="semantic-preview" aria-label="语义 CAD 结构摘要">
                <div className="semantic-preview-head"><span>LIVE SEMANTIC OUTLINE</span><Braces size={12} /></div>
                <div className="semantic-node"><span>01</span><div><b>ENTITY</b><small>{result?.parameters?.kind || 'parametric_organizer'}</small></div><i /></div>
                <div className="semantic-node"><span>02</span><div><b>FEATURES</b><small>{parameters?.compartments ?? 3} compartments · cable channel</small></div><i /></div>
                <div className="semantic-node"><span>03</span><div><b>CONSTRAINT</b><small>R {parameters?.chamfer ?? 2}.0 mm · wall {parameters?.wall ?? 2.4} mm</small></div><i /></div>
                <div className="semantic-schema"><span>IR::V0.2</span><span>VALIDATED SCHEMA</span></div>
              </div>
              <div className="composer-footer">
                <span><Command size={12} /> CTRL + ENTER</span>
                {generating ? <button type="button" onClick={cancelGeneration}><X size={12} /> 取消任务</button> : <span>DETERMINISTIC CAD</span>}
              </div>
            </section>

            <section ref={stageRef} className={`viewport-stage rise-in delay-2 ${generating ? 'is-generating' : ''}`} aria-labelledby="viewport-title">
              <div className="viewport-topbar">
                <div className="viewport-title"><span className="section-index">02 / VIEWPORT</span><i /><span>{modelLoading ? 'LOADING MESH' : result ? 'B-REP / LIVE' : 'PROCEDURAL / DEMO'}</span></div>
                <div className="view-switch" role="group" aria-label="视角">
                  {(['iso', 'top', 'front'] as const).map((item) => <button key={item} className={view === item ? 'active' : ''} type="button" onClick={() => changeView(item)}>{item.toUpperCase()}</button>)}
                </div>
                <button className="icon-button" type="button" onClick={() => void toggleFullscreen()} aria-label={fullscreen ? '退出全屏' : '全屏视口'}><Maximize2 size={16} /></button>
              </div>

              <div className="viewport-tools" aria-label="模型显示工具">
                <button type="button" className={autoRotate ? 'active' : ''} onClick={() => setAutoRotate(!autoRotate)} aria-label={autoRotate ? '暂停自动旋转' : '自动旋转'} data-tooltip="自动旋转">{autoRotate ? <Pause size={17} /> : <Orbit size={17} />}</button>
                <button type="button" className={showGrid ? 'active' : ''} onClick={() => setShowGrid(!showGrid)} aria-label="切换网格" data-tooltip="基准网格"><Grid3X3 size={17} /></button>
                <button type="button" className={wireframe ? 'active' : ''} onClick={() => { setWireframe(!wireframe); setXray(false); }} aria-label="切换线框" data-tooltip="线框模式"><Braces size={17} /></button>
                <button type="button" className={xray ? 'active' : ''} onClick={() => { setXray(!xray); setWireframe(false); }} aria-label="切换透视" data-tooltip="X-Ray"><ScanLine size={17} /></button>
                <button type="button" className={sectionOpen ? 'active' : ''} onClick={() => { setSectionOpen(!sectionOpen); if (sectionOpen) setSectionAxis('none'); }} aria-label="3D 剖切审查" data-tooltip="剖切审查"><Scissors size={17} /></button>
                <button type="button" className={measureOpen ? 'active' : ''} onClick={() => setMeasureOpen(!measureOpen)} aria-label="CAD 尺寸量测" data-tooltip="尺寸量测"><Ruler size={17} /></button>
                <span />
                <button type="button" onClick={() => viewportRef.current?.zoom(1)} aria-label="放大" data-tooltip="放大"><ZoomIn size={17} /></button>
                <button type="button" onClick={() => viewportRef.current?.zoom(-1)} aria-label="缩小" data-tooltip="缩小"><ZoomOut size={17} /></button>
                <button type="button" onClick={() => changeView('iso')} aria-label="重置视角" data-tooltip="重置视角"><RotateCcw size={17} /></button>
              </div>

              <SectionToolbar
                isOpen={sectionOpen}
                axis={sectionAxis}
                depth={sectionDepth}
                flipped={sectionFlipped}
                onAxisChange={setSectionAxis}
                onDepthChange={setSectionDepth}
                onFlipToggle={() => setSectionFlipped(!sectionFlipped)}
              />

              <MeasureHud
                isOpen={measureOpen}
                onClose={() => setMeasureOpen(false)}
                modelId={result?.model_id ?? null}
                result={result}
              />

              <div className="axis-gizmo" aria-hidden="true"><span className="axis-y">Y</span><span className="axis-x">X</span><span className="axis-z">Z</span><i /></div>
              <div className="model-coordinate coordinate-a" aria-hidden="true">X — 120.000</div>
              <div className="model-coordinate coordinate-b" aria-hidden="true">Z — 042.000</div>
              <CadViewport
                ref={viewportRef}
                result={result}
                wireframe={wireframe}
                xray={xray}
                showGrid={showGrid}
                autoRotate={autoRotate}
                generating={generating}
                theme={theme}
                onLoadState={setModelLoading}
                sectionAxis={sectionAxis}
                sectionDepth={sectionDepth}
                sectionFlipped={sectionFlipped}
              />

              <div className="model-caption">
                <div className="model-name"><span>{result ? `ID ${result.model_id.slice(0, 8).toUpperCase()}` : 'CONCEPT / 001'}</span><h2 id="viewport-title">{modelTitle}</h2></div>
                <div className="dimension-list">
                  <div><span>WIDTH</span><b>{(parameters?.width ?? 120).toFixed(1)}<small> mm</small></b></div>
                  <div><span>DEPTH</span><b>{(parameters?.depth ?? 80).toFixed(1)}<small> mm</small></b></div>
                  <div><span>HEIGHT</span><b>{(parameters?.height ?? 42).toFixed(1)}<small> mm</small></b></div>
                </div>
                <div className="viewport-hint"><MousePointer2 size={13} /><span>拖拽旋转 · 滚轮缩放</span></div>
              </div>
            </section>

            <aside className="inspector-column rise-in delay-3" aria-label="模型版本与制造信息">
              <div className="version-heading"><div><span className="section-index">03 / ARCHIVE</span><h2>版本档案</h2></div><span>{String(history.length).padStart(2, '0')} OBJECTS</span></div>
              <VersionTabs items={history} activeId={activeId} onSelect={selectHistory} />

              <section className="manufacture-panel" aria-labelledby="manufacture-title">
                <div className="manufacture-top">
                  <div className="score-ring" style={{ '--score': `${Math.min(100, Math.max(0, dfmScore)) * 3.6}deg` } as React.CSSProperties}><span><b>{Number.isFinite(dfmScore) ? Math.round(dfmScore) : 96}</b><small>DFM</small></span></div>
                  <div><span className="section-index">MANUFACTURABILITY</span><h3 id="manufacture-title">为真实世界而生</h3><p><ShieldCheck size={13} /> {result ? '内核校验已完成' : '等待真实几何校验'}</p></div>
                </div>
                <div className="manufacture-specs">
                  <div><span>壁厚</span><b>{parameters?.wall ?? 2.4} mm</b></div><div><span>公差</span><b>{parameters?.tolerance ?? 0.2} mm</b></div><div><span>材料</span><b>{settings.material.toUpperCase()}</b></div>
                </div>
                <div className="export-heading"><span>工业文件输出</span><button type="button" onClick={capture} aria-label="保存视口快照"><Expand size={14} /> PNG</button></div>
                <div className="export-list">
                  {(['step', 'stl', '3mf', 'glb'] as const).map((format, index) => (
                    <button key={format} type="button" onClick={() => void exportModel(format)}>
                      <span className="file-icon">{index === 0 ? <Cuboid size={17} /> : index === 1 ? <Layers3 size={17} /> : index === 2 ? <Box size={17} /> : <FileBox size={17} />}</span>
                      <span><b>{format.toUpperCase()}</b><small>{format === 'step' ? '参数化交换' : format === 'stl' ? '网格打印' : format === '3mf' ? '制造数据' : '实时预览'}</small></span>
                      <ArrowDownToLine size={15} />
                    </button>
                  ))}
                  <button type="button" onClick={() => setDrawingOpen(true)} title="查看与导出 ISO 2D 标准矢量制图蓝图">
                    <span className="file-icon"><FileText size={17} /></span>
                    <span><b>BLUEPRINT</b><small>2D 矢量工程蓝图</small></span>
                    <ArrowDownToLine size={15} />
                  </button>
                </div>
              </section>
            </aside>
          </div>

          <div className="pipeline-rail" aria-label="生成流程">
            {GENERATION_STEPS.map((item, index) => <div key={item} className={index < completedSteps ? 'complete' : ''}><span>{index < completedSteps ? <Check size={12} /> : `0${index + 1}`}</span><b>{item}</b><i /></div>)}
            <span className="pipeline-tech">SEMANTIC CAD IR <Zap size={12} /> OCCT KERNEL</span>
          </div>
        </section>

        <div className="kinetic-strip" aria-hidden="true"><div><span>TEXT → IR → B-REP → REALITY</span><i>✳</i><span>FROM LANGUAGE TO MATTER</span><i>✳</i><span>TEXT → IR → B-REP → REALITY</span><i>✳</i><span>FROM LANGUAGE TO MATTER</span><i>✳</i></div></div>

        <section id="process" className="engineering-section">
          <div className="engineering-intro">
            <span className="section-index">04 / UNDER THE SURFACE</span>
            <h2>不止于<br /><span>看见。</span><br />更能制造。</h2>
            <p>大模型只负责理解与规划，真正的几何由确定性 CAD 内核完成。每一条边、每一个孔、每一处公差，都有迹可循。</p>
            <a href="#studio">开始一次造物 <ArrowUpRight size={18} /></a>
          </div>
          <div className="engineering-steps">
            <article><span>01</span><div><Braces size={23} /><h3>语义，而非脚本</h3><p>将自然语言转译为 Semantic CAD IR，特征、约束与尺寸被明确记录，而不是执行不可控的生成代码。</p></div><small>SEMANTIC IR / V0.2</small></article>
            <article><span>02</span><div><Cuboid size={23} /><h3>几何，而非像素</h3><p>CadQuery 与 OCCT 构建真实 B-Rep 实体，支持布尔运算、参数化重编译和标准工业格式。</p></div><small>DETERMINISTIC B-REP</small></article>
            <article><span>03</span><div><Gauge size={23} /><h3>验证，而非猜测</h3><p>自动检查壁厚、间隙、脱模方向与制造约束，让设计在离开屏幕之前就接受真实世界的审视。</p></div><small>DFM / MULTI-GATE</small></article>
          </div>
        </section>
      </main>

      <footer className="site-footer"><div className="brand-word">FORMA<sup>®</sup></div><span>LANGUAGE IS THE NEW CAD INTERFACE.</span><div><i className={backend === 'online' ? 'online' : ''} /> {backend === 'online' ? 'GEOMETRY ENGINE CONNECTED' : 'INTERACTIVE DEMO'} · 2026</div></footer>

      {helpOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHelpOpen(false); }}>
          <section className="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title">
            <button className="modal-close icon-button" type="button" onClick={() => setHelpOpen(false)} aria-label="关闭指南"><X size={18} /></button>
            <span className="section-index">QUICK START / 03</span><h2 id="help-title">把想法交给几何。</h2>
            <p>写下结构、尺寸和用途，选择工艺，剩下的交给语义规划器与 OCCT 内核。</p>
            <div className="shortcut-list"><div><span>聚焦提示词</span><kbd>CTRL / ⌘ + K</kbd></div><div><span>开始生成</span><kbd>CTRL / ⌘ + ENTER</kbd></div><div><span>旋转模型</span><kbd>鼠标拖拽</kbd></div><div><span>缩放视口</span><kbd>鼠标滚轮</kbd></div><div><span>关闭面板</span><kbd>ESC</kbd></div></div>
            <div className="help-note"><Activity size={16} /><span>未连接后端时为明确标注的交互演示；真实工业文件始终由 FastAPI 几何服务生成。</span></div>
            <button className="help-primary" type="button" onClick={() => { setHelpOpen(false); promptRef.current?.focus(); }}>开始描述 <ArrowUpRight size={17} /></button>
          </section>
        </div>
      )}
      <DrawingModal
        isOpen={drawingOpen}
        onClose={() => setDrawingOpen(false)}
        modelId={result?.model_id ?? null}
        title={modelTitle}
      />
      <ToastStack items={toasts} onDismiss={dismissToast} onAction={(item) => { if (item.kind === 'err') void handleGenerate(); }} />
    </div>
  );
}

export default App;
