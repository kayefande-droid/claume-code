/* claume bot — avatar.js (v3.2)
 * Interactive genderless humanoid head rendered as a LOW-DENSITY 3D point
 * cloud + geometric plexus network (per the master design brief):
 *   1. ~20% particle density of a solid model — sparse grains, visible
 *      empty space and depth between dots.
 *   2. Proximity-based ultra-thin filaments connect nearby points,
 *      outlining the structural wireframe of the head.
 *   3. Custom GLSL vertex shader: grains float/drift over time while
 *      keeping their structural anchors.
 *   4. Minimal palette: glowing cyan / electric-blue on dark; two amber
 *      ear-pod accents + bright eye cores as a nod to the reference art.
 * Responsive, pointer-parallax, state-driven (BOOTING/IDLE/LISTENING/
 * THINKING/SPEAKING) via Avatar.setMode().
 */
'use strict';

(function () {
  if (!window.THREE) return;

  const COL_CYAN = new THREE.Color('#39e6ff');
  const COL_BLUE = new THREE.Color('#2b7fff');
  const COL_WHITE = new THREE.Color('#d9fbff');
  const COL_AMBER = new THREE.Color('#ffab2e');

  // ------------------------------------------------------------------
  // 1) Procedural humanoid head point cloud (sparse by construction)
  // ------------------------------------------------------------------
  function buildHeadPoints() {
    const pts = [];   // {x,y,z, c:Color, size, accent}
    const N = 2500;   // grain count for the head+neck shell (~20% density)

    // Fibonacci sphere distribution — perfectly even coverage.
    const ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const t = (i + 0.5) / N;
      const y = 1 - 2 * t;                 // -1..1
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = ga * i;
      let x = Math.cos(th) * r;
      let z = Math.sin(th) * r;

      let rad = 0.98;
      let color = Math.random() < 0.5 ? COL_CYAN : COL_BLUE;
      let size = 1.6 + Math.random() * 1.5;
      let accent = 0;

      if (y >= -0.08) {
        // ----- head: ellipsoid warp + jaw taper + face flatten -----
        const hy = y; // -0.08..1
        rad = 0.98;
        x *= 0.80;                                    // narrow sides
        z *= 0.92;
        // jaw/chin taper toward the bottom of the head
        const jaw = THREE.MathUtils.smoothstep(-hy, 0.05, 0.75);
        x *= 1.0 - 0.30 * jaw;
        z *= 1.0 - 0.10 * jaw;
        // flatten the face plane slightly so features read front-on
        if (z > 0) z *= 0.88;
        // chin hint
        if (hy < -0.45 && z > 0) z += 0.10 * (-hy - 0.45);
        // crown slightly narrower
        if (hy > 0.55) x *= 1.0 - 0.25 * THREE.MathUtils.smoothstep(hy, 0.55, 1.0);
      } else {
        // ----- neck + shoulder flare -----
        const ny = -y; // 0.08..1
        rad = 0.36 - 0.05 * ny;
        if (ny > 0.78) {
          const s = (ny - 0.78) / 0.22;               // shoulders spread
          rad = 0.31 + s * 1.05;
          z *= 0.42;                                  // shoulders are flat-ish
          size *= 1.15;
        }
        if (Math.random() < 0.06) color = COL_WHITE;  // spine glints
      }

      // organic jitter so grains don't sit on a perfect shell
      const j = 1 + (Math.random() - 0.5) * 0.05;
      pts.push({ x: x * rad * j, y: y * 1.06, z: z * rad * j, c: color, s: size, a: accent });
    }

    // ----- eyes: two bright cyan cores -----
    for (const ex of [-0.30, 0.30]) {
      for (let k = 0; k < 34; k++) {
        pts.push({
          x: ex + (Math.random() - 0.5) * 0.14,
          y: 0.16 + (Math.random() - 0.5) * 0.09,
          z: 0.74 + Math.random() * 0.05,
          c: COL_WHITE, s: 2.2 + Math.random() * 1.4, a: 1,
        });
      }
    }

    // ----- amber ear pods (reference-art accent) -----
    for (const ex of [-0.84, 0.84]) {
      for (let k = 0; k < 46; k++) {
        pts.push({
          x: ex + (Math.random() - 0.5) * 0.16,
          y: 0.02 + (Math.random() - 0.5) * 0.30,
          z: (Math.random() - 0.5) * 0.24,
          c: COL_AMBER, s: 2.0 + Math.random() * 1.6, a: 2,
        });
      }
    }

    // ----- inverted forehead triangle (dark void + outline glints) -----
    const tri = [[0, 0.66], [-0.075, 0.50], [0.075, 0.50]];
    for (let e = 0; e < 3; e++) {
      const a = tri[e], b = tri[(e + 1) % 3];
      for (let k = 0; k <= 14; k++) {
        const f = k / 14;
        pts.push({
          x: a[0] + (b[0] - a[0]) * f,
          y: a[1] + (b[1] - a[1]) * f,
          z: 0.80,
          c: COL_WHITE, s: 1.8, a: 3,
        });
      }
    }
    return pts;
  }

  // ------------------------------------------------------------------
  // 2) Plexus: connect nearby grains with ultra-thin filaments
  // ------------------------------------------------------------------
  function buildPlexus(pts) {
    const P = pts.filter((p) => p.a === 0);
    const maxD = 0.135, maxLinks = 3;
    const links = new Array(P.length).fill(0);
    const segs = [];
    for (let i = 0; i < P.length && segs.length < 5200; i++) {
      for (let j = i + 1; j < P.length; j++) {
        if (links[i] >= maxLinks) break;
        if (links[j] >= maxLinks) continue;
        const dx = P[i].x - P[j].x, dy = P[i].y - P[j].y, dz = P[i].z - P[j].z;
        const d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < maxD * maxD) {
          segs.push(P[i].x, P[i].y, P[i].z, P[j].x, P[j].y, P[j].z);
          links[i]++; links[j]++;
        }
      }
    }
    return segs;
  }

  // ------------------------------------------------------------------
  // 3) Scene
  // ------------------------------------------------------------------
  const canvas = document.getElementById('avatar');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
  camera.position.set(0, 0.06, 4.15);

  const group = new THREE.Group();
  scene.add(group);

  const pts = buildHeadPoints();

  // points geometry + custom GLSL material
  const pgeo = new THREE.BufferGeometry();
  const pos = new Float32Array(pts.length * 3);
  const col = new Float32Array(pts.length * 3);
  const siz = new Float32Array(pts.length);
  const sed = new Float32Array(pts.length);
  pts.forEach((p, i) => {
    pos.set([p.x, p.y, p.z], i * 3);
    col.set([p.c.r, p.c.g, p.c.b], i * 3);
    siz[i] = p.s;
    sed[i] = Math.random();
  });
  pgeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  pgeo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
  pgeo.setAttribute('aSize', new THREE.BufferAttribute(siz, 1));
  pgeo.setAttribute('aSeed', new THREE.BufferAttribute(sed, 1));

  const pmat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uAmp: { value: 1.0 },     // drift amplitude — state driven
      uBoost: { value: 1.0 },   // brightness — state driven
    },
    vertexShader: `
      attribute float aSize;
      attribute vec3 aColor;
      attribute float aSeed;
      uniform float uTime;
      uniform float uAmp;
      varying vec3 vColor;
      varying float vTw;
      void main() {
        vec3 p = position;
        // structural anchors + gentle per-grain drift (seeded, bounded)
        float t = uTime * 0.55 + aSeed * 6.2831;
        p += uAmp * 0.016 * vec3(
          sin(t * 1.3 + position.y * 4.0),
          cos(t * 1.1 + position.x * 4.0),
          sin(t * 0.9 + position.z * 4.0)
        );
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = aSize * (150.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
        vColor = aColor;
        vTw = 0.8 + 0.2 * sin(t * 2.1);
      }
    `,
    fragmentShader: `
      varying vec3 vColor;
      varying float vTw;
      uniform float uBoost;
      void main() {
        vec2 uv = gl_PointCoord - 0.5;
        float d = length(uv);
        float a = pow(smoothstep(0.5, 0.0, d), 1.8);
        gl_FragColor = vec4(vColor * (0.9 + 0.5 * vTw) * uBoost, a);
      }
    `,
  });
  group.add(new THREE.Points(pgeo, pmat));

  // plexus filaments
  const segs = buildPlexus(pts);
  const lgeo = new THREE.BufferGeometry();
  lgeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(segs), 3));
  const lmat = new THREE.LineBasicMaterial({
    color: new THREE.Color('#0e7490'),
    transparent: true,
    opacity: 0.30,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  group.add(new THREE.LineSegments(lgeo, lmat));

  // ------------------------------------------------------------------
  // 4) State machine + animation loop
  // ------------------------------------------------------------------
  const TARGETS = {
    BOOTING:   { amp: 2.6, boost: 0.6, spin: 0.22, tilt: 0.10 },
    IDLE:      { amp: 1.0, boost: 1.0, spin: 0.10, tilt: 0.03 },
    LISTENING: { amp: 1.7, boost: 1.25, spin: 0.05, tilt: -0.06 },
    THINKING:  { amp: 2.3, boost: 1.1, spin: 0.45, tilt: 0.05 },
    SPEAKING:  { amp: 2.0, boost: 1.45, spin: 0.08, tilt: -0.03 },
  };
  const cur = { amp: 2.6, boost: 0.6, spin: 0.22, tilt: 0.10 };
  let target = TARGETS.BOOTING;
  let mouseX = 0, mouseY = 0;

  window.Avatar = {
    setMode(mode) { target = TARGETS[mode] || TARGETS.IDLE; },
  };

  window.addEventListener('mousemove', (e) => {
    mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
    mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
  });

  function resize() {
    const w = canvas.clientWidth || window.innerWidth;
    const h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  resize();

  const clock = new THREE.Clock();
  (function loop() {
    requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;

    // ease toward state targets
    const k = 1 - Math.pow(0.002, dt);
    cur.amp += (target.amp - cur.amp) * k;
    cur.boost += (target.boost - cur.boost) * k;
    cur.spin += (target.spin - cur.spin) * k;
    cur.tilt += (target.tilt - cur.tilt) * k;

    pmat.uniforms.uTime.value = t;
    pmat.uniforms.uAmp.value = cur.amp;
    pmat.uniforms.uBoost.value = cur.boost;

    // slow sentient sway + pointer parallax + breathing
    group.rotation.y += ((Math.sin(t * 0.24) * 0.35 + mouseX * 0.45) - group.rotation.y) * (k * 0.6) + dt * cur.spin * 0.05;
    group.rotation.x = THREE.MathUtils.lerp(group.rotation.x, mouseY * 0.18 + cur.tilt, k * 0.6);
    const breathe = 1 + Math.sin(t * 0.9) * 0.008;
    group.scale.setScalar(breathe);
    group.position.y = Math.sin(t * 0.7) * 0.03;

    renderer.render(scene, camera);
  })();
})();
