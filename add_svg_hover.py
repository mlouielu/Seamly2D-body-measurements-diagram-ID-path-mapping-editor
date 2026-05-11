#!/usr/bin/env python3
"""
Add hover/click highlighting to an SVG from an ID-to-measurement mapping.

Features:
- hover definition -> highlight mapped SVG elements
- hover mapped line/path -> highlight matching definition and show full label
- click definition or mapped line/path -> copy the variable name in parentheses, e.g. bust_arc_f
- after copying, show an in-SVG popup message

Usage:
  python add_svg_hover_with_reverse.py input.svg mapping.json output.svg
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
        raise ValueError("Mapping JSON must be an object, or an object with a 'mapping' object.")

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
            raise ValueError(f"Mapping value for {code!r} must be a string or a list of strings.")

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


def is_definition_candidate(el: etree._Element, code: str) -> bool:
    if local_name(el) not in {"text", "tspan"}:
        return False
    txt = text_content(el)
    return bool(txt and re.match(rf"^{re.escape(code)}\b", txt))


def clean_definition_label(raw: str, code: str) -> str:
    raw = " ".join(raw.split())
    # If the found element is only the bold code, keep the code. Later another element may
    # provide the full line.
    return raw or code


def variable_from_label(label: str) -> str:
    m = re.search(r"\(([^()]+)\)\s*$", label)
    return m.group(1).strip() if m else ""


def collect_definition_labels(root: etree._Element, mapping: Dict[str, List[str]]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for code in mapping:
        candidates = []
        for el in root.xpath(".//*[local-name()='text' or local-name()='tspan']"):
            if is_definition_candidate(el, code):
                txt = clean_definition_label(text_content(el), code)
                candidates.append(txt)

        # Prefer the longest candidate because the parent text/tspan usually contains
        # "G12 - Bust arc front (bust_arc_f)" while the bold child may only contain "G12".
        if candidates:
            labels[code] = max(candidates, key=len)
        else:
            labels[code] = code

    return labels


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
            el.set("style", style + (";" if style and not style.endswith(";") else "") + "cursor:pointer")

        count += 1

    return count


def ensure_title(el: etree._Element, label: str) -> None:
    # Replace old generated title if present; otherwise add one.
    for child in el:
        if local_name(child) == "title":
            child.text = label
            return
    title = etree.Element(qn("title"))
    title.text = label
    el.insert(0, title)


def inject_style_and_script(root: etree._Element, highlight_color: str, definition_color: str) -> None:
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

  let tooltipGroup = null;
  let tooltipRect = null;
  let tooltipText = null;

  let popupGroup = null;
  let popupRect = null;
  let popupText = null;
  let popupTimer = null;

  function codesFor(el) {
    const raw = el.getAttribute('data-measures') || el.getAttribute('data-measure') || '';
    return raw.trim().split(/\s+/).filter(Boolean);
  }

  function hasCode(el, code) {
    return codesFor(el).includes(code);
  }

  function firstElementForCode(code) {
    const all = document.querySelectorAll('[data-measures], [data-measure]');
    for (const el of all) {
      if (hasCode(el, code)) return el;
    }
    return null;
  }

  function labelForCode(code) {
    const el = firstElementForCode(code);
    return (el && el.getAttribute('data-measure-label')) || code;
  }

  function variableForCode(code) {
    const el = firstElementForCode(code);
    if (!el) return '';

    const explicit = el.getAttribute('data-measure-var');
    if (explicit) return explicit;

    const label = el.getAttribute('data-measure-label') || '';
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
    return {group, rect, text};
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
          showTooltip(codes[0], evt, el);
        }
      });

      el.addEventListener('mousemove', function(evt){
        if (!pinned) showTooltip(codes[0], evt, el);
      });

      el.addEventListener('mouseleave', function(){
        if (!pinned) {
          clearHighlights();
          hideTooltip();
        }
      });

      el.addEventListener('focus', function(){
        if (!pinned) {
          highlight(codes[0]);
          showTooltip(codes[0], null, el);
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

        // click behavior:
        // 1. pin/unpin highlight
        // 2. copy variable from the full label, e.g. bust_arc_f
        pin(pinned === code ? null : code, evt, el);
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
    parser.add_argument("--strict", action="store_true", help="Exit with code 2 if any mapped SVG id is missing.")
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
