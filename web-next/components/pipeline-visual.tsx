"use client";

/**
 * The hero visual: the real recognition pipeline as a living diagram.
 *
 *   camera → detect → align → embed → match → confirm → register
 *
 * Canvas 2D with a light pseudo-3D (a drifting particle field with depth and mouse parallax,
 * pulses travelling along the pipeline). No WebGL library: it costs nothing to load and runs
 * on a phone. It pauses when off-screen or when the tab is hidden, uses fewer particles on
 * small screens, and under prefers-reduced-motion draws a single still frame.
 */
import { useEffect, useRef, useState } from "react";

const STAGES = [
  { key: "camera", label: "Camera", note: "CCTV · tablet · phone" },
  { key: "detect", label: "Detect", note: "SCRFD faces" },
  { key: "align", label: "Align", note: "112 × 112 crop" },
  { key: "embed", label: "Embed", note: "ArcFace 512-d" },
  { key: "match", label: "Match", note: "FAISS, class only" },
  { key: "confirm", label: "Confirm", note: "several frames" },
  { key: "mark", label: "Register", note: "present / late" },
];

type P = { x: number; y: number; z: number; vx: number; vy: number };

export function PipelineVisual() {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const hover = useRef<number | null>(null);
  hover.current = active;

  useEffect(() => {
    const el = canvas.current;
    const box = wrap.current;
    if (!el || !box) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, dpr = 1, raf = 0, visible = true, t0 = performance.now();
    const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
    let parts: P[] = [];

    const css = getComputedStyle(document.documentElement);
    const color = (v: string) => css.getPropertyValue(v).trim() || "#5C82FF";
    const C = { electric: color("--electric"), violet: color("--violet"), cyan: color("--cyan"), magenta: color("--magenta"), ink: color("--ink") };

    function resize() {
      const r = box!.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      el!.width = w * dpr; el!.height = h * dpr;
      el!.style.width = `${w}px`; el!.style.height = `${h}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = w < 640 ? 46 : 110;
      parts = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h, z: Math.random() * 0.9 + 0.1,
        vx: (Math.random() - 0.5) * 0.18, vy: (Math.random() - 0.5) * 0.18,
      }));
    }

    function nodePos(i: number) {
      const narrow = w < 640;
      if (narrow) {
        const cols = 2, row = Math.floor(i / cols), col = i % cols;
        const zig = row % 2 ? 1 - col : col;
        return { x: w * (0.27 + zig * 0.46), y: h * (0.13 + row * 0.25) };
      }
      const x = w * (0.08 + (i / (STAGES.length - 1)) * 0.84);
      const y = h * (0.5 + Math.sin(i * 0.9) * 0.18);
      return { x, y };
    }

    function frame(now: number) {
      const t = (now - t0) / 1000;
      mouse.x += (mouse.tx - mouse.x) * 0.06;
      mouse.y += (mouse.ty - mouse.y) * 0.06;
      ctx!.clearRect(0, 0, w, h);

      // depth field: nearer points are bigger, brighter and move more with the mouse
      for (const p of parts) {
        if (!reduce) {
          p.x += p.vx * p.z; p.y += p.vy * p.z;
          if (p.x < -10) p.x = w + 10; if (p.x > w + 10) p.x = -10;
          if (p.y < -10) p.y = h + 10; if (p.y > h + 10) p.y = -10;
        }
        const px = p.x + mouse.x * 18 * p.z, py = p.y + mouse.y * 14 * p.z;
        ctx!.globalAlpha = 0.12 + p.z * 0.45;
        ctx!.fillStyle = p.z > 0.6 ? C.cyan : C.violet;
        ctx!.beginPath(); ctx!.arc(px, py, 0.6 + p.z * 1.6, 0, Math.PI * 2); ctx!.fill();
      }
      ctx!.globalAlpha = 1;

      // pipeline links
      const pts = STAGES.map((_, i) => nodePos(i));
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], b = pts[i + 1];
        const g = ctx!.createLinearGradient(a.x, a.y, b.x, b.y);
        g.addColorStop(0, C.electric); g.addColorStop(1, C.violet);
        const lit = hover.current === i || hover.current === i + 1;
        ctx!.strokeStyle = g; ctx!.lineWidth = lit ? 2.4 : 1.4; ctx!.globalAlpha = lit ? 0.95 : 0.55;
        ctx!.beginPath(); ctx!.moveTo(a.x, a.y); ctx!.lineTo(b.x, b.y); ctx!.stroke();
        // travelling pulses
        for (let k = 0; k < 2; k++) {
          const f = reduce ? 0.5 : ((t * 0.45 + k * 0.5 + i * 0.13) % 1);
          const x = a.x + (b.x - a.x) * f, y = a.y + (b.y - a.y) * f;
          const rg = ctx!.createRadialGradient(x, y, 0, x, y, 9);
          rg.addColorStop(0, C.cyan); rg.addColorStop(1, "transparent");
          ctx!.globalAlpha = 0.9; ctx!.fillStyle = rg;
          ctx!.beginPath(); ctx!.arc(x, y, 9, 0, Math.PI * 2); ctx!.fill();
        }
      }
      ctx!.globalAlpha = 1;
      if (!reduce && visible) raf = requestAnimationFrame(frame);
    }

    function onMove(e: PointerEvent) {
      const r = box!.getBoundingClientRect();
      mouse.tx = (e.clientX - r.left) / r.width - 0.5;
      mouse.ty = (e.clientY - r.top) / r.height - 0.5;
    }
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && document.visibilityState === "visible";
      cancelAnimationFrame(raf);
      if (visible || reduce) raf = requestAnimationFrame(frame);
    });
    const onVis = () => {
      visible = document.visibilityState === "visible";
      cancelAnimationFrame(raf);
      if (visible) raf = requestAnimationFrame(frame);
    };
    const ro = new ResizeObserver(() => { resize(); cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); });

    resize();
    ro.observe(box);
    io.observe(box);
    document.addEventListener("visibilitychange", onVis);
    if (!reduce) window.addEventListener("pointermove", onMove, { passive: true });
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect(); io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("pointermove", onMove);
    };
  }, []);

  return (
    <div ref={wrap} className="relative h-[460px] w-full sm:h-[380px]" role="img"
         aria-label="Recognition pipeline: camera, detect, align, embed, match against the class, confirm over several frames, then mark the register.">
      <canvas ref={canvas} className="absolute inset-0" aria-hidden="true" />
      <NodeLayer active={active} setActive={setActive} />
    </div>
  );
}

/** The stage labels, as real (focusable) elements laid over the canvas at the same positions. */
function NodeLayer({ active, setActive }: { active: number | null; setActive: (i: number | null) => void }) {
  return (
    <ol className="pointer-events-none absolute inset-0 m-0 list-none p-0">
      {STAGES.map((s, i) => {
        const narrowPos = (() => {
          const row = Math.floor(i / 2), col = i % 2, zig = row % 2 ? 1 - col : col;
          return { left: `${27 + zig * 46}%`, top: `${13 + row * 25}%` };
        })();
        const widePos = { left: `${8 + (i / (STAGES.length - 1)) * 84}%`, top: `${50 + Math.sin(i * 0.9) * 18}%` };
        const on = active === i;
        return (
          <li key={s.key}>
            {[["sm:hidden", narrowPos], ["hidden sm:block", widePos]].map(([cls, pos]) => (
              <button
                key={cls as string}
                type="button"
                onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(i)} onBlur={() => setActive(null)}
                className={`${cls} pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 cursor-default border-0 bg-transparent p-0 text-center`}
                style={pos as React.CSSProperties}
                aria-label={`${s.label}: ${s.note}`}
              >
                <span className="glass mx-auto grid h-12 w-12 place-items-center rounded-2xl border text-[11px] font-semibold transition-transform duration-200"
                      style={{
                        borderColor: on ? "var(--electric)" : "var(--rule)",
                        transform: on ? "scale(1.12)" : undefined,
                        boxShadow: on ? "var(--shadow-glow)" : "var(--shadow-md)",
                        color: on ? "var(--electric)" : "var(--ink)",
                      }}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="mt-1.5 block whitespace-nowrap text-[13px] font-semibold text-ink">{s.label}</span>
                <span className={`block whitespace-nowrap text-[11.5px] text-ash transition-opacity duration-200 ${on ? "opacity-100" : "opacity-70"}`}>{s.note}</span>
              </button>
            ))}
          </li>
        );
      })}
    </ol>
  );
}
