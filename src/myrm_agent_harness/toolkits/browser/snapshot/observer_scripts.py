"""JavaScript scripts for DOM observation and cursor detection.


[INPUT]

[OUTPUT]
- MUTATION_OBSERVER_SCRIPT: MutationObserver Initialize脚本
- CURSOR_DETECT_SCRIPT: cursor-interactive Element检测脚本
- BBOX_COLLECTOR_SCRIPT: BBox 批量收集脚本

[POS]
Browser-side JavaScript script constants. Single responsibility: defines DOM mutation
observation, cursor detection, and bounding-box collection logic.
"""

MUTATION_OBSERVER_SCRIPT = """
(function() {
  window.__ariaObserver = {
    changes: [],
    observers: [],

    init: function() {
      if (this.observers.length > 0) return;

      const callback = (mutations) => {
        for (const mutation of mutations) {
          if (mutation.type === 'childList') {
            for (const node of mutation.addedNodes) {
              if (node.nodeType === 1) {
                this.changes.push({ type: 'added', selector: this.getSelector(node) });
                this.observeShadowDOM(node);
              } else if (node.nodeType === 3 && mutation.target.nodeType === 1) {
                this.changes.push({ type: 'text_added', selector: this.getSelector(mutation.target) });
              }
            }
            for (const node of mutation.removedNodes) {
              if (node.nodeType === 1) {
                this.changes.push({ type: 'removed', selector: this.getSelector(node) });
              } else if (node.nodeType === 3 && mutation.target.nodeType === 1) {
                this.changes.push({ type: 'text_removed', selector: this.getSelector(mutation.target) });
              }
            }
          }
          if (mutation.type === 'attributes') {
            this.changes.push({
              type: 'modified',
              selector: this.getSelector(mutation.target),
              attr: mutation.attributeName
            });
          }
          if (mutation.type === 'characterData' && mutation.target.parentElement) {
            this.changes.push({
              type: 'text_changed',
              selector: this.getSelector(mutation.target.parentElement)
            });
          }
        }
      };

      const options = {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
        characterDataOldValue: false,
        attributeFilter: ['role', 'aria-label', 'aria-labelledby', 'class', 'id']
      };

      const mainObserver = new MutationObserver(callback);
      mainObserver.observe(document.body, options);
      this.observers.push(mainObserver);

      this.observeShadowDOM = (node) => {
        if (node.shadowRoot) {
          const shadowObs = new MutationObserver(callback);
          shadowObs.observe(node.shadowRoot, options);
          this.observers.push(shadowObs);
          node.shadowRoot.querySelectorAll('*').forEach(child => this.observeShadowDOM(child));
        }
      };

      document.querySelectorAll('*').forEach(node => this.observeShadowDOM(node));
    },

    getSelector: function(element) {
      if (element.id) return '#' + element.id;
      if (element.className && typeof element.className === 'string') {
        const classes = element.className.trim().split(/\\s+/).slice(0, 2);
        if (classes.length > 0) return element.tagName.toLowerCase() + '.' + classes.join('.');
      }
      return element.tagName.toLowerCase();
    },

    getChanges: function() {
      const result = this.changes.slice();
      this.changes = [];
      return result;
    },

    disconnect: function() {
      for (const obs of this.observers) {
        obs.disconnect();
      }
      this.observers = [];
    }
  };

  window.__ariaObserver.init();
})();
"""

