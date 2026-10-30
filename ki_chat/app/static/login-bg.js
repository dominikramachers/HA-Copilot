"use strict";

// Animierter Hintergrund der Anmeldeseite: langsam treibende Punkte, die sich bei Nähe mit feinen Linien verbinden.
// Farben kommen aus dem Theme (--accent, --bg), passen sich also Hell/Dunkel und eigenen Farben an.
// Hält an, wenn der Tab verdeckt ist; bei „Bewegung reduzieren“ wird nur ein ruhiges Standbild gezeichnet.
// Ausblenden: in custom.css `canvas#particles { display: none; }`.
(function () {
  const canvas = document.getElementById("particles");
  if (!canvas || !canvas.getContext) return;
  if (getComputedStyle(canvas).display === "none") return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const root = document.documentElement;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.body.appendChild(probe);

  let width = 0;
  let height = 0;
  let dots = [];
  let colour = [23, 92, 211];
  let dark = false;
  let frame = 0;
  let last = 0;

  function resolve(variable, fallback) {
    probe.style.color = "";
    probe.style.color = "var(" + variable + ")";
    const m = /rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(getComputedStyle(probe).color);
    return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : fallback;
  }

  function readColours() {
    colour = resolve("--accent", [23, 92, 211]);
    const bg = resolve("--bg", [243, 244, 246]);
    dark = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) < 128;
  }

  function seed() {
    const count = Math.max(18, Math.min(90, Math.round((width * height) / 17000)));
    dots = Array.from({ length: count }, () => {
      const angle = Math.random() * Math.PI * 2;
      const speed = 5 + Math.random() * 9; // Pixel pro Sekunde
      return {
        x: Math.random() * width,
        y: Math.random() * height,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        r: 1.1 + Math.random() * 1.5,
      };
    });
  }

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    seed();
    draw();
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    const [r, g, b] = colour;
    const dotAlpha = dark ? 0.7 : 0.45;
    const lineAlpha = dark ? 0.3 : 0.2;
    const reach = Math.min(150, Math.max(90, width / 9));
    ctx.lineWidth = 1;
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        const dx = dots[i].x - dots[j].x;
        const dy = dots[i].y - dots[j].y;
        const d = Math.hypot(dx, dy);
        if (d < reach) {
          ctx.strokeStyle = "rgba(" + r + "," + g + "," + b + "," + (lineAlpha * (1 - d / reach)).toFixed(3) + ")";
          ctx.beginPath();
          ctx.moveTo(dots[i].x, dots[i].y);
          ctx.lineTo(dots[j].x, dots[j].y);
          ctx.stroke();
        }
      }
    }
    ctx.fillStyle = "rgba(" + r + "," + g + "," + b + "," + dotAlpha + ")";
    for (const dot of dots) {
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, dot.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function step(now) {
    frame = 0;
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    for (const dot of dots) {
      dot.x += dot.vx * dt;
      dot.y += dot.vy * dt;
      if (dot.x < -10) dot.x = width + 10; else if (dot.x > width + 10) dot.x = -10;
      if (dot.y < -10) dot.y = height + 10; else if (dot.y > height + 10) dot.y = -10;
    }
    draw();
    run();
  }

  function run() {
    if (frame || still.matches || document.hidden) return;
    frame = requestAnimationFrame(step);
  }

  function restart() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    last = performance.now();
    run();
  }

  let timer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(resize, 120);
  });
  document.addEventListener("visibilitychange", restart);
  if (still.addEventListener) still.addEventListener("change", () => { draw(); restart(); });
  // Hell/Dunkel oder Theme-Farben ändern sich zur Laufzeit (Umschalter, Systemeinstellung, HA-Theme).
  new MutationObserver(() => { readColours(); draw(); }).observe(root, { attributes: true, attributeFilter: ["data-theme", "style", "class"] });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTimeout(() => { readColours(); draw(); }, 50));

  readColours();
  resize();
  restart();
})();
