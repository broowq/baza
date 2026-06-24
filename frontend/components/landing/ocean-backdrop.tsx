"use client";

import { useEffect, useRef } from "react";

/**
 * Bioluminescent pixel-ocean hero backdrop.
 *
 * A low-res grid driven by domain-warped, layered FBM waves, painted into a
 * canvas whose backing store matches the hero's aspect ratio (so the upscaled
 * pixels stay square) and shown with `image-rendering: pixelated`. All temporal
 * terms ride integer harmonics and time is `now % LOOP`, so the motion loops
 * seamlessly.
 *
 * Theme-adaptive: on the dark theme it's the deep-sea bioluminescent loop
 * (normal blend, full strength); on the light theme it re-renders as soft
 * teal/mint ripples on white via a light palette + `multiply` blend, so it
 * reads as elegant brand-coloured water instead of muddy smudges. Reacts to
 * the live theme toggle, honours reduced-motion, and pauses off-screen/hidden.
 */
export function OceanBackdrop({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    const N = 4096;
    const MASK = N - 1;
    const TWO_PI = Math.PI * 2;
    const K = N / TWO_PI;
    const S = new Float32Array(N);
    for (let i = 0; i < N; i++) S[i] = Math.sin((i / N) * TWO_PI);
    const fs = (x: number) => S[((x * K) | 0) & MASK];

    const buildPal = (stops: number[][]) => {
      const pal = new Uint8Array(256 * 3);
      for (let p = 0; p < 256; p++) {
        const tt = p / 255;
        let a = stops[0];
        let b = stops[stops.length - 1];
        for (let s = 0; s < stops.length - 1; s++) {
          if (tt >= stops[s][0] && tt <= stops[s + 1][0]) {
            a = stops[s];
            b = stops[s + 1];
            break;
          }
        }
        const f = b[0] - a[0] > 0 ? (tt - a[0]) / (b[0] - a[0]) : 0;
        pal[p * 3] = (a[1] + (b[1] - a[1]) * f) | 0;
        pal[p * 3 + 1] = (a[2] + (b[2] - a[2]) * f) | 0;
        pal[p * 3 + 2] = (a[3] + (b[3] - a[3]) * f) | 0;
      }
      return pal;
    };

    const palDark = buildPal([
      [0.0, 0, 0, 0],
      [0.3, 6, 40, 70],
      [0.52, 12, 110, 140],
      [0.7, 30, 180, 185],
      [0.85, 72, 230, 214],
      [1.0, 172, 250, 238],
    ]);
    const palLight = buildPal([
      [0.0, 255, 255, 255],
      [0.32, 226, 240, 238],
      [0.54, 184, 220, 216],
      [0.72, 138, 196, 192],
      [0.86, 108, 176, 174],
      [1.0, 86, 158, 156],
    ]);

    const P2 = Math.PI * 2;
    const oc: number[][] = [
      [P2 * 1.1, P2 * 0.7, 1, 1.0, 0.0],
      [P2 * -1.9, P2 * 1.5, 2, 0.55, 1.3],
      [P2 * 2.7, P2 * 2.3, 3, 0.32, 2.1],
      [P2 * -3.6, P2 * -3.1, 2, 0.2, 0.7],
      [P2 * 5.0, P2 * 4.3, 3, 0.12, 3.0],
    ];
    const sumAmp = 2.19;
    const WARP = 0.1;
    const LOOP = 9000;

    let PAL = palDark;
    let SHR = 200;
    let SHG = 235;
    let SHB = 230;
    let VIG = 0.5;
    let GAIN = 1.15;

    let GW = 160;
    let GH = 90;
    let img = ctx.createImageData(GW, GH);

    const resize = () => {
      const w = cv.clientWidth || 1280;
      const h = cv.clientHeight || 720;
      let gw = Math.max(64, Math.min(210, Math.round(w / 6)));
      let gh = Math.max(40, Math.min(360, Math.round(h / 6)));
      if (gw * gh > 20000) {
        const f = Math.sqrt(20000 / (gw * gh));
        gw = Math.round(gw * f);
        gh = Math.round(gh * f);
      }
      GW = gw;
      GH = gh;
      cv.width = GW;
      cv.height = GH;
      img = ctx.createImageData(GW, GH);
    };
    resize();

    const frame = (t: number) => {
      const data = img.data;
      const br = 0.9 + 0.1 * fs(t);
      const invGW = 1 / GW;
      let idx = 0;
      for (let y = 0; y < GH; y++) {
        const ny = y / GH;
        const cyc = y * invGW;
        for (let x = 0; x < GW; x++) {
          const nx = x / GW;
          const cxc = x * invGW;
          const wxv =
            0.7 * fs(P2 * 0.9 * cxc + P2 * 0.6 * cyc + t) +
            0.35 * fs(P2 * 1.6 * cyc - P2 * 0.5 * cxc + 2 * t + 1.7);
          const wyv =
            0.7 * fs(P2 * 0.7 * cyc - P2 * 0.5 * cxc + t + 0.6) +
            0.35 * fs(P2 * 1.8 * cxc + P2 * 0.4 * cyc - 2 * t + 2.2);
          const wx = cxc + WARP * wxv;
          const wy = cyc + WARP * wyv;
          let h = 0;
          for (let k = 0; k < 5; k++) {
            const o = oc[k];
            h += o[3] * fs(o[0] * wx + o[1] * wy + o[2] * t + o[4]);
          }
          let v = 0.5 + 0.5 * (h / sumAmp);
          if (v < 0) v = 0;
          else if (v > 1) v = 1;
          const s1 = fs(P2 * 7.0 * wx + 3 * t) * 0.5 + 0.5;
          const s2 = fs(P2 * 6.3 * wy - 2 * t + 1.1) * 0.5 + 0.5;
          let sh = s1 * s2;
          sh = sh * sh;
          sh = sh * sh;
          let crest = (v - 0.62) / 0.38;
          if (crest < 0) crest = 0;
          const hl = sh * crest * crest;
          const pi = (v * 255) | 0;
          const m = (1 - VIG * ((nx - 0.5) * (nx - 0.5) + (ny - 0.5) * (ny - 0.5))) * br * GAIN;
          let r = (PAL[pi * 3] + hl * SHR) * m;
          let g = (PAL[pi * 3 + 1] + hl * SHG) * m;
          let b = (PAL[pi * 3 + 2] + hl * SHB) * m;
          data[idx] = r < 0 ? 0 : r > 255 ? 255 : r;
          data[idx + 1] = g < 0 ? 0 : g > 255 ? 255 : g;
          data[idx + 2] = b < 0 ? 0 : b > 255 ? 255 : b;
          data[idx + 3] = 255;
          idx += 4;
        }
      }
      ctx.putImageData(img, 0, 0);
    };

    const applyTheme = () => {
      const light = document.documentElement.classList.contains("theme-light");
      if (light) {
        PAL = palLight;
        SHR = -26;
        SHG = -22;
        SHB = -22;
        VIG = 0.12;
        GAIN = 1.0;
        cv.style.mixBlendMode = "multiply";
        cv.style.opacity = "0.62";
      } else {
        PAL = palDark;
        SHR = 200;
        SHG = 235;
        SHB = 230;
        VIG = 0.5;
        GAIN = 1.15;
        cv.style.mixBlendMode = "normal";
        cv.style.opacity = "1";
      }
    };
    applyTheme();

    const themeObs = new MutationObserver(() => {
      applyTheme();
      if (reduce) frame(0);
    });
    themeObs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce) {
      frame(0);
      return () => themeObs.disconnect();
    }

    let raf = 0;
    let visible = true;
    const tick = (now: number) => {
      frame(P2 * ((now % LOOP) / LOOP));
      raf = requestAnimationFrame(tick);
    };
    const start = () => {
      if (!raf && visible && !document.hidden) raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };

    let rraf = 0;
    const ro = new ResizeObserver(() => {
      if (rraf) cancelAnimationFrame(rraf);
      rraf = requestAnimationFrame(resize);
    });
    ro.observe(cv);

    const io = new IntersectionObserver(
      (entries) => {
        visible = entries[0]?.isIntersecting ?? true;
        if (visible) start();
        else stop();
      },
      { threshold: 0 },
    );
    io.observe(cv);
    const onVis = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVis);
    start();

    return () => {
      stop();
      io.disconnect();
      ro.disconnect();
      themeObs.disconnect();
      if (rraf) cancelAnimationFrame(rraf);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden
      className={["ocean-canvas", className].filter(Boolean).join(" ")}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        zIndex: 2,
        imageRendering: "pixelated",
        pointerEvents: "none",
      }}
    />
  );
}
