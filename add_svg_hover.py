#!/usr/bin/env python3
"""
Generate an interactive SVG from:
  1. an input SVG
  2. a measurement-code -> SVG element ID mapping JSON

Behavior:
- Hover definition label -> highlight mapped line/path, no tooltip.
- Hover diagram line/path -> highlight matching definition and show full definition tooltip.
- Click definition label -> copy variable name and show copied popup.
- Click diagram line/path -> copy variable name, show copied popup, and pin highlight/tooltip.

Usage:
  python add_svg_hover.py input.svg mapping.json output.svg
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
NS = {"svg": SVG_NS, "sodipodi": SODIPODI_NS}


def qn(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"


def local_name(el: etree._Element) -> str:
    return etree.QName(el).localname


def text_content(el: etree._Element) -> str:
    return " ".join("".join(el.itertext()).split())


def add_class(el: etree._Element, class_name: str) -> None:
    classes = (el.get("class") or "").split()
    for cls in class_name.split():
        if cls not in classes:
            classes.append(cls)
    el.set("class", " ".join(classes))


def add_measure(el: etree._Element, code: str) -> None:
    existing = (el.get("data-measures") or "").split()
    if code not in existing:
        existing.append(code)
    el.set("data-measures", " ".join(existing))
    if len(existing) == 1:
        el.set("data-measure", existing[0])
    elif "data-measure" in el.attrib:
        del el.attrib["data-measure"]


def normalize_mapping(raw: Any) -> Dict[str, List[str]]:
    if isinstance(raw, dict) and "mapping" in raw and isinstance(raw["mapping"], dict):
        raw = raw["mapping"]

    if not isinstance(raw, dict):
        raise ValueError(
            "Mapping JSON must be an object, or an object with a 'mapping' object."
        )

    mapping: Dict[str, List[str]] = {}
    for code, ids in raw.items():
        code = str(code).strip()
        if not code:
            continue
        if isinstance(ids, str):
            id_list = [ids]
        elif isinstance(ids, list):
            id_list = [str(x).strip() for x in ids if str(x).strip()]
        else:
            raise ValueError(
                f"Mapping value for {code!r} must be a string or a list of strings."
            )

        seen = set()
        clean = []
        for item in id_list:
            if item not in seen:
                clean.append(item)
                seen.add(item)
        mapping[code] = clean
    return mapping


def find_by_id(root: etree._Element, element_id: str) -> etree._Element | None:
    matches = root.xpath("//*[@id=$id]", id=element_id)
    return matches[0] if matches else None


def code_starts_text(txt: str, code: str) -> bool:
    return bool(txt and re.match(rf"^{re.escape(code)}\b", txt))


def is_single_definition_line(txt: str, code: str) -> bool:
    """
    True for e.g. "A01 - Height: Total (height)".
    False for parent text that contains A01...A02...A03...
    """
    if not code_starts_text(txt, code):
        return False
    rest = txt[len(code) :]
    return re.search(r"\b[A-Q]\d{2}\b", rest) is None


def variable_from_label(label: str) -> str:
    m = re.search(r"\(([^()]+)\)\s*$", label)
    return m.group(1).strip() if m else ""


def collect_definition_labels(
    root: etree._Element, mapping: Dict[str, List[str]]
) -> Dict[str, str]:
    labels: Dict[str, str] = {}

    all_text = root.xpath(".//*[local-name()='text' or local-name()='tspan']")
    for code in mapping:
        candidates: List[tuple[int, str]] = []

        for el in all_text:
            txt = text_content(el)
            if not code_starts_text(txt, code):
                continue

            score = 0

            # Strongly prefer individual Inkscape/Sodipodi text lines.
            if el.get(f"{{{SODIPODI_NS}}}role") == "line":
                score += 100

            # Prefer actual full definitions with a variable in parentheses.
            if variable_from_label(txt):
                score += 80

            # Avoid huge parent text nodes containing many definitions.
            if is_single_definition_line(txt, code):
                score += 50
            else:
                score -= 100

            # Prefer labels that have more than only "A01".
            if len(txt) > len(code) + 4:
                score += 20

            candidates.append((score, txt))

        if candidates:
            candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
            labels[code] = candidates[0][1]
        else:
            labels[code] = code

    return labels


def is_definition_candidate(el: etree._Element, code: str) -> bool:
    if local_name(el) not in {"text", "tspan"}:
        return False
    txt = text_content(el)
    if not code_starts_text(txt, code):
        return False

    # Annotate single line labels and short code-only tspans.
    if is_single_definition_line(txt, code):
        return True
    if txt == code:
        return True
    return False


def annotate_definition_text(root: etree._Element, code: str, label: str) -> int:
    count = 0
    variable = variable_from_label(label)

    for el in root.xpath(".//*[local-name()='text' or local-name()='tspan']"):
        if not is_definition_candidate(el, code):
            continue

        add_class(el, "measure-definition")
        add_measure(el, code)
        el.set("data-measure-label", label)
        if variable:
            el.set("data-measure-var", variable)
        el.set("tabindex", "0")

        style = el.get("style") or ""
        if "cursor:" not in style:
            el.set(
                "style",
                style
                + (";" if style and not style.endswith(";") else "")
                + "cursor:pointer",
            )

        count += 1

    return count


def ensure_title(el: etree._Element, label: str) -> None:
    for child in el:
        if local_name(child) == "title":
            child.text = label
            return
    title = etree.Element(qn("title"))
    title.text = label
    el.insert(0, title)


def inject_style_and_script(
    root: etree._Element, highlight_color: str, definition_color: str
) -> None:
    css = f"""