CURSOR_DETECT_SCRIPT = """
(function() {
  const results = [];
  const seen = new Set();

  const getAllElements = () => {
    const all = [];
    const walk = (root) => {
      const els = root.querySelectorAll('*');
      for (const el of els) {
        const tag = el.tagName.toLowerCase();
        if (tag !== 'script' && tag !== 'style' && tag !== 'meta' && tag !== 'link') {
          all.push(el);
        }
        if (el.shadowRoot) {
          walk(el.shadowRoot);
        }
      }
    };
    walk(document.body || document);
    return all;
  };

  const elements = getAllElements();

  for (const elem of elements) {
    const style = window.getComputedStyle(elem);
    const hasPointer = style.cursor === 'pointer';
    const hasOnClick = elem.onclick !== null;
    const hasTabIndex = elem.tabIndex >= 0;

    if (hasPointer || hasOnClick || hasTabIndex) {
      const text = (elem.innerText || elem.textContent || '').trim();
      const ariaLabel = elem.getAttribute('aria-label') || '';
      const name = text || ariaLabel;

      if (name && name.length > 0 && name.length < 200) {
        const key = name.substring(0, 100);
        if (!seen.has(key)) {
          seen.add(key);

          let role = 'focusable';
          if (hasPointer || hasOnClick) {
            role = 'clickable';
          }

          results.push({ name: key, role });
        }
      }
    }
  }

  return results;
})();
"""

BBOX_COLLECTOR_SCRIPT = """
(function(roleNamePairs) {
  const viewport = {
    width: window.innerWidth,
    height: window.innerHeight
  };

  const bboxMap = {};

  const getAllElements = () => {
    const all = [];
    const walk = (root) => {
      const els = root.querySelectorAll('*');
      for (const el of els) {
        all.push(el);
        if (el.shadowRoot) {
          walk(el.shadowRoot);
        }
      }
    };
    walk(document);
    return all;
  };

  const getElementsByRole = (role) => {
    const all = [];
    const walk = (root) => {
      try {
        all.push(...root.querySelectorAll(`[role="${role}"]`));
      } catch(e) {}
      // Add native tags to prevent blind spots
      try {
        if (role === 'button') all.push(...root.querySelectorAll('button, input[type="button"], input[type="submit"], input[type="reset"], input[type="image"]'));
        if (role === 'link') all.push(...root.querySelectorAll('a'));
        if (role === 'textbox' || role === 'searchbox') all.push(...root.querySelectorAll('input[type="text"], input[type="search"], input[type="email"], input[type="url"], input[type="tel"], input[type="password"], input[type="number"], input:not([type]), textarea'));
        if (role === 'combobox') all.push(...root.querySelectorAll('select'));
        if (role === 'checkbox') all.push(...root.querySelectorAll('input[type="checkbox"]'));
        if (role === 'radio') all.push(...root.querySelectorAll('input[type="radio"]'));
      } catch(e) {}

      const els = root.querySelectorAll('*');
      for (const el of els) {
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(document);
    return all;
  };

  let cachedAllElements = null;

  for (const pair of roleNamePairs) {
    const {role, name} = pair;

    let elements = [];
    if (role === 'clickable' || role === 'focusable') {
      if (!cachedAllElements) cachedAllElements = getAllElements();
      for (const elem of cachedAllElements) {
        const text = (elem.innerText || elem.textContent || '').trim();
        const ariaLabel = elem.getAttribute('aria-label') || '';
        const elemName = text || ariaLabel;
        if (elemName === name) {
          elements.push(elem);
        }
      }
    } else {
      const roleLocator = getElementsByRole(role);
      for (const elem of roleLocator) {
        const ariaLabel = elem.getAttribute('aria-label') || '';
        const text = elem.innerText || elem.textContent || '';
        const elemName = ariaLabel || text.trim();
        if (elemName === name) {
          elements.push(elem);
        }
      }
    }

    if (elements.length === 0) continue;

    const elem = elements[0];
    const rect = elem.getBoundingClientRect();

    if (rect.width > 0 && rect.height > 0) {
      const absX = rect.left + window.scrollX;
      const absY = rect.top + window.scrollY;
      const centerX = absX + rect.width / 2;
      const centerY = absY + rect.height / 2;

      bboxMap[`${role}:${name}`] = {
        x: Math.round(absX),
        y: Math.round(absY),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        centerX: Math.round(centerX),
        centerY: Math.round(centerY),
        viewport: viewport
      };
    }
  }

  return bboxMap;
})
"""
