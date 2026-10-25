import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { fetchGlb } from '../lib/api';
import type { ModelResult } from '../types';

export interface CadViewportHandle {
  reset: () => void;
  setView: (view: 'iso' | 'top' | 'front' | 'right') => void;
  zoom: (direction: 1 | -1) => void;
  capture: () => string | undefined;
}

interface Props {
  result: ModelResult | null;
  wireframe: boolean;
  xray: boolean;
  showGrid: boolean;
  autoRotate: boolean;
  generating: boolean;
  theme: 'dark' | 'light';
  onLoadState?: (loading: boolean) => void;
  sectionAxis?: 'none' | 'x' | 'y' | 'z';
  sectionDepth?: number;
  sectionFlipped?: boolean;
}

interface SceneContext {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  model: THREE.Group;
  grid: THREE.GridHelper;
  rings: THREE.Group;
  renderOnce: () => void;
  applyAppearance: () => void;
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((child) => {
    if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments) {
      child.geometry?.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((material) => {
        if (!material) return;
        const withMap = material as THREE.Material & { map?: THREE.Texture | null };
        withMap.map?.dispose();
        material.dispose();
      });
    }
  });
}

function createDemoOrganizer() {
  const group = new THREE.Group();
  group.name = 'FORMA procedural desk organizer';
  const shell = new THREE.MeshPhysicalMaterial({
    color: 0xdfe4da,
    roughness: .28,
    metalness: .08,
    clearcoat: .45,
    clearcoatRoughness: .24,
  });
  const acid = new THREE.MeshStandardMaterial({ color: 0xd7ff43, roughness: .38, metalness: .05 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x1c221c, roughness: .52 });

  const addPart = (geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number, edges = true) => {
    const mesh = new THREE.Mesh(geometry, material.clone());
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.baseColor = (material as THREE.MeshStandardMaterial).color?.getHex() ?? 0xdfe4da;
    mesh.userData.baseOpacity = 1;
    group.add(mesh);
    if (edges) {
      const line = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry, 32),
        new THREE.LineBasicMaterial({ color: 0x253023, transparent: true, opacity: .24 }),
      );
      line.userData.isEdge = true;
      mesh.add(line);
    }
    return mesh;
  };

  addPart(new RoundedBoxGeometry(4.8, .24, 3.2, 5, .12), shell, 0, .12, 0);
  addPart(new RoundedBoxGeometry(4.68, 1.65, .18, 4, .08), shell, 0, .96, -1.49);
  addPart(new RoundedBoxGeometry(4.68, 1.18, .18, 4, .08), shell, 0, .72, 1.49);
  addPart(new RoundedBoxGeometry(.18, 1.65, 3.0, 4, .08), shell, -2.31, .96, 0);
  addPart(new RoundedBoxGeometry(.18, 1.65, 3.0, 4, .08), shell, 2.31, .96, 0);
  addPart(new RoundedBoxGeometry(.12, 1.32, 2.84, 3, .05), shell, -.72, .78, 0);
  addPart(new RoundedBoxGeometry(.12, 1.32, 2.84, 3, .05), shell, .82, .78, 0);

  for (let i = 0; i < 4; i += 1) {
    addPart(new RoundedBoxGeometry(.06, .65, .12, 2, .025), dark, -2.415, .56 + i * .23, -.65 + i * .42, false);
  }
  addPart(new RoundedBoxGeometry(.72, .28, .035, 3, .025), acid, 1.45, .69, 1.595, false);

  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const context = canvas.getContext('2d')!;
  context.fillStyle = '#d7ff43';
  context.fillRect(0, 0, 512, 128);
  context.fillStyle = '#11150e';
  context.font = '700 54px monospace';
  context.fillText('FORMA / 001', 34, 82);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(.69, .17),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true }),
  );
  label.position.set(1.45, .69, 1.617);
  group.add(label);
  group.rotation.y = -.16;
  return group;
}