.measure-definition {{
  cursor: pointer;
}}
.measure-target {{
  cursor: pointer;
}}
.measure-definition.is-highlighted {{
  fill: {definition_color} !important;
  font-weight: 700 !important;
}}
.measure-target.is-highlighted {{
  stroke: {highlight_color} !important;
  stroke-opacity: 1 !important;
}}
text.measure-target.is-highlighted,
tspan.measure-target.is-highlighted {{
  fill: {definition_color} !important;
  stroke: none !important;
}}
.measure-target[data-measures],
.measure-target[data-measure] {{
  vector-effect: non-scaling-stroke;
}}
.measure-tooltip,
.measure-copy-popup {{
  pointer-events: none;
}}
.measure-tooltip rect,
.measure-copy-popup rect {{
  fill: rgba(255,255,255,0.97);
  stroke: #666;
  stroke-width: 0.75px;
}}
.measure-tooltip text,
.measure-copy-popup text {{
  font-family: Arial, sans-serif;
  font-size: 12px;
  fill: #111;
}}
.measure-copy-popup rect {{
  stroke: #0a8f45;
}}
.measure-copy-popup text {{
  fill: #0a6f38;
  font-weight: 700;
}}
"""

    js = r"""
(function(){
  let pinned = null;
  const svg = document.documentElement;
  const SVG_NS = 'http://www.w3.org/2000/svg';

  let tooltipGroup = null, tooltipRect = null, tooltipText = null;
  let popupGroup = null, popupRect = null, popupText = null, popupTimer = null;

  function codesFor(el) {
    const raw = el.getAttribute('data-measures') || el.getAttribute('data-measure') || '';
    return raw.trim().split(/\s+/).filter(Boolean);
  }

  function hasCode(el, code) {
    return codesFor(el).includes(code);
  }

  function elementsForCode(code, selector) {
    const all = document.querySelectorAll(selector || '[data-measures], [data-measure]');
    const out = [];
    for (const el of all) {
      if (hasCode(el, code)) out.push(el);
    }
    return out;
  }

  function labelForCode(code) {
    // Prefer definition labels because they are the source of truth for the full text.
    const definitions = elementsForCode(code, '.measure-definition');
    for (const el of definitions) {
      const label = el.getAttribute('data-measure-label');
      if (label && label !== code) return label;
    }

    const targets = elementsForCode(code, '.measure-target');
    for (const el of targets) {
      const label = el.getAttribute('data-measure-label');
      if (label && label !== code) return label;
    }

    return code;
  }

  function variableForCode(code) {
    const definitions = elementsForCode(code, '.measure-definition');
    const targets = elementsForCode(code, '.measure-target');
    const all = definitions.concat(targets);

    for (const el of all) {
      const explicit = el.getAttribute('data-measure-var');
      if (explicit) return explicit;
    }

    const label = labelForCode(code);
    const match = label.match(/\(([^()]+)\)\s*$/);
    return match ? match[1].trim() : '';
  }

  function makeOverlay(className) {
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('class', className);
    group.style.display = 'none';

    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('rx', '4');
    rect.setAttribute('ry', '4');

    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', '7');

    group.appendChild(rect);
    group.appendChild(text);
    svg.appendChild(group);
    return {group: group, rect: rect, text: text};
  }

  function ensureTooltip() {
    if (tooltipGroup) return;
    const o = makeOverlay('measure-tooltip');
    tooltipGroup = o.group;
    tooltipRect = o.rect;
    tooltipText = o.text;
  }

  function ensurePopup() {
    if (popupGroup) return;
    const o = makeOverlay('measure-copy-popup');
    popupGroup = o.group;
    popupRect = o.rect;
    popupText = o.text;
  }

  function clearHighlights() {
    document.querySelectorAll('.is-highlighted').forEach(function(el){
      el.classList.remove('is-highlighted');
    });
  }

  function highlight(code) {
    clearHighlights();
    if (!code) return;
    document.querySelectorAll('[data-measures], [data-measure]').forEach(function(el){
      if (hasCode(el, code)) el.classList.add('is-highlighted');
    });
  }

  function pointFromEvent(evt) {
    if (!evt || typeof evt.clientX !== 'number') return null;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    return ctm ? pt.matrixTransform(ctm.inverse()) : null;
  }

  function positionFor(evt, sourceEl) {
    const pt = pointFromEvent(evt);
    if (pt) return {x: pt.x + 10, y: pt.y - 30};

    if (sourceEl && sourceEl.getBBox) {
      try {
        const bb = sourceEl.getBBox();
        return {x: bb.x + bb.width + 10, y: bb.y - 10};
      } catch (err) {}
    }
    return {x: 10, y: 10};
  }

  function sizeOverlay(rect, text, message) {
    text.textContent = message;
    text.setAttribute('x', '7');
    text.setAttribute('y', '14');

    let bb;
    try {
      bb = text.getBBox();
    } catch (err) {
      bb = {width: Math.max(40, message.length * 7), height: 14};
    }

    const w = bb.width + 14;
    const h = Math.max(20, bb.height + 8);
    rect.setAttribute('x', '0');
    rect.setAttribute('y', '0');
    rect.setAttribute('width', String(w));
    rect.setAttribute('height', String(h));
    text.setAttribute('y', String(h - 6));
  }

  function showTooltip(code, evt, sourceEl) {
    ensureTooltip();
    const label = labelForCode(code);
    if (!label) {
      hideTooltip();
      return;
    }

    tooltipGroup.style.display = 'inline';
    sizeOverlay(tooltipRect, tooltipText, label);

    const pos = positionFor(evt, sourceEl);
    tooltipGroup.setAttribute('transform', 'translate(' + pos.x + ',' + pos.y + ')');
  }

  function hideTooltip() {
    if (tooltipGroup) tooltipGroup.style.display = 'none';
  }

  function showPopup(message, evt, sourceEl) {
    ensurePopup();
    popupGroup.style.display = 'inline';
    sizeOverlay(popupRect, popupText, message);

    const pos = positionFor(evt, sourceEl);
    popupGroup.setAttribute('transform', 'translate(' + pos.x + ',' + (pos.y + 26) + ')');

    if (popupTimer) window.clearTimeout(popupTimer);
    popupTimer = window.setTimeout(function(){
      popupGroup.style.display = 'none';
    }, 1600);
  }

  function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();

    try {
      document.execCommand('copy');
      document.body.removeChild(textarea);
      return Promise.resolve();
    } catch (err) {
      document.body.removeChild(textarea);
      return Promise.reject(err);
    }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function(){
        return fallbackCopy(text);
      });
    }
    return fallbackCopy(text);
  }

  function copyVariableForCode(code, evt, sourceEl) {
    const variable = variableForCode(code);
    if (!variable) {
      showPopup('No variable name found', evt, sourceEl);
      return;
    }

    copyText(variable).then(function(){
      showPopup('Copied: ' + variable, evt, sourceEl);
    }).catch(function(){
      // Still show the value, so the user can manually copy it if the browser blocks clipboard.
      showPopup('Copy failed: ' + variable, evt, sourceEl);
    });
  }

  function pin(code, evt, sourceEl) {
    pinned = code || null;
    highlight(pinned);
    if (pinned) showTooltip(pinned, evt, sourceEl);
    else hideTooltip();
  }

  function install() {
    ensureTooltip();
    ensurePopup();

    document.querySelectorAll('.measure-definition, .measure-target').forEach(function(el){
      const codes = codesFor(el);
      if (!codes.length) return;

      el.addEventListener('mouseenter', function(evt){
        if (!pinned) {
          highlight(codes[0]);

          // Tooltip is only for diagram paths/targets, not definition labels.
          if (el.classList.contains('measure-target')) {
            showTooltip(codes[0], evt, el);
          }
        }
      });

      el.addEventListener('mousemove', function(evt){
        if (!pinned && el.classList.contains('measure-target')) {
          showTooltip(codes[0], evt, el);
        }
      });

      el.addEventListener('mouseleave', function(){
        if (!pinned) {
          clearHighlights();
          hideTooltip();
        }
      });

      el.addEventListener('focus', function(evt){
        if (!pinned) {
          highlight(codes[0]);
          if (el.classList.contains('measure-target')) {
            showTooltip(codes[0], evt, el);
          }
        }
      });

      el.addEventListener('blur', function(){
        if (!pinned) {
          clearHighlights();
          hideTooltip();
        }
      });

      el.addEventListener('click', function(evt){
        evt.stopPropagation();
        const code = codes[0];

        if (el.classList.contains('measure-target')) {
          // Diagram path: pin highlight and show full definition tooltip.
          pin(pinned === code ? null : code, evt, el);
        } else {
          // Definition label: highlight only; no tooltip.
          pinned = null;
          hideTooltip();
          highlight(code);
        }

        copyVariableForCode(code, evt, el);
      });
    });

    document.addEventListener('click', function(){
      pin(null);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
})();
"""

    style_el = etree.Element(qn("style"))
    style_el.text = css

    script_el = etree.Element(qn("script"))
    script_el.set("type", "application/ecmascript")
    script_el.text = etree.CDATA(js)

    insert_at = 0
    for i, child in enumerate(root):
        if local_name(child) in {"title", "desc"}:
            insert_at = i + 1
    root.insert(insert_at, style_el)
    root.insert(insert_at + 1, script_el)


def add_hover_to_svg(
    input_svg: Path,
    mapping_json: Path,
    output_svg: Path,
    highlight_color: str,
    definition_color: str,
    strict: bool,
) -> int:
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree = etree.parse(str(input_svg), parser)
    root = tree.getroot()

    raw_mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
    mapping = normalize_mapping(raw_mapping)
    labels = collect_definition_labels(root, mapping)

    missing_ids: Dict[str, List[str]] = {}
    annotated_targets = 0
    annotated_definitions = 0

    for code, ids in mapping.items():
        label = labels.get(code, code)
        variable = variable_from_label(label)

        annotated_definitions += annotate_definition_text(root, code, label)

        for element_id in ids:
            el = find_by_id(root, element_id)
            if el is None:
                missing_ids.setdefault(code, []).append(element_id)
                continue

            add_class(el, "measure-target")
            add_measure(el, code)
            el.set("data-measure-label", label)
            if variable:
                el.set("data-measure-var", variable)
            el.set("tabindex", "0")
            ensure_title(el, label)
            annotated_targets += 1

    inject_style_and_script(root, highlight_color, definition_color)
    output_svg.write_text(etree.tostring(root, encoding="unicode"), encoding="utf-8")

    if missing_ids:
        print("Warning: some mapped SVG ids were not found:", file=sys.stderr)
        for code, ids in missing_ids.items():
            print(f"  {code}: {', '.join(ids)}", file=sys.stderr)
        if strict:
            return 2

    print(f"Wrote: {output_svg}")
    print(f"Mapped codes: {len(mapping)}")
    print(f"Annotated target elements: {annotated_targets}")
    print(f"Annotated definition text elements: {annotated_definitions}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add hover/click highlight interaction to an SVG using a measurement-code-to-SVG-ID mapping."
    )
    parser.add_argument("input_svg", type=Path)
    parser.add_argument("mapping_json", type=Path)
    parser.add_argument("output_svg", type=Path)
    parser.add_argument("--highlight-color", default="#ff4d00")
    parser.add_argument("--definition-color", default="#cc3300")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 if any mapped SVG id is missing.",
    )
    args = parser.parse_args(argv)

    return add_hover_to_svg(
        input_svg=args.input_svg,
        mapping_json=args.mapping_json,
        output_svg=args.output_svg,
        highlight_color=args.highlight_color,
        definition_color=args.definition_color,
        strict=args.strict,
    )


if __name__ == "__main__":
    raise SystemExit(main())
