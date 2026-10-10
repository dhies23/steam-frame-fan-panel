/* sf_fan_qam.js — Steam Frame quick-access-menu "风扇" tab.
 *
 * Injected into the Steam GamepadUI quick-access-menu popup
 * (vrOverlayKey valve.steam.gamepadui.barpopup) by sf-fan-qamd.
 *
 * Adds a fan tab next to the "?" help tab and renders a panel with live
 * fan RPM / duty cycle and board temperatures plus a speed slider.
 *
 * Styling comes from cloning real QAM rows (label+toggle row, slider row,
 * section header), so the panel is pixel-identical to the stock menus and
 * survives Valve rehashing class names: nothing here depends on a hashed
 * class name.
 */
(function () {
  'use strict';

  var V = 3;
  var prev = window.__SF_FAN__;
  // The daemon only injects when the script hash changed, so always take over.
  if (prev && prev.teardown) { try { prev.teardown(); } catch (e) {} }

  var TAB_ID = 'sf_fan_tab';
  var PANEL_ID = 'sf_fan_panel';
  var BODY_ID = 'sf_fan_body';
  var TAB_LABEL = '风扇';
  var PANEL_TITLE = '风扇';
  var CACHE_KEY = 'sf_fan_tpl_v3';

  /* ------------------------------------------------------------------ */
  /* icons                                                               */
  /* ------------------------------------------------------------------ */

  function svg(inner, vb) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + (vb || '0 0 36 36') +
      '" fill="none" width="100%" height="100%">' + inner + '</svg>';
  }

  // three-blade fan, sized to sit like the stock tab icons
  var ICON_FAN = svg(
    '<g fill="currentColor" transform="translate(18 18) scale(1.32) translate(-18 -18)">' +
    '<path d="M17.4 16.1c-2.2-1.5-3.9-3.6-3.9-5.9 0-2.4 1.6-4.2 3.6-4.2 2.5 0 4.5 2.7 4.5 6.1 0 2.1-1.4 3.9-4.2 4z"/>' +
    '<path d="M17.4 16.1c-2.2-1.5-3.9-3.6-3.9-5.9 0-2.4 1.6-4.2 3.6-4.2 2.5 0 4.5 2.7 4.5 6.1 0 2.1-1.4 3.9-4.2 4z" transform="rotate(120 18 18)"/>' +
    '<path d="M17.4 16.1c-2.2-1.5-3.9-3.6-3.9-5.9 0-2.4 1.6-4.2 3.6-4.2 2.5 0 4.5 2.7 4.5 6.1 0 2.1-1.4 3.9-4.2 4z" transform="rotate(240 18 18)"/>' +
    '<circle cx="18" cy="18" r="3.1"/>' +
    '</g>');

  // circular arrows = automatic
  var ICON_AUTO = svg(
    '<g fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round">' +
    '<path d="M8.5 15.5a9.5 9.5 0 0 1 15.6-4.2"/>' +
    '<path d="M27.5 20.5a9.5 9.5 0 0 1-15.6 4.2"/>' +
    '</g>' +
    '<g fill="currentColor">' +
    '<path d="M25.6 4.9l4.6 6.9-8.1 1.2z"/>' +
    '<path d="M10.4 31.1L5.8 24.2l8.1-1.2z"/>' +
    '</g>');

  // gauge = rpm
  var ICON_GAUGE = svg(
    '<g fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round">' +
    '<path d="M7 25.5a11.5 11.5 0 1 1 22 0"/>' +
    '</g>' +
    '<g fill="currentColor">' +
    '<path d="M17.3 20.2l6.4-6.1 1.9 2-6.4 6.1a3 3 0 1 1-1.9-2z"/>' +
    '<circle cx="18" cy="26" r="2.2"/>' +
    '</g>');

  // thermometer
  var ICON_TEMP = svg(
    '<g fill="currentColor">' +
    '<path d="M20.5 20.9V9a2.5 2.5 0 0 0-5 0v11.9a5.5 5.5 0 1 0 5 0zM18 28.5a2.5 2.5 0 0 1-1.5-4.5v-13h3v13A2.5 2.5 0 0 1 18 28.5z"/>' +
    '<rect x="17" y="13" width="2" height="9" rx="1"/>' +
    '</g>');

  var TEMP_ROWS = [
    { key: 'soc', label: '核心 SoC' },
    { key: 'cpu', label: 'CPU' },
    { key: 'gpu', label: 'GPU' },
    { key: 'ddr', label: '内存' },
    { key: 'heatsink', label: '散热片' },
    { key: 'fan', label: '风扇口' }
  ];

  var state = {
    rpm: null, pwm: null, mode: 'auto', maxTemp: null,
    temps: [], error: null
  };

  var ui = null;
  var tpl = null;
  var isActive = false;
  var dragging = false;
  var observer = null;
  var scheduled = false;
  var qamSeenAt = 0;
  var cleanups = [];
  var harvesting = false;
  var harvestAfter = 0;

  /* The daemon pushes a state snapshot once a second, so anything the user
   * just did has to survive one or two pushes before the hardware echo
   * arrives -- otherwise the control visibly snaps back a moment later. */
  var PENDING_MS = 2500;
  var pendingPwm = null, pendingPwmAt = 0;
  var pendingMode = null, pendingModeAt = 0;
  var lastFlip = 0;

  /* The delta fan stalls below ~20 % duty (the stock controller's own floor is
   * 30 %). Never command less than this: a collapsed/hidden slider must not be
   * readable as "0 %", which used to stop the fan. */
  var MIN_PWM = 20;
  var MAX_PWM = 100;

  var dbg = {
    down: 0, move: 0, up: 0, upOffTarget: 0, sent: 0, ignored: 0, flips: 0,
    flipsSkipped: 0, clicks: 0, lastErr: null
  };

  function log() {
    try {
      console.log.apply(console, ['[sf-fan]'].concat(
        Array.prototype.slice.call(arguments)));
    } catch (e) {}
  }

  function send(obj) {
    try {
      if (typeof window.__sfFanSend === 'function') {
        window.__sfFanSend(JSON.stringify(obj));
        dbg.sent++;
        return true;
      }
    } catch (e) { dbg.lastErr = String(e); log('send failed', e); }
    return false;
  }

  function setStyle(el, css) {
    if (!el) return;
    el.style.cssText = el.style.cssText + ';' + css;
  }

  /* ------------------------------------------------------------------ */
  /* DOM discovery                                                       */
  /* ------------------------------------------------------------------ */

  function qamRoot() { return document.getElementById('QuickAccess-Menu'); }

  function parts() {
    var root = qamRoot();
    if (!root) return null;
    var tablist = root.querySelector('[role="tablist"]');
    if (!tablist) return null;
    var bodies = [].slice.call(root.querySelectorAll('[id^="quickaccess_content_"]'));
    if (!bodies.length) return null;
    var wrappers = bodies.map(function (b) { return b.parentElement; });
    var scroll = wrappers[0].parentElement;
    if (!scroll) return null;
    return { root: root, tablist: tablist, bodies: bodies,
             wrappers: wrappers, scroll: scroll };
  }

  function rendered(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function activeWrapper(p) {
    for (var i = 0; i < p.wrappers.length; i++) {
      if (rendered(p.wrappers[i])) return p.wrappers[i];
    }
    return null;
  }

  function findRow(scope, probe) {
    var rows = [].slice.call(scope.children);
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].querySelector(probe)) return rows[i];
    }
    return null;
  }

  function findSection(body, probe) {
    var secs = [].slice.call(body.children);
    for (var i = 0; i < secs.length; i++) {
      if (secs[i].querySelector(probe)) return secs[i];
    }
    return null;
  }

  function classList(el) {
    return String((el && el.className) || '').split(/\s+/).filter(Boolean);
  }

  function mine(el) {
    return !!(el && el.closest && el.closest('#' + PANEL_ID));
  }

  /* A stock toggle shows its state purely through one extra class on the
   * checkbox element: the knob only slides and the track only turns blue while
   * that class is present (the stylesheet has no [aria-checked] rule at all).
   * A clone therefore keeps whatever state it was cloned in forever -- which is
   * why setting aria-checked made the switch look completely dead.
   *
   * Harvest that class by diffing a checked against an unchecked toggle, and
   * also keep one clone of each state as a fallback for tabs that only happen
   * to show toggles of a single state. */
  function harvestToggleStates(scope) {
    var boxes = [].slice.call(
      (scope || document).querySelectorAll('[role="checkbox"]'))
      .filter(function (b) { return !mine(b); });
    var on = null, off = null;
    for (var i = 0; i < boxes.length; i++) {
      var checked = boxes[i].getAttribute('aria-checked') === 'true';
      if (checked && !on) on = boxes[i];
      if (!checked && !off) off = boxes[i];
      if (on && off) break;
    }
    if (!on && !off) return null;
    var extra = null;
    if (on && off) {
      var offSet = classList(off);
      var diff = classList(on).filter(function (c) {
        return c !== 'gpfocus' && offSet.indexOf(c) < 0;
      });
      if (diff.length) extra = diff.join(' ');
    }
    return {
      toggleOnExtra: extra,
      toggleOnHTML: on ? on.outerHTML : null,
      toggleOffHTML: off ? off.outerHTML : null
    };
  }

  /* Clone one real slider row, one real toggle row and one section header
   * out of whichever QAM tab is currently rendered. */
  function grabTemplates(p) {
    var w = activeWrapper(p);
    if (!w) return null;
    var body = w.querySelector('[id^="quickaccess_content_"]');
    if (!body) return null;

    var sliderSec = findSection(body, '.SliderControl');
    var toggleSec = findSection(body, '[role="checkbox"]');
    if (!sliderSec || !toggleSec) return null;

    var sliderRow = findRow(sliderSec, '.SliderControl');
    var toggleRow = findRow(toggleSec, '[role="checkbox"]');
    if (!sliderRow || !toggleRow) return null;

    var sliderEl = sliderRow.querySelector('[role="slider"]');
    if (!sliderEl) return null;

    // how a toggle looks in each state (class to flip + a clone of each state)
    var ts = harvestToggleStates(body) || harvestToggleStates(document) || {};

    // the extra class the wrapper carries while its tab is selected
    var others = p.wrappers.filter(function (x) { return x !== w; });
    var wSet = String(w.className).split(/\s+/);
    var activeExtra = null;
    others.forEach(function (o) {
      var oSet = String(o.className).split(/\s+/);
      var extra = wSet.filter(function (c) { return c && oSet.indexOf(c) < 0; });
      if (extra.length && !activeExtra) activeExtra = extra.join(' ');
    });

    // the extra class a selected tab carries
    var sel = p.tablist.querySelector('[role="tab"][aria-selected="true"]');
    var tabExtra = null;
    if (sel) {
      var selSet = String(sel.className).split(/\s+/);
      [].slice.call(p.tablist.querySelectorAll('[role="tab"]')).forEach(function (t) {
        if (tabExtra || t === sel) return;
        var tSet = String(t.className).split(/\s+/);
        var extra = selSet.filter(function (c) { return c && tSet.indexOf(c) < 0; });
        if (extra.length) tabExtra = extra.join(' ');
      });
    }

    var labelBox = toggleRow.querySelector('[id$="_Label"]');
    var iconHolder = labelBox && labelBox.firstElementChild;

    // Templates are kept as HTML strings so they can also be cached across a
    // client reload (DOM nodes do not survive JSON).
    return {
      wrapperCls: String(w.className).split(/\s+/)
        .filter(function (c) { return c && c !== activeExtra; }).join(' '),
      activeExtra: activeExtra,
      titleCls: (w.firstElementChild || {}).className || '',
      bodyCls: body.className,
      sectionCls: sliderSec.className,
      headerHTML: sliderSec.firstElementChild.outerHTML,
      toggleRowHTML: toggleRow.outerHTML,
      sliderWidgetHTML: sliderEl.outerHTML,
      sliderGroupHTML: sliderEl.parentElement.outerHTML,
      labelHolderCls: labelBox ? labelBox.className : '',
      iconHolderCls: iconHolder ? iconHolder.className : '',
      tabExtra: tabExtra,
      toggleOnExtra: ts.toggleOnExtra || null,
      toggleOnHTML: ts.toggleOnHTML || null,
      toggleOffHTML: ts.toggleOffHTML || null
    };
  }

  /* Valve rehashes class names between client builds, so a cached template is
   * only reusable while its classes still exist in the stylesheets. */
  function selectorKnown(cls) {
    if (!cls) return false;
    var sheets = document.styleSheets;
    for (var i = 0; i < sheets.length; i++) {
      var rules;
      try { rules = sheets[i].cssRules; } catch (e) { continue; }
      if (!rules) continue;
      for (var j = 0; j < rules.length; j++) {
        var sel = rules[j].selectorText;
        if (sel && sel.indexOf(cls) >= 0) return true;
      }
    }
    return false;
  }

  function saveTemplates() {
    if (!tpl) return;
    try {
      var probe = String(tpl.sectionCls || '').split(/\s+/)[0];
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ probe: probe, tpl: tpl }));
    } catch (e) {}
  }

  function loadTemplates() {
    var raw;
    try { raw = sessionStorage.getItem(CACHE_KEY); } catch (e) { return null; }
    if (!raw) return null;
    var obj;
    try { obj = JSON.parse(raw); } catch (e) { return null; }
    if (!obj || !obj.tpl || !obj.probe) return null;
    var t = obj.tpl;
    if (!t.toggleOnExtra && !(t.toggleOnHTML && t.toggleOffHTML)) {
      log('cached templates cannot render toggle states; discarding');
      try { sessionStorage.removeItem(CACHE_KEY); } catch (e) {}
      return null;
    }
    if (!selectorKnown(obj.probe) ||
        (t.toggleOnExtra && !selectorKnown(t.toggleOnExtra))) {
      log('cached templates are from an older client build; discarding');
      try { sessionStorage.removeItem(CACHE_KEY); } catch (e) {}
      return null;
    }
    return obj.tpl;
  }

  function nodeFromHTML(html) {
    var box = document.createElement('div');
    box.innerHTML = html;
    return box.firstElementChild;
  }

  /* ------------------------------------------------------------------ */
  /* row construction                                                    */
  /* ------------------------------------------------------------------ */

  function labelBoxOf(row) {
    return row.querySelector('[id$="_Label"]') || row.querySelector('div > div');
  }

  function setLabel(row, text) {
    var box = labelBoxOf(row);
    if (!box) return null;
    var nodes = [].slice.call(box.childNodes);
    nodes.forEach(function (n) {
      if (n.nodeType === 3 || (n.nodeType === 1 && n.tagName !== 'DIV')) {
        box.removeChild(n);
      }
    });
    box.appendChild(document.createTextNode(text));
    return box;
  }

  function setIcon(row, svgText) {
    var box = labelBoxOf(row);
    if (!box) return;
    var holder = box.firstElementChild;
    if (holder && holder.querySelector('svg')) holder.innerHTML = svgText;
  }

  function newRow() {
    return nodeFromHTML(tpl.toggleRowHTML);
  }

  function controlWrapper(row) {
    // the row-inner's last element child is the control slot
    var inner = row.children[0];
    if (!inner) return null;
    return inner.lastElementChild;
  }

  function valueRow(label, icon, initial) {
    var row = newRow();
    setLabel(row, label);
    setIcon(row, icon);
    var cw = controlWrapper(row);
    var v = document.createElement('div');
    v.textContent = initial;
    v.style.cssText = 'font-size:14px;line-height:20px;font-weight:600;' +
      'color:#fff;font-variant-numeric:tabular-nums;white-space:nowrap;' +
      'text-align:right;';
    if (cw) {
      cw.innerHTML = '';
      cw.style.cssText = 'flex:0 0 auto;min-width:0;display:flex;' +
        'align-items:center;justify-content:flex-end;';
      cw.appendChild(v);
    }
    row.__value = v;
    return row;
  }

  /* The stock switch is drawn entirely by CSS: the knob slides via a transform
   * and the track turns blue via a ::before that slides in. Both are animated
   * with `transition: transform .2s`, and a transition only advances while the
   * page is actually being composited -- the QAM popup is throttled whenever
   * nobody is looking at it (and in VR whenever the overlay is not up), and
   * then the transition sits at "running" forever holding the *old* value.
   * The switch then looks like it never reacts to a click.
   *
   * So the state is also pinned directly: the transition is switched off and
   * the two visual properties are written inline, which the style engine
   * applies on the spot no matter what the timeline is doing. The colours are
   * the ones measured off a real switch, so it still looks stock. */
  var LOOK_STYLE_ID = 'sf_fan_look_css';
  var KNOB_ON = 'translateX(16px)';
  var KNOB_OFF = 'translateX(0px)';
  var RAIL_ON = 'rgb(26, 159, 255)';
  var RAIL_OFF = 'hsla(0, 0%, 100%, 0.15)';

  function ensureLookStyle() {
    if (document.getElementById(LOOK_STYLE_ID)) return;
    var st = document.createElement('style');
    st.id = LOOK_STYLE_ID;
    /* the blue fill is painted by the rail's ::before; we paint the rail
     * itself instead, so drop the pseudo-element or the two would fight */
    st.textContent = '#' + PANEL_ID +
      ' [role="checkbox"] > div:first-child::before{content:none !important}';
    (document.head || document.documentElement).appendChild(st);
  }

  function pinToggleLook(cb, on) {
    if (!cb || !cb.children || cb.children.length !== 2) return;
    ensureLookStyle();
    var rail = cb.children[0], knob = cb.children[1];
    rail.style.transition = 'none';
    rail.style.background = on ? RAIL_ON : RAIL_OFF;
    knob.style.transition = 'none';
    knob.style.transform = on ? KNOB_ON : KNOB_OFF;
  }

  /* Put the checkbox into the requested visual state. Flips the one class the
   * stylesheet keys off (so anything else keyed off it still works), falls back
   * to swapping in a clone of a real toggle already in that state, and pins the
   * two properties that carry the look either way. */
  function applyToggleLook(cb, on) {
    if (!cb || !tpl) return cb;
    var want = on ? '1' : '0';
    if (cb.getAttribute('data-sf-state') === want) {
      pinToggleLook(cb, on);
      return cb;
    }

    if (tpl.toggleOnExtra) {
      var cls = classList(cb).filter(function (c) { return c !== tpl.toggleOnExtra; });
      if (on) cls.push(tpl.toggleOnExtra);
      cb.className = cls.join(' ');
      cb.setAttribute('data-sf-state', want);
      cb.setAttribute('aria-checked', on ? 'true' : 'false');
      pinToggleLook(cb, on);
      return cb;
    }

    var html = on ? tpl.toggleOnHTML : tpl.toggleOffHTML;
    if (!html) {
      // no way to change the look yet; keep the state marked as unknown so a
      // later render (once the templates are complete) still fixes it up
      cb.setAttribute('aria-checked', on ? 'true' : 'false');
      pinToggleLook(cb, on);
      return cb;
    }
    var fresh = nodeFromHTML(html);
    if (!fresh) return cb;
    fresh.setAttribute('data-sf-state', want);
    fresh.setAttribute('aria-checked', on ? 'true' : 'false');
    fresh.removeAttribute('aria-labelledby');
    var label = cb.getAttribute('aria-label');
    if (label) fresh.setAttribute('aria-label', label);
    if (cb.parentNode) cb.parentNode.replaceChild(fresh, cb);
    pinToggleLook(fresh, on);
    if (ui) ui.checkbox = fresh;
    return fresh;
  }

  function toggleRow(label, icon) {
    var row = newRow();
    setLabel(row, label);
    setIcon(row, icon);
    var cb = row.querySelector('[role="checkbox"]');
    if (cb) {
      cb.removeAttribute('aria-labelledby');
      cb.setAttribute('aria-label', label);
      cb = applyToggleLook(cb, state.mode === 'auto') || cb;
    }
    row.__cb = cb;
    return row;
  }

  /* A stock slider carries these inline custom properties; without them the
   * fill bar and handle maths resolve to nothing. The "default value"
   * gradient classes are stripped: we have no default marker. */
  var SLIDER_DEFAULT_CLASSES = [
    'BKyENCj-EIOyULNJlDOtz',      // has a default value
    '_3mRyvMGiDLM0201gdyBNxA',    // default > current
    '_2KP6TN1CqkX-HgbPjfINAJ'     // default < current
  ];

  function setSliderVars(el, pct) {
    if (!el) return;
    var v = Math.max(0, Math.min(100, pct)) / 100;
    el.style.setProperty('--normalized-slider-value', String(v));
    el.style.setProperty('--normalized-slider-default-value', String(v));
    el.style.setProperty('--normalized-slider-origin', '0');
    el.style.setProperty('--slider-extra-notch-padding', '0px');
    el.style.setProperty('--default-value-track-color', '#b0deff');
    el.setAttribute('aria-valuenow', String(Math.round(pct)));
    el.setAttribute('aria-valuetext', String(Math.round(pct)));
  }

  function sliderRow(label, icon) {
    var row = newRow();
    setLabel(row, label);
    setIcon(row, icon);
    var cw = controlWrapper(row);
    if (!cw) return row;
    cw.innerHTML = '';
    cw.style.cssText = 'flex:1 1 auto;min-width:0;display:flex;' +
      'align-items:center;margin-left:12px;';

    var widget = nodeFromHTML(tpl.sliderWidgetHTML);
    widget.setAttribute('aria-label', label);
    widget.removeAttribute('aria-labelledby');
    widget.className = String(widget.className).split(/\s+/)
      .filter(function (c) { return c && SLIDER_DEFAULT_CLASSES.indexOf(c) < 0; })
      .join(' ');
    widget.style.cssText = 'flex:1 1 auto;min-width:0;width:100%;';
    setSliderVars(widget, 0);

    // wrap so the slider stretches like the stock brightness/volume rows
    var holder = nodeFromHTML(tpl.sliderGroupHTML);  // role=button group
    holder.innerHTML = '';
    holder.setAttribute('aria-label', label);
    holder.style.cssText = 'flex:1 1 auto;min-width:0;display:flex;' +
      'align-items:center;padding:0;';
    holder.appendChild(widget);
    cw.appendChild(holder);

    row.__slider = widget;
    return row;
  }

  function section(label) {
    var sec = document.createElement('div');
    sec.className = tpl.sectionCls;
    var head = nodeFromHTML(tpl.headerHTML);
    var t = head.querySelector('div');
    if (t) t.textContent = label;
    sec.appendChild(head);
    return sec;
  }

  /* ------------------------------------------------------------------ */
  /* panel                                                               */
  /* ------------------------------------------------------------------ */

  function buildPanel(p) {
    var existing = document.getElementById(PANEL_ID);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    var wrap = document.createElement('div');
    wrap.id = PANEL_ID;
    wrap.className = tpl.wrapperCls;
    wrap.style.display = 'none';
    var title = document.createElement('div');
    title.className = tpl.titleCls;
    title.textContent = PANEL_TITLE;

    var body = document.createElement('div');
    body.id = BODY_ID;
    body.className = tpl.bodyCls;

    /* 风扇控制 */
    var s1 = section('风扇控制');
    var sRow = sliderRow('风扇转速', ICON_FAN);
    var aRow = toggleRow('自动温控', ICON_AUTO);
    var rRow = valueRow('实时转速', ICON_GAUGE, '-- RPM');
    var dRow = valueRow('当前占空比', ICON_GAUGE, '-- %');
    s1.appendChild(sRow);
    s1.appendChild(aRow);
    s1.appendChild(rRow);
    s1.appendChild(dRow);

    /* 温度 */
    var s2 = section('温度');
    var tempRows = {};
    TEMP_ROWS.forEach(function (t) {
      var r = valueRow(t.label, ICON_TEMP, '--');
      tempRows[t.key] = r;
      s2.appendChild(r);
    });

    var note = document.createElement('div');
    note.style.cssText = 'padding:0 16px;margin:4px 0 24px;font-size:12px;' +
      'line-height:16px;color:rgba(255,255,255,0.4);';
    note.textContent = '手动转速会暂停系统自动温控；温度过高时自动恢复。';

    body.appendChild(s1);
    body.appendChild(s2);
    body.appendChild(note);
    wrap.appendChild(title);
    wrap.appendChild(body);
    p.scroll.appendChild(wrap);

    ui = {
      wrap: wrap, body: body, note: note,
      sliderRow: sRow, autoRow: aRow, rpmRow: rRow, pwmRow: dRow,
      tempRows: tempRows,
      slider: sRow.__slider, checkbox: aRow.__cb, tab: null
    };

    hookSlider();
    hookToggle();
    return true;
  }

  /* ------------------------------------------------------------------ */
  /* tab                                                                 */
  /* ------------------------------------------------------------------ */

  function buildTab(p) {
    if (document.getElementById(TAB_ID)) return true;
    var tabs = [].slice.call(p.tablist.querySelectorAll('[role="tab"]'));
    if (!tabs.length) return false;
    var anchor = tabs[tabs.length - 1];          // the "?" help tab
    var tab = anchor.cloneNode(true);
    tab.id = TAB_ID;
    tab.removeAttribute('aria-labelledby');
    tab.setAttribute('aria-label', TAB_LABEL);
    tab.setAttribute('aria-controls', BODY_ID);
    tab.setAttribute('aria-selected', 'false');
    var s = tab.querySelector('svg');
    if (s) s.outerHTML = ICON_FAN;

    tab.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      activate(true);
    }, true);
    tab.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        e.stopPropagation();
        activate(true);
      }
    }, true);

    anchor.parentNode.insertBefore(tab, anchor.nextSibling);
    if (ui) ui.tab = tab;
    log('tab added');
    return true;
  }

  /* ------------------------------------------------------------------ */
  /* activation                                                          */
  /* ------------------------------------------------------------------ */

  function stockTabSelected(p) {
    var tabs = [].slice.call(p.tablist.querySelectorAll('[role="tab"]'));
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].id === TAB_ID) continue;
      if (tabs[i].getAttribute('aria-selected') === 'true') return true;
    }
    return false;
  }

  function applyActive(p, on) {
    isActive = on;
    var panel = document.getElementById(PANEL_ID);
    var tab = document.getElementById(TAB_ID);
    var extra = tpl && tpl.tabExtra;
    var wExtra = tpl && tpl.activeExtra;

    p.wrappers.forEach(function (w) {
      if (on) {
        if (w.style.display !== 'none') w.style.display = 'none';
      } else if (w.style.display === 'none') {
        w.style.display = '';
      }
    });

    if (panel) {
      // the stock wrapper class is display:none; it only becomes visible with
      // the "active tab" class. Set both, so this works even if the class
      // name changes between client builds.
      panel.style.display = on ? 'flex' : 'none';
      var pc = tpl ? tpl.wrapperCls.split(/\s+/) : [];
      if (on && wExtra) pc = pc.concat(wExtra.split(/\s+/));
      panel.className = pc.filter(Boolean).join(' ');
    }

    if (tab) {
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      var cls = String(tab.className).split(/\s+/).filter(function (c) {
        return c && c !== extra;
      });
      if (on && extra) cls.push(extra);
      var next = cls.join(' ');
      if (next !== tab.className) tab.className = next;
    }

    if (on) {
      [].slice.call(p.tablist.querySelectorAll('[role="tab"]')).forEach(function (t) {
        if (t.id === TAB_ID) return;
        t.setAttribute('aria-selected', 'false');
        if (extra) {
          var c = String(t.className).split(/\s+/).filter(function (x) {
            return x && x !== extra;
          }).join(' ');
          if (c !== t.className) t.className = c;
        }
      });
      render();
    }
  }

  function activate(on) {
    var p = parts();
    if (!p) return;
    if (!tpl) tpl = grabTemplates(p);
    if (!on) {
      applyActive(p, false);
      return;
    }
    if (!tpl) {
      // No row templates yet (the QAM is showing a tab without any). Stay
      // "active" and finish once the harvest has produced templates.
      isActive = true;
      harvest(p, function (ok) {
        var p2 = parts();
        if (!p2 || !ok) return;
        if (!document.getElementById(PANEL_ID)) buildPanel(p2);
        applyActive(p2, true);
      });
      return;
    }
    if (!document.getElementById(PANEL_ID)) buildPanel(p);
    applyActive(p, true);
  }

  /* ------------------------------------------------------------------ */
  /* controls                                                            */
  /* ------------------------------------------------------------------ */

  /* The panel is rebuilt whenever the QAM re-renders, and Steam's own slider
   * swaps its DOM node while you drag it, so never hold on to a cached node:
   * always look the live one up. */
  function liveSlider() {
    return document.querySelector('#' + PANEL_ID + ' [role="slider"]') || null;
  }

  function liveCheckbox() {
    return document.querySelector('#' + PANEL_ID + ' [role="checkbox"]') || null;
  }

  function sliderRowOf(node) {
    return (node && node.closest && node.closest('[role="button"]')) || node;
  }

  function setSliderValue(pct) {
    var el = liveSlider();
    if (!el) return;
    setSliderVars(el, pct);
    if (ui && ui.pwmRow && ui.pwmRow.__value) {
      ui.pwmRow.__value.textContent = Math.round(pct) + ' %';
    }
  }

  function notePwm(v) {
    pendingPwm = v;
    pendingPwmAt = Date.now();
    state.pwm = v;
  }

  function hookSlider() {
    if (!ui.slider) return;

    function valueAt(ev) {
      var node = liveSlider();
      if (!node) { dbg.ignored++; return null; }
      var r = node.getBoundingClientRect();
      // a collapsed slider (panel hidden, mid-rebuild) must never read as 0 %
      if (!(r.width > 0)) { dbg.ignored++; return null; }
      var f = (ev.clientX - r.left) / r.width;
      if (!isFinite(f)) { dbg.ignored++; return null; }
      f = Math.max(0, Math.min(1, f));
      return Math.round(MIN_PWM + f * (MAX_PWM - MIN_PWM));
    }

    function apply(ev, force) {
      var v = valueAt(ev);
      if (v === null) return;
      if (!force && v === state.pwm) return;
      setSliderValue(v);
      notePwm(v);
      send({ cmd: 'set_pwm', value: v });
    }

    /* Is this event happening on the slider (or its row)? */
    function onSlider(ev) {
      var node = liveSlider();
      if (!node) return false;
      var row = sliderRowOf(node);
      var t = ev.target;
      return !!(t && (t === node || (node.contains && node.contains(t)) ||
                      (row && row.contains && row.contains(t))));
    }

    function down(ev) {
      if (ev.button !== undefined && ev.button !== 0) return;
      var node = liveSlider();
      if (!node) return;
      if (!onSlider(ev)) return;
      ev.preventDefault(); ev.stopPropagation();
      dbg.down++;
      dragging = true;
      apply(ev, true);
    }
    function move(ev) {
      // a move with no button held means the pointerup was missed: stop
      if (dragging && ev.buttons === 0) { dragging = false; return; }
      if (!dragging) return;
      ev.preventDefault(); ev.stopPropagation();
      dbg.move++;
      apply(ev, false);
    }
    function up(ev) {
      if (!dragging) return;
      dragging = false;
      /* Only a release that is still over the slider sets a value. Without
       * this, a click on the toggle (or anywhere else in the panel) after a
       * drag whose pointerup we never saw would be read as "the user dragged
       * the slider to that x" -- the panel then commanded a fresh duty cycle
       * right after the toggle had switched to automatic, and the switch
       * looked like it did nothing. */
      if (!onSlider(ev)) { dbg.upOffTarget++; return; }
      dbg.up++;
      apply(ev, true);
    }
    function cancel() { dragging = false; }

    /* Listening on window in the capture phase keeps the gesture alive even if
     * Steam's React tree replaces the slider node halfway through the drag. */
    window.addEventListener('pointerdown', down, true);
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
    window.addEventListener('pointercancel', cancel, true);
    window.addEventListener('blur', cancel, true);
    cleanups.push(function () {
      window.removeEventListener('pointerdown', down, true);
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', cancel, true);
      window.removeEventListener('blur', cancel, true);
    });

    window.addEventListener('keydown', function (ev) {
      var node = liveSlider();
      if (!node) return;
      var t = ev.target;
      if (!(t && (t === node || (node.contains && node.contains(t))))) return;
      var cur = state.pwm === null || state.pwm === undefined
        ? MIN_PWM : state.pwm;
      var step = ev.shiftKey ? 1 : 5;
      var v = null;
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowUp') v = cur + step;
      if (ev.key === 'ArrowLeft' || ev.key === 'ArrowDown') v = cur - step;
      if (v === null) return;
      v = Math.max(MIN_PWM, Math.min(MAX_PWM, v));
      ev.preventDefault(); ev.stopPropagation();
      setSliderValue(v);
      notePwm(v);
      send({ cmd: 'set_pwm', value: v });
    }, true);
  }

  /* Switch between the two modes. Optimistic: the daemon polls several times a
   * second, so waiting for its echo makes the switch feel dead and would send
   * the next click the wrong way. */
  function setMode(next, quiet) {
    if (next !== 'auto' && next !== 'manual') return false;
    if (state.mode === next && !quiet) return false;
    var now = Date.now();
    state.mode = next;
    pendingMode = next;
    pendingModeAt = now;
    if (next === 'manual' && (state.pwm === null || state.pwm === undefined)) {
      state.pwm = MIN_PWM;
      pendingPwm = MIN_PWM;
      pendingPwmAt = now;
    }
    /* Send first. The command is what the user asked for; if drawing the new
     * state ever throws, the request must still reach the daemon. */
    send({ cmd: next === 'auto' ? 'set_auto' : 'set_manual' });
    try { render(); } catch (e) { dbg.lastErr = String(e); log('render error', e); }
    return true;
  }

  /* The element that represents the toggle, for events that may land on the
   * knob or the track inside it rather than on the checkbox itself. */
  function toggleTarget(ev) {
    var cb = liveCheckbox();
    if (!cb || !ev || !ev.target) return null;
    var t = ev.target;
    if (t === cb) return cb;
    if (cb.contains && cb.contains(t)) return cb;
    if (t.closest) {
      var found = t.closest('[role="checkbox"]');
      if (found && found === cb) return cb;
    }
    return null;
  }

  function hookToggle() {
    var sawDown = 0;

    function flip(ev) {
      var cb = toggleTarget(ev);
      if (!cb) return;
      if (ev.type === 'click') {
        /* A pointerdown we already handled is followed by a click for the same
         * gesture; acting on both would toggle twice and land back where the
         * user started. */
        if (Date.now() - sawDown < 800) { dbg.flipsSkipped++; return; }
        dbg.clicks++;
      } else {
        if (ev.button !== undefined && ev.button !== 0) return;
        sawDown = Date.now();
      }
      if (ev.preventDefault) ev.preventDefault();
      if (ev.stopPropagation) ev.stopPropagation();
      var now = Date.now();
      if (now - lastFlip < 250) { dbg.flipsSkipped++; return; }
      lastFlip = now;
      dbg.flips++;
      /* Trust what is on screen. `state.mode` can be a step behind (the daemon
       * pushes four times a second) or ahead (a push that was in flight when
       * the user clicked), and the visible knob is what the user is reacting
       * to, so flipping away from that is never surprising. */
      var shown = cb.getAttribute('data-sf-state');
      var on = shown === '1' ? true
             : (shown === '0' ? false : state.mode === 'auto');
      setMode(on ? 'manual' : 'auto');
    }

    /* pointerdown gives the snappiest response; click is the safety net for
     * input paths that deliver a click without a preceding pointer event. */
    window.addEventListener('pointerdown', flip, true);
    window.addEventListener('click', flip, true);
    window.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
      flip(ev);
    }, true);
    cleanups.push(function () {
      window.removeEventListener('pointerdown', flip, true);
      window.removeEventListener('click', flip, true);
    });
  }

  /* ------------------------------------------------------------------ */
  /* render                                                              */
  /* ------------------------------------------------------------------ */

  function fmtTemp(v) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    return v.toFixed(1) + ' °C';
  }

  function render() {
    if (!ui) return;
    if (ui.rpmRow && ui.rpmRow.__value) {
      ui.rpmRow.__value.textContent = (state.rpm === null || state.rpm === undefined)
        ? '-- RPM' : Math.round(state.rpm) + ' RPM';
    }
    if (ui.pwmRow && ui.pwmRow.__value && !dragging) {
      ui.pwmRow.__value.textContent = (state.pwm === null || state.pwm === undefined)
        ? '-- %' : Math.round(state.pwm) + ' %';
    }
    if (ui.slider && !dragging && state.pwm !== null && state.pwm !== undefined) {
      setSliderVars(liveSlider(), state.pwm);
    }
    var cb = liveCheckbox();
    if (cb) cb = applyToggleLook(cb, state.mode === 'auto') || cb;
    if (cb && ui) ui.checkbox = cb;
    (state.temps || []).forEach(function (t) {
      var row = ui.tempRows[t.key];
      if (row && row.__value) row.__value.textContent = fmtTemp(t.c);
    });
    if (ui.note) {
      if (state.error) {
        ui.note.textContent = state.error;
        ui.note.style.color = '#ffb340';
      } else {
        ui.note.textContent = '手动转速会暂停系统自动温控；温度过高时自动恢复。';
        ui.note.style.color = 'rgba(255,255,255,0.4)';
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /* sync                                                                */
  /* ------------------------------------------------------------------ */

  function sync() {
    var p = parts();
    if (!p) { qamSeenAt = 0; return; }

    if (!document.getElementById(TAB_ID)) buildTab(p);

    if (!tpl) {
      tpl = grabTemplates(p);
      if (tpl) saveTemplates();
    }
    if (!tpl && !harvesting && Date.now() >= harvestAfter) {
      // The QAM is showing a tab that renders no slider/toggle rows, so there
      // is nothing to clone yet: briefly borrow the settings tab.
      harvest(p, function (ok) {
        if (!ok) return;
        var p2 = parts();
        if (p2 && !document.getElementById(PANEL_ID)) buildPanel(p2);
      });
    }
    if (tpl && !document.getElementById(PANEL_ID)) buildPanel(p);

    if (isActive) {
      if (harvesting) return;              // harvest owns the tab selection
      if (stockTabSelected(p)) {
        log('stock tab selected -> deactivate');
        applyActive(p, false);
        return;
      }
      if (!document.getElementById(PANEL_ID) && tpl) buildPanel(p);
      var panel = document.getElementById(PANEL_ID);
      if (panel && panel.style.display !== 'flex') {
        panel.style.display = 'flex';
        if (tpl && tpl.activeExtra &&
            String(panel.className).indexOf(tpl.activeExtra) < 0) {
          panel.className = String(panel.className) + ' ' + tpl.activeExtra;
        }
      }
      p.wrappers.forEach(function (w) {
        if (w.style.display !== 'none') w.style.display = 'none';
      });
      var tab = document.getElementById(TAB_ID);
      if (tab && tpl && tpl.tabExtra &&
          String(tab.className).indexOf(tpl.tabExtra) < 0) {
        tab.className = String(tab.className) + ' ' + tpl.tabExtra;
      }
      if (tab && tab.getAttribute('aria-selected') !== 'true') {
        tab.setAttribute('aria-selected', 'true');
      }
      render();
    }
  }

  /* Valve renders a tab's rows only while that tab is selected, so when the
   * QAM is sitting on a tab with no slider/toggle rows (notifications, help)
   * there is nothing to clone. Borrow a tab that does have them, wait for
   * React to render it, harvest, then put the user's tab back. */
  function harvest(p, done) {
    if (harvesting) return;
    var tabs = [].slice.call(p.tablist.querySelectorAll('[role="tab"]'))
      .filter(function (t) { return t.id !== TAB_ID; });
    if (!tabs.length) { if (done) done(false); return; }

    var back = tabs.filter(function (t) {
      return t.getAttribute('aria-selected') === 'true';
    })[0] || null;

    // the settings tab always has both a slider row and a toggle row
    var order = tabs.slice().sort(function (a, b) {
      var ra = /quickaccess_content_4$/.test(a.getAttribute('aria-controls') || '') ? 0 : 1;
      var rb = /quickaccess_content_4$/.test(b.getAttribute('aria-controls') || '') ? 0 : 1;
      return ra - rb;
    });

    harvesting = true;
    log('harvesting row templates');

    var i = 0;
    var waited = 0;
    var STEP = 120;
    var LIMIT = 1600;

    function clickTab(t) {
      try {
        t.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      } catch (e) {}
    }

    function finish(ok) {
      harvesting = false;
      harvestAfter = ok ? 0 : Date.now() + 5000;
      if (ok) saveTemplates();
      var p3 = parts();
      if (p3) {
        if (isActive) {
          var mine = document.getElementById(TAB_ID);
          if (mine) clickTab(mine);
        } else if (back && back.parentNode) {
          clickTab(back);
        }
        if (ok && !document.getElementById(PANEL_ID)) buildPanel(p3);
      }
      log('harvest ->', ok ? 'ok' : 'failed');
      if (done) done(ok);
    }

    function poll() {
      if (!harvesting) return;
      var p2 = parts();
      if (p2) {
        tpl = grabTemplates(p2);
        if (tpl) { finish(true); return; }
      }
      if (waited >= LIMIT) {
        waited = 0;
        i++;
        if (i >= order.length) { finish(false); return; }
        clickTab(order[i]);
      } else {
        waited += STEP;
      }
      setTimeout(poll, STEP);
    }

    clickTab(order[0]);
    setTimeout(poll, STEP);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(function () {
      scheduled = false;
      try { sync(); } catch (e) { log('sync error', e); }
    }, 60);
  }

  function startObserver() {
    if (observer) return;
    observer = new MutationObserver(schedule);
    observer.observe(document.body || document.documentElement,
                     { childList: true, subtree: true });
  }

  /* ------------------------------------------------------------------ */
  /* api                                                                 */
  /* ------------------------------------------------------------------ */

  var API = {
    v: V,
    setState: function (s) {
      if (s) {
        var now = Date.now();
        for (var k in s) {
          if (!Object.prototype.hasOwnProperty.call(s, k)) continue;
          // keep the user's just-made change until the daemon echoes it back
          if (k === 'pwm') {
            if (dragging) continue;
            if (pendingPwm !== null && s.pwm !== pendingPwm &&
                now - pendingPwmAt < PENDING_MS) continue;
            pendingPwm = null;
          }
          if (k === 'mode') {
            if (pendingMode !== null && s.mode !== pendingMode &&
                now - pendingModeAt < PENDING_MS) continue;
            pendingMode = null;
          }
          state[k] = s[k];
        }
      }
      try { render(); } catch (e) { log('render error', e); }
    },
    getState: function () { return state; },
    debug: function () { return dbg; },
    get tpl() { return tpl; },
    setAuto: function () { return setMode('auto'); },
    setManual: function (pwm) {
      setMode('manual', true);
      if (pwm !== undefined && pwm !== null) {
        var v = Math.max(MIN_PWM, Math.min(MAX_PWM, Math.round(pwm)));
        setSliderValue(v);
        notePwm(v);
        send({ cmd: 'set_pwm', value: v });
      }
      return true;
    },
    sync: sync,
    activate: activate,
    ping: function () { return 'pong'; },
    teardown: function () {
      if (observer) { observer.disconnect(); observer = null; }
      cleanups.forEach(function (fn) { try { fn(); } catch (e) {} });
      cleanups = [];
      ['sf_fan_tab', 'sf_fan_panel'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el && el.parentNode) el.parentNode.removeChild(el);
      });
      var look = document.getElementById(LOOK_STYLE_ID);
      if (look && look.parentNode) look.parentNode.removeChild(look);
      var p = parts();
      if (p) {
        p.wrappers.forEach(function (w) { w.style.display = ''; });
      }
      ui = null; tpl = null; isActive = false;
      harvesting = false; harvestAfter = 0;
      // forget the build marker so the daemon knows to re-inject
      try { if (window.__SF_FAN__ === API) window.__SF_FAN__ = null; } catch (e) {}
    }
  };
  window.__SF_FAN__ = API;

  // Reuse the harvested row templates when the page was reloaded but the
  // client build is unchanged, so no tab has to be borrowed for a moment.
  tpl = loadTemplates();

  startObserver();
  sync();
  log('installed v' + V + (tpl ? ' (cached templates)' : ''));
  return 'ok:installed';
})();
