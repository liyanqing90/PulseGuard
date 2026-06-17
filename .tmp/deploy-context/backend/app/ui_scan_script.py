from __future__ import annotations


UI_SCAN_SCRIPT = r"""
() => {
  const MAX_RESULTS = 240;
  const MAX_WORK_ITEMS = 520;
  const pageWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, window.innerWidth);
  const pageHeight = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight);

  const nativeInteractiveTags = new Set(["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA", "OPTION", "SUMMARY"]);
  const roleInteractive = new Set([
    "button",
    "link",
    "menuitem",
    "tab",
    "option",
    "treeitem",
    "listitem",
    "row",
    "cell",
    "gridcell",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "textbox",
    "combobox"
  ]);
  const structureTags = new Set(["NAV", "HEADER", "FOOTER", "MAIN", "ASIDE", "SECTION", "ARTICLE", "FORM", "TABLE", "UL", "OL", "LI"]);
  const landmarkRoles = new Set(["navigation", "banner", "contentinfo", "main", "complementary", "region", "article"]);
  const mediaTags = new Set(["IMG", "SVG", "CANVAS", "VIDEO", "PICTURE", "IFRAME"]);
  const headingTags = new Set(["H1", "H2", "H3", "H4", "H5", "H6"]);
  const hardSkipTags = new Set(["META", "SCRIPT", "STYLE", "LINK", "TITLE", "HEAD", "NOSCRIPT", "BR"]);
  const stableAttrs = [
    "data-testid",
    "data-test",
    "data-qa",
    "data-cy",
    "data-automation",
    "data-eid",
    "data-id",
    "data-action",
    "data-target",
    "data-name",
    "dt-eid",
    "dt-imp-once",
    "dt-params",
    "aria-label",
    "aria-labelledby",
    "name",
    "title",
    "alt"
  ];
  const preferredDataAttrs = ["data-testid", "data-test", "data-qa", "data-cy", "data-automation"];
  const semanticWords = new Set([
    "search",
    "login",
    "signin",
    "register",
    "signup",
    "username",
    "password",
    "captcha",
    "code",
    "filter",
    "price",
    "brand",
    "logout",
    "submit",
    "save",
    "confirm",
    "cancel",
    "close",
    "more",
    "menu",
    "dialog",
    "tab",
    "button",
    "link",
    "edit",
    "delete",
    "remove",
    "add",
    "create",
    "select",
    "sort",
    "toggle",
    "title",
    "image",
    "img",
    "store",
    "mall",
    "subsidy",
    "detail",
    "swiper",
    "goods",
    "product",
    "card",
    "panel",
    "section"
  ]);
  const weakNoiseWords = new Set([
    "wrapper",
    "container",
    "inner",
    "outer",
    "content",
    "box",
    "group",
    "flex",
    "row",
    "col",
    "grid",
    "inline",
    "block",
    "layout",
    "item",
    "root",
    "main"
  ]);

  const attrSelector = (name, value) => `[${name}=${JSON.stringify(String(value))}]`;
  const normalizeText = (value) =>
    String(value || "")
      .normalize("NFKC")
      .replace(/\s+/g, " ")
      .trim();
  const directText = (el) =>
    normalizeText(
      Array.from(el.childNodes || [])
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent || "")
        .join(" ")
    );
  const visibleText = (el) =>
    normalizeText(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("alt") || el.getAttribute("title") || el.textContent || "");
  const roleOf = (el) =>
    el.getAttribute("role") ||
    {
      A: "link",
      BUTTON: "button",
      INPUT: inputRole(el),
      SELECT: "combobox",
      TEXTAREA: "textbox",
      H1: "heading",
      H2: "heading",
      H3: "heading",
      H4: "heading",
      H5: "heading",
      H6: "heading",
      NAV: "navigation",
      HEADER: "banner",
      FOOTER: "contentinfo",
      MAIN: "main",
      ASIDE: "complementary",
      SECTION: "region",
      ARTICLE: "article"
    }[el.tagName] ||
    "";

  function inputRole(el) {
    const type = String(el.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (["button", "submit", "reset"].includes(type)) return "button";
    if (type === "range") return "slider";
    return "textbox";
  }

  function cssCount(selector) {
    try {
      return document.querySelectorAll(selector).length;
    } catch {
      return 0;
    }
  }

  function exactVisibleTextCount(text) {
    if (!text) return 0;
    let count = 0;
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
    let node = walker.currentNode;
    while (node) {
      if (visibleText(node) === text) count += 1;
      if (count > 1) return count;
      node = walker.nextNode();
    }
    return count;
  }

  function hasStableAttribute(el) {
    return stableAttrs.some((name) => {
      const value = el.getAttribute(name);
      return value && isStableValue(value);
    });
  }

  function isVisible(el) {
    if (!el || hardSkipTags.has(el.tagName) || el.closest("head")) return false;
    if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 8 && rect.height >= 8;
  }

  function isDynamicToken(token) {
    const value = String(token || "");
    if (!value) return true;
    if (/^(react|mui|ember|ng|jss|css|ant|rc|ruyi|icon)-/i.test(value)) return true;
    if (/^[a-f0-9]{8,}$/i.test(value)) return true;
    if (/^[A-Za-z0-9_-]{12,}$/.test(value) && /[A-Z]/.test(value) && /\d/.test(value)) return true;
    if (/\d{4,}/.test(value)) return true;
    return false;
  }

  function isStableValue(value) {
    const text = normalizeText(value);
    if (!text || text.length > 96) return false;
    if (/^[0-9a-f]{8,}$/i.test(text)) return false;
    if (/^\d{5,}$/.test(text)) return false;
    return true;
  }

  function classIdText(el) {
    return `${el.id || ""} ${el.getAttribute("class") || ""}`;
  }

  function rawTokens(value) {
    return normalizeText(value)
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .split(/[^A-Za-z0-9\u4e00-\u9fff]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function semanticTokens(el) {
    return rawTokens(classIdText(el))
      .map((item) => item.toLowerCase())
      .filter((item) => item && !isDynamicToken(item) && !weakNoiseWords.has(item) && !/^([pm]|text|bg|border|rounded|shadow|opacity|z)-/.test(item))
      .slice(0, 5);
  }

  function hasSemanticClass(el) {
    return semanticTokens(el).some((token) => semanticWords.has(token));
  }

  function isButtonLike(el) {
    if (!["DIV", "SPAN"].includes(el.tagName)) return false;
    const role = roleOf(el);
    if (role === "button") return true;
    const tokens = semanticTokens(el);
    return tokens.includes("button") || tokens.includes("btn") || (tokens.includes("filter") && tokens.includes("button"));
  }

  function isNativeInteractive(el) {
    return nativeInteractiveTags.has(el.tagName) || roleInteractive.has(roleOf(el));
  }

  function isKeyNode(el) {
    if (isNativeInteractive(el) || isButtonLike(el)) return true;
    const role = roleOf(el);
    const tabindex = Number(el.getAttribute("tabindex"));
    const style = getComputedStyle(el);
    const ownText = directText(el);
    const isScrollable = el.scrollHeight > el.clientHeight + 8 || el.scrollWidth > el.clientWidth + 8;
    return (
      (!Number.isNaN(tabindex) && tabindex >= 0) ||
      el.hasAttribute("aria-pressed") ||
      el.hasAttribute("aria-selected") ||
      el.hasAttribute("aria-expanded") ||
      el.getAttribute("contenteditable") === "true" ||
      Boolean(el.onclick || el.getAttribute("onclick")) ||
      style.cursor === "pointer" ||
      Boolean(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.getAttribute("title") || el.getAttribute("alt")) ||
      (ownText.length >= 2 && ownText.length <= 24) ||
      el.children.length >= 2 ||
      (el.parentElement && el.parentElement.children.length >= 2) ||
      structureTags.has(el.tagName) ||
      landmarkRoles.has(role) ||
      hasStableAttribute(el) ||
      hasSemanticClass(el) ||
      isScrollable ||
      ["sticky", "fixed"].includes(style.position) ||
      ["dialog", "alertdialog"].includes(role)
    );
  }

  function isIndependentInteractive(el) {
    return isNativeInteractive(el) || isButtonLike(el) || Boolean(el.onclick || el.getAttribute("onclick")) || roleInteractive.has(roleOf(el));
  }

  function hasInteractiveAncestor(el) {
    let parent = el.parentElement;
    while (parent && parent !== document.body && parent !== document.documentElement) {
      if ((isNativeInteractive(parent) || isButtonLike(parent)) && !isIndependentInteractive(el)) return true;
      parent = parent.parentElement;
    }
    return false;
  }

  function stableClassSelector(el) {
    const classes = Array.from(el.classList || []).filter((item) => {
      const lower = item.toLowerCase();
      if (isDynamicToken(lower)) return false;
      if (/^(ant|css|rc)-/.test(lower)) return false;
      return rawTokens(lower).some((token) => semanticWords.has(token.toLowerCase())) || lower.length <= 24;
    });
    return classes.slice(0, 2).map((item) => `.${CSS.escape(item)}`).join("");
  }

  function cssPath(el) {
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.documentElement) {
      const tag = current.tagName.toLowerCase();
      let part = tag;
      const id = current.id;
      if (id && isStableValue(id) && !isDynamicToken(id)) {
        const selector = `#${CSS.escape(id)}`;
        if (cssCount(selector) === 1) {
          parts.unshift(selector);
          break;
        }
      }
      part += stableClassSelector(current);
      const parent = current.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      const selector = parts.join(" > ");
      if (cssCount(selector) === 1) return selector;
      current = parent;
    }
    return parts.join(" > ") || el.tagName.toLowerCase();
  }

  function accessibleName(el) {
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const text = labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.innerText || document.getElementById(id)?.textContent || "")
        .join(" ");
      if (normalizeText(text)) return normalizeText(text);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return normalizeText(aria);
    if (el.id) {
      const label = document.querySelector(`label[for=${JSON.stringify(el.id)}]`);
      if (label) return visibleText(label);
    }
    for (const attr of ["title", "alt", "value", "placeholder"]) {
      const value = el.getAttribute(attr) || (attr === "value" ? el.value : "");
      if (value) return normalizeText(value);
    }
    return visibleText(el);
  }

  function locatorScore(type, selector, unique) {
    let score = 36;
    const value = String(selector || "");
    if (["testid", "data", "dt"].includes(type)) score += 42;
    if (type === "name") score += 38;
    if (type === "id") score += 36;
    if (type === "label" || type === "role" || type === "aria" || type === "title") score += 31;
    if (type === "css") score += 20;
    if (type === "text") score += 10;
    if (unique) score += 14;
    if (/nth-(child|of-type)|\[\d+\]/.test(value)) score -= 16;
    if ((value.match(/>/g) || []).length > 2) score -= 12;
    if (value.length > 96) score -= 14;
    if (value.length > 150) score -= 20;
    if (/^text=/.test(value) && /[\u4e00-\u9fff]/.test(value)) score -= 4;
    return Math.max(1, Math.min(100, Math.round(score)));
  }

  function addLocator(list, type, selector, unique) {
    if (!selector || list.some((item) => item.selector === selector)) return;
    if (/^xpath=\/(?:html|body)/.test(selector)) return;
    const score = locatorScore(type, selector, unique);
    list.push({ type, selector, unique, score, displayScore: score + typePreference(type) });
  }

  function typePreference(type) {
    return { role: 6, testid: 6, name: 5, label: 4, id: 4, css: 4, data: 4, dt: 4, aria: 3, title: 3, placeholder: 2, text: 1 }[type] || 0;
  }

  function generateLocators(el, kind) {
    const list = [];
    for (const attr of preferredDataAttrs) {
      const value = el.getAttribute(attr);
      if (value && isStableValue(value)) {
        const selector = attrSelector(attr, value);
        addLocator(list, "testid", selector, cssCount(selector) === 1);
      }
    }
    const dt = el.getAttribute("dt-eid");
    if (dt && isStableValue(dt)) {
      const selector = attrSelector("dt-eid", dt);
      addLocator(list, "dt", selector, cssCount(selector) === 1);
    }
    for (const attr of Array.from(el.getAttributeNames ? el.getAttributeNames() : [])) {
      if (!attr.startsWith("data-") || preferredDataAttrs.includes(attr)) continue;
      const value = el.getAttribute(attr);
      if (value && isStableValue(value)) {
        const selector = attrSelector(attr, value);
        addLocator(list, "data", selector, cssCount(selector) === 1);
      }
    }
    if (el.id && isStableValue(el.id) && !isDynamicToken(el.id)) {
      const selector = `#${CSS.escape(el.id)}`;
      addLocator(list, "id", selector, cssCount(selector) === 1);
    }
    const name = el.getAttribute("name");
    if (name && isStableValue(name)) {
      const selector = `${el.tagName.toLowerCase()}${attrSelector("name", name)}`;
      addLocator(list, "name", selector, cssCount(selector) === 1);
    }
    const placeholder = el.getAttribute("placeholder");
    if (placeholder && isStableValue(placeholder)) {
      const selector = `${el.tagName.toLowerCase()}${attrSelector("placeholder", placeholder)}`;
      addLocator(list, "placeholder", selector, cssCount(selector) === 1);
    }
    const aria = el.getAttribute("aria-label");
    if (aria && isStableValue(aria)) {
      const selector = attrSelector("aria-label", aria);
      addLocator(list, "aria", selector, cssCount(selector) === 1);
    }
    const role = roleOf(el);
    const acc = accessibleName(el);
    if (role && acc && acc.length <= 60 && roleInteractive.has(role)) {
      addLocator(list, "role", `role=${role}[name=${JSON.stringify(acc)}]`, true);
    }
    const alt = el.getAttribute("alt");
    if (alt && isStableValue(alt)) {
      const selector = `${el.tagName.toLowerCase()}${attrSelector("alt", alt)}`;
      addLocator(list, "aria", selector, cssCount(selector) === 1);
    }
    const title = el.getAttribute("title");
    if (title && isStableValue(title)) {
      const selector = `${el.tagName.toLowerCase()}${attrSelector("title", title)}`;
      addLocator(list, "title", selector, cssCount(selector) === 1);
    }
    const text = visibleText(el);
    if (text && text.length <= 60 && kind !== "component" && exactVisibleTextCount(text) === 1) {
      addLocator(list, "text", `text=${JSON.stringify(text)}`, true);
    }
    const css = cssPath(el);
    addLocator(list, "css", css, cssCount(css) === 1);

    const byType = new Map();
    for (const item of list.sort((left, right) => right.displayScore - left.displayScore)) {
      const existing = byType.get(item.type);
      if (!existing || item.displayScore > existing.displayScore) byType.set(item.type, item);
    }
    const best = Array.from(byType.values()).sort((left, right) => right.displayScore - left.displayScore)[0];
    return best || { type: "css", selector: css, unique: false, score: 35, displayScore: 35 };
  }

  function suffixFor(el, kind) {
    if (isButtonLike(el)) return "button";
    const role = roleOf(el);
    const tag = el.tagName.toLowerCase();
    const type = String(el.getAttribute("type") || "").toLowerCase();
    if (["button", "submit"].includes(role) || ["button", "submit", "reset"].includes(type)) return "button";
    if (["checkbox", "radio"].includes(role) || ["checkbox", "radio"].includes(type)) return role || type;
    if (role === "link" || tag === "a") return "link";
    if (role === "tab") return "tab";
    if (role === "menuitem") return "menuitem";
    if (role === "option") return "option";
    if (role === "listitem" || tag === "li") return "li";
    if (tag === "textarea") return "textarea";
    if (tag === "select") return "select";
    if (tag === "input") return type === "password" ? "password" : "input";
    if (tag === "img") return "img";
    if (role === "navigation" || tag === "nav") return "nav";
    if (role === "banner" || tag === "header") return "header";
    if (role === "contentinfo" || tag === "footer") return "footer";
    if (role === "main" || tag === "main") return "main";
    if (role === "complementary" || tag === "aside") return "aside";
    if (role === "region" || tag === "section") return "section";
    if (kind === "media") return tag;
    return tag === "div" || tag === "span" ? "div" : tag;
  }

  function cleanBase(value) {
    const text = normalizeText(value).replace(/[([]?\d+[)\]]?$/, "");
    if (!text) return "";
    const cleaned = text
      .replace(/[^\u4e00-\u9fffA-Za-z0-9.%]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "");
    const tokens = cleaned.split("_").filter(Boolean);
    if (!tokens.length) return "";
    const deduped = [];
    for (const token of tokens) {
      if (deduped[deduped.length - 1] !== token) deduped.push(token);
    }
    const hasCjk = deduped.some((token) => /[\u4e00-\u9fff]/.test(token));
    const preferred = hasCjk ? deduped.filter((token) => /[\u4e00-\u9fff0-9]/.test(token)) : deduped;
    return preferred
      .slice(0, 3)
      .map((token) => (token.length > 18 ? token.slice(0, 18) : token))
      .join("_");
  }

  function baseFor(el, category) {
    const candidates = [];
    const acc = accessibleName(el);
    if (category === "buttonlike") {
      candidates.push(directText(el), acc, el.getAttribute("title"), semanticTokens(el).join("_"));
    } else if (category === "interactive") {
      candidates.push(acc, el.getAttribute("title"), el.value, el.getAttribute("placeholder"), visibleText(el), el.getAttribute("name"), semanticTokens(el).join("_"));
    } else {
      candidates.push(semanticTokens(el).join("_"), roleOf(el), directText(el), visibleText(el));
    }
    const chinese = candidates.map(cleanBase).find((item) => /[\u4e00-\u9fff]/.test(item));
    return chinese || candidates.map(cleanBase).find(Boolean) || "element";
  }

  function buildName(el, kind) {
    const category = isButtonLike(el) ? "buttonlike" : isNativeInteractive(el) ? "interactive" : "container";
    const suffix = suffixFor(el, kind);
    const base = baseFor(el, category) || "element";
    const max = 35;
    const full = `${base}_${suffix}`;
    if (full.length <= max) return full;
    const available = Math.max(6, max - suffix.length - 1);
    return `${base.slice(0, available)}_${suffix}`;
  }

  function kindOf(el) {
    if (mediaTags.has(el.tagName)) return "media";
    if (isNativeInteractive(el) || isButtonLike(el)) return "interactive";
    const own = directText(el);
    if (headingTags.has(el.tagName) || (own && own.length <= 60 && el.children.length <= 1)) return "text";
    if (structureTags.has(el.tagName) || landmarkRoles.has(roleOf(el)) || hasStableAttribute(el) || hasSemanticClass(el)) return "component";
    return visibleText(el) ? "text" : "component";
  }

  function elementScore(el, kind, locator, rect) {
    let score = locator.displayScore;
    if (kind === "interactive") score += 30;
    if (kind === "media") score += 22;
    if (kind === "component") score += 10;
    if (headingTags.has(el.tagName)) score += 12;
    const area = rect.width * rect.height;
    score += Math.min(12, Math.log10(Math.max(area, 1)) * 3);
    if (area > pageWidth * pageHeight * 0.68) score -= 24;
    if (rect.width < 24 || rect.height < 16) score -= 24;
    return Math.round(score);
  }

  function stability(score) {
    if (score >= 80) return "high";
    if (score >= 60) return "medium";
    return "low";
  }

  function selectorCollector() {
    const classKeywords = [
      "btn",
      "button",
      "tab",
      "link",
      "icon",
      "close",
      "clear",
      "remove",
      "delete",
      "edit",
      "add",
      "create",
      "submit",
      "confirm",
      "cancel",
      "search",
      "filter",
      "sort",
      "toggle",
      "select",
      "title",
      "image",
      "img",
      "store",
      "mall",
      "subsidy",
      "detail",
      "swiper",
      "goods",
      "product",
      "card",
      "panel",
      "section"
    ];
    return [
      "button",
      "a[href]",
      "input:not([type='hidden'])",
      "select",
      "textarea",
      "[role='button']",
      "[role='link']",
      "[role='menuitem']",
      "[role='tab']",
      "[role='option']",
      "[role='treeitem']",
      "[role='listitem']",
      "[role='row']",
      "[role='cell']",
      "[role='gridcell']",
      "[role='checkbox']",
      "[role='radio']",
      "[role='textbox']",
      "[role='combobox']",
      "[onclick]",
      "[tabindex]:not([tabindex='-1'])",
      "label[for]",
      "img[alt]",
      "[data-testid]",
      "[data-test]",
      "[data-qa]",
      "[data-cy]",
      "[data-automation]",
      "[data-eid]",
      "[data-id]",
      "[data-action]",
      "[data-target]",
      "[data-name]",
      "[dt-eid]",
      "[dt-imp-once]",
      "[dt-params]",
      "[aria-label]",
      "[aria-labelledby]",
      "[name]",
      "[title]",
      "main",
      "nav",
      "header",
      "footer",
      "section",
      "article",
      "aside",
      "form",
      "table",
      "ul",
      "ol",
      "li",
      "h1",
      "h2",
      "h3",
      "h4",
      "h5",
      "h6",
      "img",
      "svg",
      "canvas",
      "video",
      "picture",
      "iframe",
      ...classKeywords.flatMap((word) => [`[class*='${word}']`, `[id*='${word}']`])
    ].join(",");
  }

  const rawNodes = Array.from(document.body ? document.body.querySelectorAll(selectorCollector()) : document.querySelectorAll(selectorCollector()));
  const visibleNodes = [];
  const seenNodes = new Set();
  for (const el of rawNodes) {
    if (seenNodes.has(el) || !isVisible(el) || !isKeyNode(el) || hasInteractiveAncestor(el)) continue;
    seenNodes.add(el);
    visibleNodes.push(el);
    if (visibleNodes.length >= MAX_WORK_ITEMS) break;
  }

  const initial = [];
  for (const el of visibleNodes) {
    const rect = el.getBoundingClientRect();
    const x = Math.max(0, rect.left + window.scrollX);
    const y = Math.max(0, rect.top + window.scrollY);
    if (x > pageWidth || y > pageHeight) continue;
    const kind = kindOf(el);
    const locator = generateLocators(el, kind);
    const score = elementScore(el, kind, locator, rect);
    initial.push({
      el,
      selector: locator.selector,
      selector_type: locator.type,
      stability: stability(locator.score),
      score,
      name: buildName(el, kind),
      text: visibleText(el).slice(0, 160),
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      kind,
      box: {
        x,
        y,
        width: Math.min(pageWidth - x, rect.width),
        height: Math.min(pageHeight - y, rect.height)
      }
    });
  }

  const pruned = initial.filter((item) => {
    return !initial.some((other) => {
      if (item === other) return false;
      if (!item.el.contains(other.el)) return false;
      const itemText = normalizeText(item.text);
      const otherText = normalizeText(other.text);
      return otherText && (itemText === otherText || itemText.includes(otherText));
    });
  });

  const bySelector = new Map();
  for (const item of pruned.sort((left, right) => right.score - left.score)) {
    if (!bySelector.has(item.selector)) bySelector.set(item.selector, item);
  }

  const nameCounts = new Map();
  const output = Array.from(bySelector.values())
    .sort((left, right) => right.score - left.score)
    .slice(0, MAX_RESULTS)
    .map(({ el, score, ...item }) => {
      const count = (nameCounts.get(item.name) || 0) + 1;
      nameCounts.set(item.name, count);
      return { ...item, name: count === 1 ? item.name : `${item.name}_${count}`, score };
    });

  return {
    viewport: { width: window.innerWidth, height: window.innerHeight },
    page_size: { width: pageWidth, height: pageHeight },
    candidates: output
  };
}
"""