const CadViewport = forwardRef<CadViewportHandle, Props>(function CadViewport({
  result, wireframe, xray, showGrid, autoRotate, generating, theme, onLoadState,
  sectionAxis = 'none', sectionDepth = 0, sectionFlipped = false,
}, ref) {
  const mountRef = useRef<HTMLDivElement>(null);
  const contextRef = useRef<SceneContext | null>(null);
  const optionsRef = useRef({ wireframe, xray, showGrid, autoRotate, generating, theme, sectionAxis, sectionDepth, sectionFlipped });
  const [ready, setReady] = useState(false);
  optionsRef.current = { wireframe, xray, showGrid, autoRotate, generating, theme, sectionAxis, sectionDepth, sectionFlipped };

  const setCameraView = (view: 'iso' | 'top' | 'front' | 'right') => {
    const ctx = contextRef.current;
    if (!ctx) return;
    const positions = {
      iso: new THREE.Vector3(7.4, 5.8, 8.4),
      top: new THREE.Vector3(0, 11.5, .001),
      front: new THREE.Vector3(0, 2.8, 11.5),
      right: new THREE.Vector3(11.5, 3.4, 0),
    };
    ctx.camera.position.copy(positions[view]);
    ctx.controls.target.set(0, .8, 0);
    ctx.controls.update();
    ctx.renderOnce();
  };

  useImperativeHandle(ref, () => ({
    reset: () => setCameraView('iso'),
    setView: setCameraView,
    zoom: (direction) => {
      const ctx = contextRef.current;
      if (!ctx) return;
      const offset = ctx.camera.position.clone().sub(ctx.controls.target).multiplyScalar(direction === 1 ? .84 : 1.18);
      ctx.camera.position.copy(ctx.controls.target).add(offset);
      ctx.controls.update();
      ctx.renderOnce();
    },
    capture: () => {
      const ctx = contextRef.current;
      if (!ctx) return undefined;
      ctx.renderer.render(ctx.scene, ctx.camera);
      return ctx.renderer.domElement.toDataURL('image/png');
    },
  }));

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, .1, 100);
    camera.position.set(7.4, 5.8, 8.4);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    renderer.localClippingEnabled = true;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute('aria-label', '可交互三维模型视口，拖拽旋转，滚轮缩放');
    renderer.domElement.setAttribute('role', 'img');
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = .065;
    controls.target.set(0, .8, 0);
    controls.minDistance = 5;
    controls.maxDistance = 22;
    controls.maxPolarAngle = Math.PI * .49;
    controls.autoRotateSpeed = .75;

    scene.add(new THREE.HemisphereLight(0xf3ffe8, 0x17231a, 2.25));
    const key = new THREE.DirectionalLight(0xffffff, 4.1);
    key.position.set(4, 9, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -7;
    key.shadow.camera.right = 7;
    key.shadow.camera.top = 7;
    key.shadow.camera.bottom = -7;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xd7ff43, 3.3);
    rim.position.set(-6, 3, -5);
    scene.add(rim);
    const fill = new THREE.DirectionalLight(0x8db9a2, 1.6);
    fill.position.set(5, 1, -5);
    scene.add(fill);

    const grid = new THREE.GridHelper(28, 56, 0x617052, 0x3c493b);
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    gridMaterials.forEach((material) => { material.transparent = true; material.opacity = .17; });
    grid.position.y = -.025;
    scene.add(grid);

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ color: 0x000000, opacity: .2 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    floor.position.y = -.04;
    scene.add(floor);

    const rings = new THREE.Group();
    [3.8, 4.35].forEach((radius, index) => {
      const curve = new THREE.EllipseCurve(0, 0, radius, radius, 0, Math.PI * 2);
      const points = curve.getPoints(160).map((point) => new THREE.Vector3(point.x, 0, point.y));
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const line = new THREE.LineLoop(geometry, new THREE.LineBasicMaterial({ color: 0xd7ff43, transparent: true, opacity: index ? .07 : .14 }));
      line.position.y = -.015;
      rings.add(line);
    });
    scene.add(rings);

    const model = createDemoOrganizer();
    scene.add(model);

    const renderOnce = () => renderer.render(scene, camera);
    const applyAppearance = () => {
      const options = optionsRef.current;
      grid.visible = options.showGrid;
      rings.visible = options.showGrid;
      controls.autoRotate = options.autoRotate && !options.generating;

      if (!options.sectionAxis || options.sectionAxis === 'none') {
        renderer.clippingPlanes = [];
      } else {
        const normal = new THREE.Vector3(
          options.sectionAxis === 'x' ? 1 : 0,
          options.sectionAxis === 'y' ? 1 : 0,
          options.sectionAxis === 'z' ? 1 : 0
        );
        if (options.sectionFlipped) normal.negate();
        const constant = -(options.sectionDepth ?? 0) * (options.sectionFlipped ? -1 : 1);
        renderer.clippingPlanes = [new THREE.Plane(normal, constant)];
      }

      model.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach((material) => {
          if (!(material instanceof THREE.MeshStandardMaterial) && !(material instanceof THREE.MeshPhysicalMaterial)) return;
          material.wireframe = options.wireframe;
          material.transparent = options.xray;
          material.opacity = options.xray ? .24 : 1;
          material.depthWrite = !options.xray;
          material.side = options.xray ? THREE.DoubleSide : THREE.FrontSide;
          material.needsUpdate = true;
        });
        child.children.forEach((edge) => {
          if (edge.userData.isEdge) edge.visible = !options.wireframe;
        });
      });
      renderOnce();
    };

    const resize = () => {
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderOnce();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    contextRef.current = { scene, camera, renderer, controls, model, grid, rings, renderOnce, applyAppearance };
    resize();
    applyAppearance();
    setReady(true);

    let raf = 0;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const animate = () => {
      raf = requestAnimationFrame(animate);
      if (document.hidden) return;
      controls.update();
      if (!motionQuery.matches && optionsRef.current.generating) model.rotation.y += .0015;
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      contextRef.current = null;
      disposeObject(scene);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  useEffect(() => { contextRef.current?.applyAppearance(); }, [wireframe, xray, showGrid, autoRotate, generating, theme]);

  useEffect(() => {
    if (!result || !ready) return;
    const ctx = contextRef.current;
    if (!ctx) return;
    const controller = new AbortController();
    onLoadState?.(true);
    fetchGlb(result.model_id, controller.signal)
      .then((buffer) => new GLTFLoader().parseAsync(buffer, ''))
      .then((gltf) => {
        if (controller.signal.aborted) { disposeObject(gltf.scene); return; }
        const current = contextRef.current;
        if (!current) { disposeObject(gltf.scene); return; }
        current.scene.remove(current.model);
        disposeObject(current.model);
        const wrapper = new THREE.Group();
        const imported = gltf.scene;
        imported.rotation.x = -Math.PI / 2;
        wrapper.add(imported);
        wrapper.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(wrapper);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const scale = 5.4 / Math.max(size.x, size.y, size.z, .001);
        wrapper.scale.setScalar(scale);
        wrapper.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
        wrapper.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });
        current.scene.add(wrapper);
        current.model = wrapper;
        current.applyAppearance();
        setCameraView('iso');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        console.error('GLB preview failed', error);
      })
      .finally(() => { if (!controller.signal.aborted) onLoadState?.(false); });
    return () => { controller.abort(); onLoadState?.(false); };
  }, [result, ready]);

  return (
    <div className="cad-canvas-wrap">
      <div ref={mountRef} className="cad-canvas" />
      {generating && (
        <div className="viewport-generating" aria-live="polite">
          <span className="scan-bracket" />
          <span className="micro-label">REBUILDING GEOMETRY</span>
        </div>
      )}
    </div>
  );
});

export default CadViewport;
