(() => {
  // find a real (stock) slider still in the DOM on another tab
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return 'no qam';
  const sliders = [...root.querySelectorAll('[role="slider"]')]
    .filter(s => !s.closest('#sf_fan_panel'));
  const out = sliders.slice(0, 2).map(s => {
    const cs = getComputedStyle(s);
    const inner = s.querySelector('.SliderControl') || s.firstElementChild;
    const ics = inner ? getComputedStyle(inner) : null;
    const parent = s.parentElement;
    const pcs = getComputedStyle(parent);
    return {
      outer: s.outerHTML.slice(0, 700),
      sliderVars: {
        nsv: cs.getPropertyValue('--normalized-slider-value'),
        nso: cs.getPropertyValue('--normalized-slider-origin'),
        nsdv: cs.getPropertyValue('--normalized-slider-default-value'),
        notch: cs.getPropertyValue('--slider-extra-notch-padding'),
        minw: cs.getPropertyValue('--slider-min-width'),
        handlew: cs.getPropertyValue('--slider-handle-width')
      },
      innerVars: ics ? {
        nsv: ics.getPropertyValue('--normalized-slider-value'),
        nso: ics.getPropertyValue('--normalized-slider-origin'),
        notch: ics.getPropertyValue('--slider-extra-notch-padding'),
        handlew: ics.getPropertyValue('--slider-handle-width')
      } : null,
      parentVars: {
        notch: pcs.getPropertyValue('--slider-extra-notch-padding'),
        minw: pcs.getPropertyValue('--slider-min-width')
      },
      parentCls: parent.className,
      parentOuter: parent.outerHTML.slice(0, 400)
    };
  });
  return JSON.stringify(out, null, 1);
})()
