"use strict";
// Under Ingress the iframe shares the origin of the HA frontend, so its theme can be read
// directly. ha.css holds HA's default values for when it can't (direct port, local dev).
(() => {
  const VARIABLES = [
    "--primary-color", "--accent-color", "--text-primary-color",
    "--primary-background-color", "--secondary-background-color", "--card-background-color",
    "--primary-text-color", "--secondary-text-color", "--disabled-text-color",
    "--divider-color", "--outline-color", "--state-icon-color",
    "--success-color", "--warning-color", "--error-color", "--info-color",
    "--ha-card-background", "--ha-card-border-color", "--ha-card-border-radius",
    "--ha-card-border-width", "--ha-card-box-shadow",
    "--app-header-background-color", "--app-header-text-color", "--app-header-border-bottom",
    "--ha-font-family-body", "--ha-font-family-code", "--ha-font-size-scale",
  ];
  const root = document.documentElement;

  function parentDocument() {
    try {
      return window.parent !== window ? window.parent.document : null;
    } catch (error) {
      return null;
    }
  }

  function sync() {
    const doc = parentDocument();
    if (!doc) return;
    const sources = [doc.documentElement, doc.querySelector("home-assistant")].filter(Boolean)
      .map((element) => window.parent.getComputedStyle(element));
    for (const name of VARIABLES) {
      const value = sources.map((style) => style.getPropertyValue(name).trim()).find(Boolean);
      if (value) root.style.setProperty(name, value);
      else root.style.removeProperty(name);
    }
    root.style.colorScheme = sources[0].colorScheme;
  }

  // HA declares Roboto with @font-face in its own document, a frame doesn't inherit that.
  function copyFonts() {
    const doc = parentDocument();
    if (!doc) return;
    const rules = [];
    for (const sheet of [...doc.styleSheets, ...(doc.adoptedStyleSheets || [])]) {
      let list = [];
      try {
        list = sheet.cssRules;
      } catch (error) {
        continue;
      }
      for (const rule of list) {
        if (rule.type === CSSRule.FONT_FACE_RULE && rule.style.fontStyle !== "italic") rules.push(rule.cssText);
      }
    }
    if (!rules.length) return;
    const style = document.createElement("style");
    style.textContent = rules.join("\n");
    document.head.append(style);
  }

  function watch() {
    const doc = parentDocument();
    if (!doc) return;
    let queued = false;
    const schedule = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        sync();
      });
    };
    const observer = new MutationObserver(schedule);
    const options = { attributes: true, attributeFilter: ["style", "class", "dark"] };
    observer.observe(doc.documentElement, options);
    const app = doc.querySelector("home-assistant");
    if (app) observer.observe(app, options);
    // HA switches themes after the media query fires, the observer catches its update.
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", schedule);
  }

  sync();
  copyFonts();
  watch();
})();
