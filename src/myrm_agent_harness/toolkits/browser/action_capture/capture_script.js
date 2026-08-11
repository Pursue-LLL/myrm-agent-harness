// Browser action capture script, injected into the captured page by
// ActionCaptureEngine. Listens for DOM interactions and reports them through
// the __myrmCaptureCallback bridge (window.__myrmCaptureActive gates emission).
(function() {
  if (window.__myrmActionCapture) return;

  const SENSITIVE_TYPES = new Set(['password', 'credit-card-number', 'cc-csc']);

  // Resolve the innermost event target, piercing open shadow DOM boundaries so
  // selectors target the real element instead of the shadow host.
  function eventTarget(e) {
    if (e && typeof e.composedPath === 'function') {
      const path = e.composedPath();
      if (path && path.length) return path[0];
    }
    return e.target;
  }

  function getSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    if (el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
    if (el.getAttribute('aria-label')) return '[aria-label="' + el.getAttribute('aria-label') + '"]';
    if (el.getAttribute('name')) return el.tagName.toLowerCase() + '[name="' + el.getAttribute('name') + '"]';

    const tag = el.tagName.toLowerCase();
    const parent = el.parentElement;
    if (!parent) return tag;
    const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
    if (siblings.length === 1) return getSelector(parent) + ' > ' + tag;
    const idx = siblings.indexOf(el) + 1;
    return getSelector(parent) + ' > ' + tag + ':nth-child(' + idx + ')';
  }

  function getRole(el) {
    return el.getAttribute('role') || el.tagName.toLowerCase();
  }

  function isSensitive(el) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    return type === 'password' || SENSITIVE_TYPES.has(ac);
  }

  function truncateText(text) {
    const t = (text || '').trim();
    return t.length > 80 ? t.slice(0, 80) + '...' : t;
  }

  function selectLabelText(el) {
    const label = el.closest('label');
    if (!label) return '';
    // A wrapped select contributes its option text to label.textContent — clone
    // and strip the form controls so only the field's wording remains.
    const clone = label.cloneNode(true);
    clone.querySelectorAll('select, input, textarea, button').forEach(n => n.remove());
    return truncateText(clone.textContent);
  }

  function getText(el) {
    const label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (label) return label;
    if (el.tagName === 'SELECT') {
      // A select's textContent concatenates every option label — useless as a
      // field description. Prefer the wrapping/adjacent label, then the label
      // of the currently selected option, so multi-dropdown forms stay
      // disambiguated in the generated skill.
      const labelText = selectLabelText(el);
      if (labelText) return labelText;
      const prev = el.previousElementSibling;
      if (prev && /^(LABEL|SPAN|DIV)$/i.test(prev.tagName)) {
        const t = truncateText(prev.textContent);
        if (t) return t;
      }
      const option = el.selectedOptions[0];
      if (option) return truncateText(option.label || option.textContent || option.value);
      return '';
    }
    return truncateText(el.textContent);
  }

  function emit(action, el, value, modifiers, label) {
    if (!window.__myrmCaptureActive) return;
    window.__myrmCaptureCallback(JSON.stringify({
      action: action,
      selector: getSelector(el),
      value: value || '',
      modifiers: modifiers || [],
      label: label || '',
      url: location.href,
      title: document.title,
      elementText: getText(el),
      elementRole: getRole(el),
      isPassword: isSensitive(el),
      ts: Date.now() / 1000
    }));
  }

  // SPA navigations (history.pushState/replaceState, hash change) do not fire a
  // browser navigation event, so they are reported here and folded on the Python
  // side together with real navigations.
  function emitNavigation(url) {
    if (!window.__myrmCaptureActive) return;
    window.__myrmCaptureCallback(JSON.stringify({
      action: 'navigate',
      selector: '',
      value: url,
      url: url,
      title: document.title,
      elementText: '',
      elementRole: '',
      isPassword: false,
      ts: Date.now() / 1000
    }));
  }

  // ---- Session-based fill capture -----------------------------------------
  // Text input is recorded once at commit time with the final value, so pauses
  // during typing never produce fragmented type steps.
  let fillSession = null;  // { element, baselineValue, lastValue }
  let composing = false;
  const committedValues = new WeakMap();

  function fillableFromTarget(target) {
    if (!target || !target.tagName) return null;
    const tag = target.tagName.toLowerCase();
    if (tag === 'textarea') return target;
    if (tag === 'input') {
      const type = (target.type || '').toLowerCase();
      if (type === 'checkbox' || type === 'radio' || type === 'file' ||
          type === 'button' || type === 'submit' || type === 'reset' || type === 'hidden') {
        return null;
      }
      return target;
    }
    if (target.isContentEditable || target.contentEditable === 'true') return target;
    return null;
  }

  function readFillableValue(el) {
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return el.value || '';
    return (el.textContent || '').trim();
  }

  function syncFillSessionValue(el) {
    if (fillSession && fillSession.element === el) {
      fillSession.lastValue = readFillableValue(el);
    }
  }

  function commitFillSession() {
    if (!fillSession || composing) return;
    const session = fillSession;
    fillSession = null;
    if (session.lastValue === session.baselineValue) return;  // no-op focus
    if (!session.lastValue) return;  // cleared to empty: drop (matches trace-reducer)
    const isPwd = session.element instanceof HTMLInputElement &&
      (session.element.type || '').toLowerCase() === 'password';
    emit('fill', session.element, isPwd ? '***' : session.lastValue);
    committedValues.set(session.element, session.lastValue);
  }

  function ensureFillSession(el) {
    if (fillSession && fillSession.element === el) return;
    if (fillSession) commitFillSession();
    const current = readFillableValue(el);
    fillSession = {
      element: el,
      baselineValue: committedValues.get(el) ?? current,
      lastValue: current,
    };
  }

  function commitOnBlur(el) {
    if (fillSession && fillSession.element === el) commitPendingInput();
  }

  // Commit pending input before any interaction that is not on the same input.
  function commitPendingInput() {
    if (!fillSession) return;
    syncFillSessionValue(fillSession.element);
    commitFillSession();
  }

  // ---- Autocomplete / typeahead option clicks fold into the fill session ----
  function isInputCompletionClick(target) {
    if (!target || !target.closest) return false;
    if (target.closest('[role="option"]') && target.closest('[role="listbox"]')) return true;
    const root = target.closest(
      '[id*="Sug"],[id*="sug"],[class*="suggest"],[class*="autocomplete"],[class*="typeahead"],[data-autocomplete]'
    );
    return !!(root && fillSession && !root.contains(fillSession.element));
  }

  // Clicks on search/chat chrome that only focus the nearby input fold into a
  // fill session instead of producing a click step. Selector list is narrowed to
  // search-style fields so ordinary form submit buttons are never affected.
  function nearbyFillableFromSearchChrome(target) {
    if (!target || !target.closest) return null;
    const container = target.closest(
      '[id*="chat-input"], [id*="search"], [class*="search"], form, [role="search"]'
    );
    if (!container) return null;
    const fillable = container.querySelector(
      'textarea, input[type="search"], input[name="q"], #chat-textarea'
    );
    if (fillable && fillableFromTarget(fillable) &&
        fillable !== target && !fillable.contains(target)) {
      return fillable;
    }
    return null;
  }

  // ---- SPA navigation tracking: pushState/replaceState/hash changes ----
  let lastSpaUrl = location.href;

  function onSpaUrlChange() {
    commitPendingInput();
    const url = location.href;
    if (url !== lastSpaUrl && window.__myrmCaptureActive) {
      lastSpaUrl = url;
      emitNavigation(url);
    }
  }

  // ---- Keyboard-activation dedup: Enter-triggered click is already a press step ----
  let keyboardActivation = null;

  // ---- Hover candidates: a hover that precedes a click on another element is
  // itself a necessary prerequisite (dropdown menus, row-action buttons). It is
  // emitted right before that click and deduplicated per element, so incidental
  // mouse movement never pollutes the trace. ----
  const HOVER_BEFORE_CLICK_MAX_MS = 10000;
  let pendingHover = null;  // { element, recordedAt }
  const emittedHoverElements = new WeakSet();

  function hoverTriggerSignal(el) {
    if (!(el instanceof HTMLElement)) return null;
    if (el.matches('input, textarea, select, option')) return null;
    if (el.disabled || el.hasAttribute('disabled') || el.hasAttribute('inert')) return null;
    const ariaHidden = el.getAttribute('aria-hidden');
    if (ariaHidden && ariaHidden.toLowerCase() === 'true') return null;
    const hasPopup = el.hasAttribute('aria-haspopup');
    const handler = el.hasAttribute('onmouseover') || el.hasAttribute('onmouseenter');
    if (!hasPopup && !handler && getComputedStyle(el).cursor !== 'pointer') return null;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return el;
  }

  document.addEventListener('mouseover', function(e) {
    if (!window.__myrmCaptureActive) return;
    const target = eventTarget(e);
    const hoverEl = target instanceof Element
      ? target.closest('a, button, [role="button"], [role="menuitem"], [role="tab"], [aria-haspopup], [onmouseover], [onmouseenter]')
      : null;
    if (!hoverEl || hoverEl !== hoverTriggerSignal(hoverEl)) return;
    pendingHover = { element: hoverEl, recordedAt: Date.now() };
  }, true);

  // Emit the pending hover step when a click/dblclick/select lands elsewhere,
  // deduplicating so the same trigger is recorded at most once per session.
  function emitHoverBeforeClick(actionTarget) {
    if (!pendingHover) return;
    const hover = pendingHover;
    pendingHover = null;
    if (Date.now() - hover.recordedAt > HOVER_BEFORE_CLICK_MAX_MS) return;
    if (actionTarget && hover.element.contains(actionTarget)) return;
    if (emittedHoverElements.has(hover.element)) return;
    emittedHoverElements.add(hover.element);
    emit('hover', hover.element);
  }

  document.addEventListener('click', function(e) {
    if (e.button !== 0) return;
    const target = eventTarget(e);

    if (e.detail === 0 && keyboardActivation &&
        (Date.now() - keyboardActivation.recordedAt) < 500 &&
        keyboardActivation.target === target) {
      keyboardActivation = null;
      return;
    }
    keyboardActivation = null;

    const el = target && target.closest
      ? target.closest('a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], label')
      : null;
    if (!el) return;

    const fillable = fillableFromTarget(el);
    if (fillable) { ensureFillSession(fillable); return; }

    if (el.tagName.toLowerCase() === 'label' && el.control && fillableFromTarget(el.control)) {
      ensureFillSession(el.control);
      return;
    }

    if (el.tagName.toLowerCase() === 'select') return;  // select is emitted via change

    const nearby = nearbyFillableFromSearchChrome(el);
    if (nearby) { ensureFillSession(nearby); return; }

    if (fillSession && isInputCompletionClick(target)) { commitPendingInput(); return; }

    commitPendingInput();
    emitHoverBeforeClick(el);
    emit('click', el);
  }, true);

  document.addEventListener('dblclick', function(e) {
    commitPendingInput();
    const target = eventTarget(e);
    const el = target && target.closest
      ? target.closest('a, button, input, select, textarea, [role="button"]')
      : null;
    if (el && el.tagName.toLowerCase() !== 'select') {
      emitHoverBeforeClick(el);
      emit('dblclick', el);
    }
  }, true);

  document.addEventListener('change', function(e) {
    const el = eventTarget(e);
    if (!el || !el.tagName) return;
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') {
      commitPendingInput();
      emitHoverBeforeClick(el);
      // Multi-select captures every selected option (value + readable label);
      // single-value selects keep the plain value so the trace stays minimal.
      const options = Array.from(el.selectedOptions || []);
      if (el.multiple && options.length > 1) {
        const values = options.map(o => o.value).join('; ');
        const labels = options.map(o => o.label || o.textContent || o.value).join(', ');
        emit('select', el, values, [], labels);
      } else {
        const option = options[0] || null;
        const value = option ? option.value : el.value;
        const label = option ? (option.label || option.textContent || option.value) : '';
        emit('select', el, value, [], label);
      }
    } else if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
      commitPendingInput();
      emit(el.checked ? 'check' : 'uncheck', el, String(el.checked));
    } else if (tag === 'input' && el.type === 'file') {
      commitPendingInput();
      const names = Array.from(el.files || []).map(f => f.name).join(', ');
      emit('upload', el, names);
    }
  }, true);

  document.addEventListener('focusin', function(e) {
    const el = fillableFromTarget(eventTarget(e));
    if (el) ensureFillSession(el);
  }, true);

  document.addEventListener('input', function(e) {
    const el = fillableFromTarget(eventTarget(e));
    if (!el) return;
    ensureFillSession(el);
    syncFillSessionValue(el);
  }, true);

  document.addEventListener('focusout', function(e) {
    const el = fillableFromTarget(eventTarget(e));
    if (el) commitOnBlur(el);
  }, true);

  document.addEventListener('compositionstart', function() { composing = true; }, true);

  document.addEventListener('compositionend', function(e) {
    composing = false;
    const el = fillableFromTarget(eventTarget(e));
    if (el) { ensureFillSession(el); syncFillSessionValue(el); }
  }, true);

  document.addEventListener('keydown', function(e) {
    const el = eventTarget(e);
    const fillable = (el && el.tagName) ? fillableFromTarget(el) : null;
    if (fillable) syncFillSessionValue(fillable);

    // Only Enter/Escape are semantically replayable presses. Tab is omitted:
    // it fires focusout which already commits the fill session. Modifier keys
    // are preserved so e.g. Ctrl+Enter (send) replays with identical semantics.
    if (e.key !== 'Enter' && e.key !== 'Escape') return;
    // While an IME composition is active, Enter/Escape select or cancel the
    // candidate phrase — not a page-level action, so neither a press step nor a
    // keyboard-activation target should be recorded for them.
    if (composing) return;

    if (e.key === 'Enter') {
      // A form implicitly submits on Enter; the browser then synthesizes a click
      // on the submit button (detail=0). Record that button as the activation
      // target so the synthetic click is deduplicated instead of becoming a
      // redundant click step that would double-submit on replay.
      let submitTarget = el;
      if (fillable && fillable.closest) {
        const form = fillable.closest('form');
        if (form) {
          submitTarget = form.querySelector(
            'button:not([type]),button[type="submit"],input[type="submit"],input[type="image"]'
          ) || el;
        }
      }
      keyboardActivation = { target: submitTarget, recordedAt: Date.now() };
    }

    if (fillable) commitFillSession();
    if (el && el.tagName) {
      const modifiers = [];
      if (e.ctrlKey) modifiers.push('ctrl');
      if (e.metaKey) modifiers.push('meta');
      if (e.altKey) modifiers.push('alt');
      if (e.shiftKey) modifiers.push('shift');
      emitHoverBeforeClick(el);
      emit('press', el, e.key, modifiers);
    }
  }, true);

  window.addEventListener('pagehide', commitFillSession);
  window.addEventListener('hashchange', onSpaUrlChange);
  window.addEventListener('popstate', onSpaUrlChange);

  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;
  history.pushState = function() {
    const result = originalPushState.apply(this, arguments);
    onSpaUrlChange();
    return result;
  };
  history.replaceState = function() {
    const result = originalReplaceState.apply(this, arguments);
    onSpaUrlChange();
    return result;
  };

  window.__myrmActionCapture = true;
  window.__myrmCaptureActive = true;
})();
