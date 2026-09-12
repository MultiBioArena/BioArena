import {memo, useEffect, useRef} from 'react';
import './ambientBackdrop.css';

/*! Particle rendering adapted from Magic UI. Copyright (c) Magic UI. MIT license: /licenses/magic-ui.txt */
type Particle = {x:number; y:number; radius:number; alpha:number; speed:number; phase:number};

export const AmbientBackdrop = memo(function AmbientBackdrop(){
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(()=>{
    const element = host.current, surface = canvas.current;
    if(!element || !surface)return;
    const context = surface.getContext('2d');
    if(!context)return;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const compact = matchMedia('(max-width: 700px)');
    let width = 1, height = 1, particles:Particle[] = [];
    let frame = 0, timer:ReturnType<typeof setTimeout>|undefined, last = 0, elapsed = 0;
    let disposed = false, pointerX = 0, pointerY = 0, offsetX = 0, offsetY = 0;
    // Presentation randomness is isolated from every neural and trading random stream.
    let seed = 1717;
    const random = ()=>{seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296};
    const paused = ()=>document.hidden || !!document.fullscreenElement;
    const paint = (dt:number)=>{
      elapsed += dt;
      context.clearRect(0, 0, width, height);
      offsetX += (pointerX - offsetX) * .045;
      offsetY += (pointerY - offsetY) * .045;
      for(const p of particles){
        p.y -= dt * p.speed;
        if(p.y < -8)p.y = height + 8;
        const x = p.x + (reduced.matches ? 0 : Math.sin(elapsed * .12 + p.phase) * 13 + offsetX);
        const y = p.y + (reduced.matches ? 0 : offsetY);
        const edge = Math.max(0, Math.min(1, x / 50, (width - x) / 50, y / 50, (height - y) / 50));
        context.beginPath();
        context.arc(x, y, p.radius, 0, Math.PI * 2);
        context.fillStyle = `rgba(187, 210, 157, ${p.alpha * edge})`;
        context.fill();
      }
    };
    const stop = ()=>{clearTimeout(timer); cancelAnimationFrame(frame); frame = 0; last = 0};
    const draw = (now:number)=>{
      frame = 0;
      if(disposed || paused() || reduced.matches)return;
      const dt = last ? Math.min((now - last) / 1000, .1) : 0;
      last = now;
      paint(dt);
      timer = setTimeout(()=>{frame = requestAnimationFrame(draw)}, 50);
    };
    const refresh = ()=>{
      stop();
      element.dataset.motion = paused() ? 'paused' : reduced.matches ? 'still' : 'active';
      if(!paused())paint(0);
      if(!paused() && !reduced.matches && !disposed)frame = requestAnimationFrame(draw);
    };
    const resize = ()=>{
      const rect = element.getBoundingClientRect();
      width = Math.max(1, rect.width); height = Math.max(1, rect.height);
      const dpr = Math.min(devicePixelRatio || 1, 1.25);
      surface.width = Math.round(width * dpr); surface.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      particles = Array.from({length:compact.matches ? 24 : 64}, ()=>({
        x:random() * width, y:random() * height, radius:.45 + random() * 1.25,
        alpha:.12 + random() * .28, speed:2 + random() * 4, phase:random() * Math.PI * 2,
      }));
      refresh();
    };
    const move = (event:PointerEvent)=>{
      if(reduced.matches || compact.matches || event.pointerType !== 'mouse')return;
      pointerX = (event.clientX / width - .5) * 10;
      pointerY = (event.clientY / height - .5) * 8;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    document.addEventListener('visibilitychange', refresh);
    document.addEventListener('fullscreenchange', refresh);
    window.addEventListener('pointermove', move, {passive:true});
    reduced.addEventListener('change', refresh);
    compact.addEventListener('change', resize);
    resize();
    return()=>{
      disposed = true; stop(); observer.disconnect();
      document.removeEventListener('visibilitychange', refresh);
      document.removeEventListener('fullscreenchange', refresh);
      window.removeEventListener('pointermove', move);
      reduced.removeEventListener('change', refresh);
      compact.removeEventListener('change', resize);
    };
  }, []);

  return <div className="ambient-backdrop" ref={host} aria-hidden="true">
    <div className="ambient-field ambient-field-worm"/>
    <div className="ambient-field ambient-field-fly"/>
    <div className="ambient-field ambient-field-larva"/>
    <div className="ambient-texture"/>
    <canvas ref={canvas}/>
    <div className="ambient-vignette"/>
  </div>;
});
