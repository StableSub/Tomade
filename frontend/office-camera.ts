/** Local office zoom and bounded pointer panning; no account state is changed.
 * Controls use native buttons. Dispose releases listeners and pointer capture.
 */
export function createOfficeCamera(viewport: HTMLElement, controls: HTMLElement) {
  const map = viewport.querySelector<HTMLElement>('.office-map')!;
  const out = controls.querySelector<HTMLButtonElement>('[data-zoom="out"]')!;
  const reset = controls.querySelector<HTMLButtonElement>('[data-zoom="reset"]')!;
  const into = controls.querySelector<HTMLButtonElement>('[data-zoom="in"]')!;
  const events = new AbortController();
  const options = { signal: events.signal };
  let zoom = 1, x = 0, y = 0, enabled = true, dragged = false;
  let pointer: { id: number; x: number; y: number; originX: number; originY: number } | null = null;

  function paint() {
    map.style.setProperty('--office-zoom', String(zoom));
    const maxX = Math.max(0, (map.offsetWidth - viewport.clientWidth) / 2);
    const maxY = Math.max(0, (map.offsetHeight - viewport.clientHeight) / 2);
    x = Math.max(-maxX, Math.min(maxX, x));
    y = Math.max(-maxY, Math.min(maxY, y));
    map.style.transform = zoom === 1 ? '' : `translate(${x}px, ${y}px)`;
    viewport.classList.toggle('is-zoomed', zoom > 1);
    out.disabled = zoom === 1;
    into.disabled = zoom === 3;
    reset.textContent = `${Math.round(zoom * 100)}%`;
    reset.setAttribute('aria-label', `현재 ${Math.round(zoom * 100)}%, 전체 보기로 초기화`);
  }
  function stopDrag() {
    if (pointer && viewport.hasPointerCapture(pointer.id)) viewport.releasePointerCapture(pointer.id);
    pointer = null;
    viewport.classList.remove('is-panning');
  }
  function changeZoom(next: number, anchorX = 0, anchorY = 0) {
    if (!enabled) return;
    stopDrag();
    next = Math.max(1, Math.min(3, next));
    const ratio = next / zoom;
    x = anchorX - (anchorX - x) * ratio;
    y = anchorY - (anchorY - y) * ratio;
    zoom = next;
    paint();
  }
  out.addEventListener('click', () => changeZoom(zoom - .25), options);
  into.addEventListener('click', () => changeZoom(zoom + .25), options);
  reset.addEventListener('click', () => changeZoom(1), options);
  viewport.addEventListener('wheel', event => {
    // Leave browser accessibility zoom (Ctrl/Cmd + wheel) alone.
    if (!enabled || event.ctrlKey || event.metaKey || !event.deltaY) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    changeZoom(zoom + (event.deltaY < 0 ? .25 : -.25),
      event.clientX - rect.left - rect.width / 2, event.clientY - rect.top - rect.height / 2);
  }, { ...options, passive: false });
  viewport.addEventListener('pointerdown', event => {
    if (!enabled || !event.isPrimary || event.button !== 0) return;
    dragged = false;
    if (zoom === 1) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, originX: x, originY: y };
  }, options);
  viewport.addEventListener('pointermove', event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    if (!(event.buttons & 1)) { stopDrag(); return; }
    const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
    if (!dragged && Math.hypot(dx, dy) < 5) return;
    dragged = true;
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add('is-panning');
    x = pointer.originX + dx; y = pointer.originY + dy;
    paint();
  }, options);
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    viewport.addEventListener(type, stopDrag, options);
  }
  viewport.addEventListener('click', event => {
    // Only the click following a drag is swallowed; keyboard activation still works.
    if (dragged && event.detail > 0) { event.preventDefault(); event.stopImmediatePropagation(); }
    dragged = false;
  }, { ...options, capture: true });
  window.addEventListener('blur', stopDrag, options);
  const observer = new ResizeObserver(() => { stopDrag(); paint(); });
  observer.observe(viewport);
  viewport.classList.add('camera-ready');
  paint();
  return {
    setEnabled(value: boolean) {
      stopDrag();
      enabled = value;
      zoom = 1; x = 0; y = 0; dragged = false;
      controls.hidden = !value;
      viewport.classList.toggle('camera-ready', value);
      paint();
    },
    dispose() {
      stopDrag(); events.abort(); observer.disconnect();
      viewport.classList.remove('camera-ready', 'is-zoomed');
      map.style.removeProperty('--office-zoom'); map.style.transform = '';
    },
  };
}
