import { useEffect, useRef } from 'react';
import * as THREE from 'three';

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform float uTheme;
  uniform float uGenerating;
  uniform vec2 uPointer;
  uniform vec2 uResolution;

  float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1., 0.)), f.x),
               mix(hash(i + vec2(0., 1.)), hash(i + vec2(1., 1.)), f.x), f.y);
  }

  float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    mat2 rotation = mat2(0.80, -0.60, 0.60, 0.80);
    for (int i = 0; i < 5; i++) {
      value += amplitude * noise(p);
      p = rotation * p * 2.03 + 7.1;
      amplitude *= 0.5;
    }
    return value;
  }

  void main() {
    vec2 p = vUv - 0.5;
    p.x *= uResolution.x / max(uResolution.y, 1.0);
    vec2 mouse = uPointer;
    mouse.x *= uResolution.x / max(uResolution.y, 1.0);

    float t = uTime * mix(0.055, 0.16, uGenerating);
    float md = length(p - mouse);
    float influence = exp(-md * 3.2);
    vec2 direction = normalize(p - mouse + vec2(0.0001));
    p += vec2(-direction.y, direction.x) * influence * 0.20;
    p += direction * influence * -0.10;

    vec2 q = vec2(fbm(p * 1.3 + vec2(t, -t * .4)),
                  fbm(p * 1.3 + vec2(5.2 - t * .5, 1.3 + t)));
    vec2 r = vec2(fbm(p * 1.5 + 2.6 * q + vec2(1.7, 9.2) + t),
                  fbm(p * 1.5 + 2.6 * q + vec2(8.3, 2.8) - t * .7));
    float f = fbm(p * 1.25 + 3.2 * r);

    float contours = pow(1.0 - abs(sin((f + r.x * .18) * 31.0)), 18.0);
    float fine = pow(1.0 - abs(sin((f + q.y * .1) * 71.0)), 40.0) * .25;
    float aura = smoothstep(.9, .08, length(p - vec2(.27, .04)));
    float halo = exp(-md * 4.5);

    vec3 darkBase = vec3(.031, .038, .034);
    vec3 lightBase = vec3(.895, .904, .866);
    vec3 base = mix(darkBase, lightBase, uTheme);
    vec3 acid = vec3(.843, 1.0, .263);
    vec3 sage = mix(vec3(.13, .19, .16), vec3(.31, .38, .32), uTheme);

    float field = contours * (.11 + aura * .25 + halo * .52 + uGenerating * .22);
    vec3 color = base;
    color += sage * (q.x * .11 + r.y * .055) * (1.0 - uTheme * .45);
    color = mix(color, acid, clamp(field + fine * aura, 0.0, .62));
    color += acid * halo * contours * .12;

    float vignette = 1.0 - smoothstep(.22, 1.05, length(vUv - .5));
    color *= mix(.72 + vignette * .28, .93 + vignette * .07, uTheme);
    gl_FragColor = vec4(color, 1.0);
  }
`;

interface Props {
  generating: boolean;
  theme: 'dark' | 'light';
}

export default function GenerativeBackground({ generating, theme }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const generatingRef = useRef(generating);
  const themeRef = useRef(theme);

  useEffect(() => { generatingRef.current = generating; }, [generating]);
  useEffect(() => { themeRef.current = theme; }, [theme]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    mount.appendChild(renderer.domElement);
    renderer.domElement.setAttribute('aria-hidden', 'true');

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const uniforms = {
      uTime: { value: 0 },
      uTheme: { value: themeRef.current === 'light' ? 1 : 0 },
      uGenerating: { value: 0 },
      uPointer: { value: new THREE.Vector2(0.25, 0.05) },
      uResolution: { value: new THREE.Vector2(1, 1) },
    };
    const material = new THREE.ShaderMaterial({ vertexShader, fragmentShader, uniforms });
    const geometry = new THREE.PlaneGeometry(2, 2);
    scene.add(new THREE.Mesh(geometry, material));

    const pointer = new THREE.Vector2(0.25, 0.05);
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reducedMotion = motionQuery.matches;
    let raf = 0;
    let last = performance.now();
    let elapsed = 0;
    let visible = true;

    const resize = () => {
      const { clientWidth: width, clientHeight: height } = mount;
      renderer.setSize(width, height, false);
      uniforms.uResolution.value.set(width, height);
    };
    const onPointerMove = (event: PointerEvent) => {
      pointer.set((event.clientX / window.innerWidth - .5) * 1.2, -(event.clientY / window.innerHeight - .5) * 1.2);
    };
    const onMotionChange = (event: MediaQueryListEvent) => { reducedMotion = event.matches; };
    const onVisibility = () => { visible = !document.hidden; last = performance.now(); };

    const render = (now: number) => {
      raf = requestAnimationFrame(render);
      const dt = Math.min((now - last) / 1000, .05);
      last = now;
      if (!visible) return;
      if (!reducedMotion) elapsed += dt;
      uniforms.uTime.value = elapsed;
      uniforms.uPointer.value.lerp(pointer, reducedMotion ? 1 : .045);
      uniforms.uGenerating.value += ((generatingRef.current ? 1 : 0) - uniforms.uGenerating.value) * .035;
      uniforms.uTheme.value += (((themeRef.current === 'light') ? 1 : 0) - uniforms.uTheme.value) * .06;
      renderer.render(scene, camera);
    };

    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    motionQuery.addEventListener('change', onMotionChange);
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('visibilitychange', onVisibility);
      motionQuery.removeEventListener('change', onMotionChange);
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="generative-background" aria-hidden="true" />;
}
