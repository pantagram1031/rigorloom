#!/usr/bin/env python3
"""Apply the COM-free core build_report operations to an HWPX archive."""

import argparse
import base64
import copy
import hashlib
import io
import json
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


SUPPORTED_OPS = {
    "goto_text", "insert_text", "insert_equation", "insert_table",
    "page_binding", "replace_all", "insert_blank_before", "insert_picture",
    "set_line_spacing",
}
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")
HWPUNIT_PER_MM = 7200 / 25.4
HWPUNIT_PER_PIXEL_96_DPI = 7200 / 96
HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"


def emit(summary, code):
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False) + "\n").encode("utf-8"))
    return code


def summary(ok, applied=0, unsupported=None, anchors_missing=None,
            results=None, partial=None):
    payload = {"ok": ok, "applied": applied, "unsupported": unsupported or [],
               "anchors_missing": anchors_missing or []}
    if results is not None:
        payload["results"] = results
    if partial:
        payload["partial"] = partial
    return payload


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def sibling_tag(reference, name):
    namespace = reference.rsplit("}", 1)[0] + "}" if "}" in reference else ""
    return namespace + name


def parse_xml(data):
    for _event, pair in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        prefix, uri = pair
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass
    return ET.ElementTree(ET.fromstring(data))


def child_parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


def ancestor(node, parents, wanted):
    while node is not None:
        if local_name(node.tag) == wanted:
            return node
        node = parents.get(node)
    return None


def first_ref(element, key):
    if element is None:
        return None
    value = element.get(key)
    if value is not None:
        return value
    for node in element.iter():
        value = node.get(key)
        if value is not None:
            return value
    return None


def existing_styles(header_root):
    styles = {"bold": [], "bold_any": None, "normal": [], "center": None,
              "justify": None}
    for node in header_root.iter():
        lname = local_name(node.tag)
        if lname == "charPr":
            style_id = node.get("id")
            is_bold = any(local_name(child.tag) == "bold"
                          for child in node.iter() if child is not node)
            if is_bold and styles["bold_any"] is None:
                styles["bold_any"] = style_id
            height = node.get("height")
            if style_id is None or height is None:
                continue
            try:
                entry = (int(height), style_id)
            except ValueError:
                continue
            styles["bold" if is_bold else "normal"].append(entry)
        elif lname == "paraPr":
            align = next((child for child in node.iter()
                          if local_name(child.tag) == "align"), None)
            horizontal = align.get("horizontal", "").upper() if align is not None else ""
            if horizontal == "JUSTIFY" and styles["justify"] is None:
                styles["justify"] = node.get("id")
            elif horizontal == "CENTER" and styles["center"] is None:
                styles["center"] = node.get("id")
    return styles


def has_visible_table_borders(border_fill):
    sides = {local_name(child.tag): child.get("type", "").upper()
             for child in border_fill}
    return all(sides.get(name) == "SOLID" for name in (
        "leftBorder", "rightBorder", "topBorder", "bottomBorder"))


def balanced_equation_script(script):
    if not isinstance(script, str) or not script.strip():
        return False
    pairs = {"}": "{", "]": "["}
    stack = []
    for char in script:
        if char in "{[":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


def load_ops(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("ops")
    if not isinstance(payload, list):
        raise ValueError("ops payload must be a list or an object containing an ops list")
    for index, op in enumerate(payload):
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            raise ValueError(f"op at index {index} must be an object with a string op")
        if op["op"] == "goto_text" and not isinstance(op.get("text"), str):
            raise ValueError(f"goto_text at index {index} requires string text")
        if op["op"] == "insert_text" and not isinstance(op.get("text"), str):
            raise ValueError(f"insert_text at index {index} requires string text")
    return payload


class HwpxDocument:
    def __init__(self, path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as zin:
            self.items = zin.infolist()
            self.contents = {item.filename: zin.read(item.filename) for item in self.items}
        section_names = sorted(name for name in self.contents if SECTION_RE.match(name))
        if not section_names:
            raise ValueError("HWPX has no Contents/section*.xml members")
        if "Contents/header.xml" not in self.contents:
            raise ValueError("HWPX has no Contents/header.xml member")
        self.sections = {name: parse_xml(self.contents[name]) for name in section_names}
        self.header = parse_xml(self.contents["Contents/header.xml"])
        self.package_trees = {
            name: parse_xml(self.contents[name])
            for name in ("Contents/content.hpf", "META-INF/manifest.xml")
            if name in self.contents
        }
        styles = existing_styles(self.header.getroot())
        self.bold_charprs = styles["bold"]
        self.normal_charprs = styles["normal"]
        self.bold_charpr = styles["bold_any"]
        self.center_parapr = styles["center"]
        self.justify_parapr = styles["justify"]
        self.border_fill = None
        # Prefer a form-native table border style over the first header entry.
        # Real Hancom forms commonly reserve the first borderFill for borderless
        # paragraphs while existing tables point at the solid grid style.
        for tree in self.sections.values():
            table = next((node for node in tree.getroot().iter()
                          if local_name(node.tag) == "tbl" and node.get("borderFillIDRef")),
                         None)
            if table is not None:
                self.border_fill = table.get("borderFillIDRef")
                break
        self.dirty = set()
        self.header_dirty = False
        self.package_dirty = set()
        self.added_members = {}
        self.inserted_paragraphs = []
        ids = []
        object_ids = []
        zorders = []
        for tree in self.sections.values():
            for node in tree.getroot().iter():
                if (node.get("zOrder") or "").isdigit():
                    zorders.append(int(node.get("zOrder")))
                if local_name(node.tag) == "p" and (node.get("id") or "").isdigit():
                    ids.append(int(node.get("id")))
                elif (node.get("id") or "").isdigit():
                    object_ids.append(int(node.get("id")))
        self.next_para_id = max(ids, default=0) + 1
        self.next_object_id = max(object_ids, default=0) + 1
        self.next_zorder = max(zorders, default=-1) + 1

    def save(self, out_path):
        replacements = {}
        for name in self.dirty:
            replacements[name] = ET.tostring(
                self.sections[name].getroot(), encoding="utf-8", xml_declaration=True)
        if self.header_dirty:
            replacements["Contents/header.xml"] = ET.tostring(
                self.header.getroot(), encoding="utf-8", xml_declaration=True)
        for name in self.package_dirty:
            replacements[name] = ET.tostring(
                self.package_trees[name].getroot(), encoding="utf-8",
                xml_declaration=True)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(suffix=".hwpx", dir=str(out_path.parent))
        import os
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_name, "w") as zout:
                for item in self.items:
                    zout.writestr(item, replacements.get(item.filename,
                                                         self.contents[item.filename]))
                for name, data in self.added_members.items():
                    zout.writestr(name, data)
            shutil.move(temp_name, out_path)
        finally:
            if Path(temp_name).exists():
                Path(temp_name).unlink()

    def _track_inserted(self, section_name, para):
        self.inserted_paragraphs.append((section_name, para))

    def goto_text(self, text):
        """Return insertion context for the first anchor contained in one hp:t."""
        for section_name, tree in self.sections.items():
            root = tree.getroot()
            parents = child_parent_map(root)
            for text_node in root.iter():
                if local_name(text_node.tag) != "t":
                    continue
                # T6: deliberately do not concatenate adjacent t nodes or runs.
                if text not in "".join(text_node.itertext()):
                    continue
                para = ancestor(text_node, parents, "p")
                run = ancestor(text_node, parents, "run")
                if para is None or run is None:
                    continue
                parent = parents.get(para)
                if parent is None:
                    continue
                cell = ancestor(para, parents, "tc")
                cell_paras = ([node for node in cell.iter()
                               if local_name(node.tag) == "p"] if cell is not None else [])
                table_label = cell is not None and len(cell_paras) == 1
                para_attrs = dict(para.attrib)
                para_attrs["paraPrIDRef"] = para.get("paraPrIDRef", "")
                charpr = first_ref(run, "charPrIDRef")
                return {"section": section_name, "parent": parent,
                        "insert_at": list(parent).index(para) + 1,
                        "current": None, "anchor_para": para, "anchor_run": run,
                        "para_attrs": para_attrs,
                        "charpr": charpr, "table_label": table_label,
                        "p_tag": para.tag, "run_tag": run.tag, "t_tag": text_node.tag}
        return None

    def replace_all(self, op):
        find = op.get("find")
        replacement = op.get("replace")
        if not isinstance(find, str) or not find or not isinstance(replacement, str):
            raise LookupError("replace_all")
        count = 0
        for section_name, tree in self.sections.items():
            section_count = 0
            for node in tree.getroot().iter():
                if local_name(node.tag) != "t" or node.text is None:
                    continue
                matches = node.text.count(find)
                if matches:
                    node.text = node.text.replace(find, replacement)
                    section_count += matches
            if section_count:
                count += section_count
                self.dirty.add(section_name)
        return {"replaced": count}

    @staticmethod
    def _blank_paragraph(para):
        if local_name(para.tag) != "p" or "".join(para.itertext()).strip():
            return False
        harmless = {"p", "run", "t", "linesegarray", "lineseg"}
        return all(local_name(node.tag) in harmless for node in para.iter())

    def insert_blank_before(self, text):
        cursor = self.goto_text(text)
        if cursor is None:
            return None
        parent = cursor["parent"]
        anchor = cursor["anchor_para"]
        index = list(parent).index(anchor)
        if index and self._blank_paragraph(parent[index - 1]):
            return {"blank_before": text, "inserted": False}

        attrs = {key: value for key, value in anchor.attrib.items() if key != "id"}
        attrs["id"] = str(self.next_para_id)
        self.next_para_id += 1
        para = ET.Element(cursor["p_tag"], attrs)
        run_attrs = ({"charPrIDRef": cursor["charpr"]}
                     if cursor["charpr"] is not None else {})
        ET.SubElement(para, cursor["run_tag"], run_attrs)
        self._append_lineseg(cursor, para, cursor["charpr"])
        parent.insert(index, para)
        self._track_inserted(cursor["section"], para)
        self.dirty.add(cursor["section"])
        return {"blank_before": text, "inserted": True}

    def page_binding(self, op):
        mode = str(op.get("mode") or "submit").lower()
        if mode not in {"submit", "book"}:
            raise LookupError("page_binding")
        page_defs = []
        for section_name, tree in self.sections.items():
            for page_pr in (node for node in tree.getroot().iter()
                            if local_name(node.tag) == "pagePr"):
                margin = next((node for node in page_pr
                               if local_name(node.tag) == "margin"), None)
                if margin is None:
                    continue
                try:
                    left = int(margin.get("left"))
                    right = int(margin.get("right"))
                    gutter = int(margin.get("gutter", "0"))
                except (TypeError, ValueError):
                    continue
                if mode == "submit":
                    total = left + right + gutter
                    left = total // 2
                    right = total - left
                    gutter = 0
                    margin.set("left", str(left))
                    margin.set("right", str(right))
                    margin.set("gutter", "0")
                    self.dirty.add(section_name)
                page_defs.append({"section": section_name, "left": left,
                                  "right": right, "gutter": gutter})
        if not page_defs:
            note = "page binding is not representable: no numeric section page definition"
            return {"binding": mode, "sections": 0, "partial": True, "note": note}
        result = {"binding": mode, "sections": len(page_defs),
                  "note": "applied to section page definition"}
        result.update({key: page_defs[0][key] for key in ("left", "right", "gutter")})
        return result

    def _ensure_table_border_fill(self):
        if self.border_fill is not None:
            return self.border_fill
        root = self.header.getroot()
        border_fills = next((node for node in root.iter()
                             if local_name(node.tag) == "borderFills"), None)
        if border_fills is None:
            raise LookupError("insert_table:borderFill")
        fills = [node for node in border_fills
                 if local_name(node.tag) == "borderFill"]
        solid = next((node for node in fills if has_visible_table_borders(node)), None)
        if solid is not None:
            self.border_fill = solid.get("id")
            return self.border_fill

        numeric_ids = [int(node.get("id")) for node in fills
                       if (node.get("id") or "").isdigit()]
        new_id = str(max(numeric_ids, default=0) + 1)
        border = ET.SubElement(border_fills, sibling_tag(border_fills.tag, "borderFill"),
                               {"id": new_id})
        ET.SubElement(border, sibling_tag(border.tag, "slash"),
                      {"type": "NONE", "Crooked": "0", "isCounter": "0"})
        ET.SubElement(border, sibling_tag(border.tag, "backSlash"),
                      {"type": "NONE", "Crooked": "0", "isCounter": "0"})
        for name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            ET.SubElement(border, sibling_tag(border.tag, name),
                          {"type": "SOLID", "width": "0.12 mm", "color": "#000000"})
        ET.SubElement(border, sibling_tag(border.tag, "diagonal"),
                      {"type": "SOLID", "width": "0.1 mm", "color": "#000000"})
        border_fills.set("itemCnt", str(len(fills) + 1))
        self.border_fill = new_id
        self.header_dirty = True
        return new_id

    def _append_lineseg(self, cursor, para, charpr=None, horzsize=None,
                        spacing_ratio=0.8):
        for child in list(para):
            if local_name(child.tag) == "linesegarray":
                para.remove(child)
        height = self._charpr_height(charpr) or 1000
        width = horzsize or self._section_usable_width(cursor) or 1
        array = ET.SubElement(para, sibling_tag(cursor["p_tag"], "linesegarray"))
        ET.SubElement(array, sibling_tag(cursor["p_tag"], "lineseg"), {
            "textpos": "0", "vertpos": "0", "vertsize": str(height),
            "textheight": str(height), "baseline": str(round(height * 0.85)),
            "spacing": str(round(height * spacing_ratio)), "horzpos": "0",
            "horzsize": str(max(1, width)), "flags": "393216",
        })

    @staticmethod
    def _new_run(cursor, para, attrs):
        run = ET.Element(cursor["run_tag"], attrs)
        lineseg_index = next((index for index, child in enumerate(para)
                              if local_name(child.tag) == "linesegarray"), len(para))
        para.insert(lineseg_index, run)
        return run

    def _new_paragraph(self, cursor, para_pr=None, charpr=None):
        attrs = {key: value for key, value in cursor["para_attrs"].items()
                 if key != "id" and value != ""}
        attrs["id"] = str(self.next_para_id)
        self.next_para_id += 1
        if para_pr is not None:
            attrs["paraPrIDRef"] = para_pr
        elif cursor["table_label"]:
            if self.justify_parapr is None:
                raise LookupError("insert_text:justify")
            # T10: a T8 split body paragraph must not inherit centered label paraPr.
            attrs["paraPrIDRef"] = self.justify_parapr
        para = ET.Element(cursor["p_tag"], attrs)
        self._append_lineseg(cursor, para, charpr or cursor["charpr"])
        cursor["parent"].insert(cursor["insert_at"], para)
        cursor["insert_at"] += 1
        cursor["current"] = para
        self._track_inserted(cursor["section"], para)
        self.dirty.add(cursor["section"])
        return para

    def _append_run(self, cursor, para, text, bold, normal_charpr=None, bold_charpr=None):
        if not text:
            return
        charpr = ((bold_charpr or self.bold_charpr) if bold
                  else (normal_charpr or cursor["charpr"]))
        if bold and charpr is None:
            raise LookupError("insert_text:bold")
        attrs = {"charPrIDRef": charpr} if charpr is not None else {}
        run = self._new_run(cursor, para, attrs)
        text_node = ET.SubElement(run, cursor["t_tag"])
        text_node.text = text
        self._append_lineseg(cursor, para, charpr)

    @staticmethod
    def _segment_lines(op):
        segments = op.get("segments")
        if segments is None:
            segments = [{"text": op["text"], "bold": False}]
        lines = [[]]
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise ValueError("insert_text segments require string text values")
            bold = bool(segment.get("bold"))
            parts = segment["text"].replace("\r\n", "\n").replace("\r", "\n").split("\n")
            for index, part in enumerate(parts):
                if part:
                    lines[-1].append((part, bold))
                if index < len(parts) - 1:
                    lines.append([])
        return lines

    def insert_text(self, cursor, op):
        lines = self._segment_lines(op)
        normal_charpr = cursor["charpr"]
        bold_charpr = self.bold_charpr
        point_size = op.get("pt")
        if point_size is not None:
            if (not isinstance(point_size, (int, float)) or isinstance(point_size, bool)
                    or point_size <= 0):
                raise LookupError("insert_text")
            target_height = round(point_size * 100)
            normal_charpr = self._nearest_charpr(self.normal_charprs, target_height)
            bold_charpr = self._nearest_charpr(self.bold_charprs, target_height)
            if normal_charpr is None:
                raise LookupError("insert_text")
        last = None
        for line_number, runs in enumerate(lines):
            if line_number == 0 and cursor["current"] is not None:
                para = cursor["current"]
            else:
                # T8: creating this sibling paragraph is the XML equivalent of
                # BreakPara before body text; the label paragraph remains untouched.
                para = self._new_paragraph(cursor, charpr=normal_charpr)
            for text, bold in runs:
                self._append_run(cursor, para, text, bold, normal_charpr, bold_charpr)
            last = para
        cursor["charpr"] = normal_charpr
        cursor["current"] = None if op.get("break_after") else last

    def _charpr_height(self, charpr_id):
        for height, style_id in self.normal_charprs + self.bold_charprs:
            if style_id == charpr_id:
                return height
        return None

    @staticmethod
    def _nearest_charpr(styles, target_height):
        if not styles:
            return None
        return min(styles, key=lambda item: abs(item[0] - target_height))[1]

    def _charpr_at_height(self, target_height):
        return next((style_id for height, style_id in self.normal_charprs
                     if height == target_height), None)

    @staticmethod
    def _style_fingerprint(node):
        clone = copy.deepcopy(node)
        clone.attrib.pop("id", None)
        return ET.tostring(clone, encoding="utf-8")

    def _line_spacing_variant(self, base_id, percent):
        para_properties = next((node for node in self.header.getroot().iter()
                                if local_name(node.tag) == "paraProperties"), None)
        if para_properties is None:
            raise LookupError("set_line_spacing:paraProperties")
        para_prs = [node for node in para_properties
                    if local_name(node.tag) == "paraPr"]
        base = next((node for node in para_prs if node.get("id") == base_id), None)
        if base is None:
            raise LookupError("set_line_spacing:paraPr")

        candidate = copy.deepcopy(base)
        spacing_nodes = [node for node in candidate.iter()
                         if local_name(node.tag) == "lineSpacing"]
        if not spacing_nodes:
            spacing_nodes = [ET.SubElement(
                candidate, sibling_tag(candidate.tag, "lineSpacing"))]
        for spacing in spacing_nodes:
            spacing.set("type", "PERCENT")
            spacing.set("value", str(percent))
            spacing.set("unit", "HWPUNIT")

        wanted = self._style_fingerprint(candidate)
        for existing in para_prs:
            if self._style_fingerprint(existing) == wanted:
                return existing.get("id")

        numeric_ids = [int(node.get("id")) for node in para_prs
                       if (node.get("id") or "").isdigit()]
        new_id = str(max(numeric_ids, default=-1) + 1)
        candidate.set("id", new_id)
        para_properties.append(candidate)
        para_properties.set("itemCnt", str(len(para_prs) + 1))
        self.header_dirty = True
        return new_id

    def set_line_spacing(self, cursor, op):
        try:
            percent = int(op.get("percent", 160))
        except (TypeError, ValueError):
            raise LookupError("set_line_spacing")
        if percent <= 0:
            raise LookupError("set_line_spacing")

        if op.get("all", True):
            targets = list(self.inserted_paragraphs)
            note = ("document-wide line spacing applied only to paragraphs inserted "
                    "by xml_backend this run; form-owned paragraphs were preserved")
            partial = True
        else:
            current = cursor.get("current") if cursor is not None else None
            targets = [(section_name, para) for section_name, para
                       in self.inserted_paragraphs if para is current]
            partial = not targets
            note = ("current paragraph was form-owned; line spacing was not changed"
                    if partial else None)

        changed = 0
        variants = {}
        for section_name, para in targets:
            base_id = para.get("paraPrIDRef")
            if base_id is None:
                continue
            key = (base_id, percent)
            if key not in variants:
                variants[key] = self._line_spacing_variant(base_id, percent)
            new_id = variants[key]
            if para.get("paraPrIDRef") != new_id:
                para.set("paraPrIDRef", new_id)
                changed += 1
                self.dirty.add(section_name)
        result = {"line_spacing_percent": percent, "paragraphs": changed}
        if partial:
            result.update({"partial": True, "note": note})
        return result

    def insert_equation(self, cursor, op):
        script = op.get("hwpeqn")
        if not balanced_equation_script(script):
            raise LookupError("insert_equation")
        base_pt = op.get("base_pt")
        equation_charpr = cursor["charpr"]
        requested_height = None
        if base_pt is not None:
            if (not isinstance(base_pt, (int, float)) or isinstance(base_pt, bool)
                    or base_pt <= 0):
                raise LookupError("insert_equation")
            requested_height = round(base_pt * 100)
            equation_charpr = self._nearest_charpr(self.normal_charprs, requested_height)
            if equation_charpr is None:
                raise LookupError("insert_equation")
        if op.get("display"):
            if self.center_parapr is None or self.justify_parapr is None:
                raise LookupError("insert_equation")
            para = self._new_paragraph(cursor, self.center_parapr, equation_charpr)
            run = self._new_run(cursor, para, {"charPrIDRef": equation_charpr})
        else:
            para = cursor["current"] or cursor["anchor_para"]
            if cursor["current"] is None:
                run = cursor["anchor_run"]
            else:
                runs = [child for child in para if local_name(child.tag) == "run"]
                run = runs[-1] if runs else self._new_run(
                    cursor, para, {"charPrIDRef": cursor["charpr"]})
        charpr = first_ref(run, "charPrIDRef") or cursor["charpr"]
        height = self._charpr_height(charpr)
        if height is None:
            raise LookupError("insert_equation")
        if requested_height is not None:
            height = requested_height
        # Hancom stores the rendered bounding box.  A COM-free writer cannot run
        # the equation layout engine, but non-zero conservative dimensions are
        # materially safer than the synthetic slice-2 zero box.
        visual_length = len(re.sub(r"[{}\[\]`]", "", script))
        equation_width = max(height, round(visual_length * height * 0.22))
        usable_width = self._section_usable_width(cursor)
        if usable_width:
            equation_width = min(equation_width, usable_width)
        over_count = script.count("over")
        if over_count == 0:
            equation_height = round(height * 1.365)
            equation_baseline = "76"
        elif over_count >= 2 and "," not in script:
            equation_height = round(height * 2.452)
            equation_baseline = "61"
        else:
            equation_height = round(height * 2.25)
            equation_baseline = "66"
        equation = ET.SubElement(run, sibling_tag(cursor["p_tag"], "equation"), {
            "id": str(self.next_object_id), "zOrder": str(self.next_zorder),
            "numberingType": "EQUATION",
            "textWrap": "TOP_AND_BOTTOM", "textFlow": "BOTH_SIDES", "lock": "0",
            "dropcapstyle": "None", "version": "Equation Version 60",
            "baseLine": equation_baseline, "textColor": "#000000", "baseUnit": str(height),
            "lineMode": "CHAR", "font": "HancomEQN",
        })
        self.next_object_id += 1
        self.next_zorder += 1
        ET.SubElement(equation, sibling_tag(cursor["p_tag"], "sz"), {
            "width": str(equation_width), "height": str(equation_height),
            "widthRelTo": "ABSOLUTE",
            "heightRelTo": "ABSOLUTE", "protect": "0",
        })
        ET.SubElement(equation, sibling_tag(cursor["p_tag"], "pos"), {
            "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
            "allowOverlap": "0", "holdAnchorAndSO": "0",
            "vertRelTo": "PARA", "horzRelTo": "PARA", "vertAlign": "TOP",
            "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0",
        })
        ET.SubElement(equation, sibling_tag(cursor["p_tag"], "outMargin"), {
            "left": "56", "right": "56", "top": "0", "bottom": "0",
        })
        comment = ET.SubElement(equation, sibling_tag(cursor["p_tag"], "shapeComment"))
        comment.text = "수식입니다."
        script_node = ET.SubElement(equation, sibling_tag(cursor["p_tag"], "script"))
        script_node.text = script
        # EquationCreate leaves a text cursor after the control in the same run.
        ET.SubElement(run, cursor["t_tag"])
        self.dirty.add(cursor["section"])
        cursor["current"] = (self._new_paragraph(cursor, self.justify_parapr)
                             if op.get("display") else para)

    def _section_usable_width(self, cursor):
        root = self.sections[cursor["section"]].getroot()
        page_pr = next((node for node in root.iter()
                        if local_name(node.tag) == "pagePr"), None)
        margin = next((node for node in page_pr.iter()
                       if local_name(node.tag) == "margin"), None) if page_pr is not None else None
        if page_pr is None or margin is None:
            return None
        try:
            width = int(page_pr.get("width"))
            left = int(margin.get("left", "0"))
            right = int(margin.get("right", "0"))
            gutter = int(margin.get("gutter", "0"))
        except (TypeError, ValueError):
            return None
        usable = width - left - right - gutter - round(2 * HWPUNIT_PER_MM)
        return usable if usable > 0 else None

    @staticmethod
    def _column_widths(total_width, ratios):
        ratio_sum = sum(ratios)
        widths = [round(total_width * ratio / ratio_sum) for ratio in ratios[:-1]]
        widths.append(total_width - sum(widths))
        return widths

    @staticmethod
    def _image_info(data):
        if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            if width and height:
                return width, height, "image/png", "png"
            raise LookupError("insert_picture:dimensions")
        if len(data) >= 4 and data[:2] == b"\xff\xd8":
            index = 2
            sof_markers = {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }
            while index + 4 <= len(data):
                while index < len(data) and data[index] != 0xFF:
                    index += 1
                while index < len(data) and data[index] == 0xFF:
                    index += 1
                if index >= len(data):
                    break
                marker = data[index]
                index += 1
                if marker in {0x01, 0xD8, 0xD9}:
                    continue
                if index + 2 > len(data):
                    break
                segment_length = struct.unpack(">H", data[index:index + 2])[0]
                if segment_length < 2 or index + segment_length > len(data):
                    break
                if marker in sof_markers and segment_length >= 7:
                    height, width = struct.unpack(">HH", data[index + 3:index + 7])
                    if width and height:
                        return width, height, "image/jpeg", "jpg"
                index += segment_length
        raise LookupError("insert_picture:format")

    def _next_image_id(self):
        names = set(self.contents) | set(self.added_members)
        ids = []
        for name in names:
            match = re.search(r"(?:^|/)image(\d+)\.[^/]+$", name,
                              flags=re.IGNORECASE)
            if match:
                ids.append(int(match.group(1)))
        for tree in [self.header, *self.package_trees.values(), *self.sections.values()]:
            for node in tree.getroot().iter():
                for value in node.attrib.values():
                    match = re.fullmatch(r"image(\d+)", value, flags=re.IGNORECASE)
                    if match:
                        ids.append(int(match.group(1)))
        return max(ids, default=0) + 1

    @staticmethod
    def _set_collection_count(collection, count):
        key = next((key for key in collection.attrib
                    if local_name(key).lower() in {"itemcnt", "count"}), "itemCnt")
        collection.set(key, str(count))

    def _register_header_bindata(self, image_ref, member_name, mime, extension):
        collection = next((node for node in self.header.getroot().iter()
                           if local_name(node.tag).lower() == "bindatalist"), None)
        if collection is None:
            return False
        entries = list(collection)
        if entries:
            entry = ET.Element(entries[-1].tag, dict(entries[-1].attrib))
        else:
            entry = ET.Element(sibling_tag(collection.tag, "binData"))
        replacements = {
            "id": image_ref, "href": member_name, "path": member_name,
            "media-type": mime, "mediatype": mime, "format": extension,
            "bindata": image_ref, "storageid": image_ref,
        }
        seen = set()
        for key in list(entry.attrib):
            lname = local_name(key).lower()
            if lname in replacements:
                entry.set(key, replacements[lname])
                seen.add(lname)
        if "id" not in seen:
            entry.set("id", image_ref)
        if "href" not in seen and "path" not in seen:
            entry.set("href", member_name)
        if "media-type" not in seen and "mediatype" not in seen:
            entry.set("media-type", mime)
        collection.append(entry)
        self._set_collection_count(collection, len(entries) + 1)
        self.header_dirty = True
        return True

    def _register_content_hpf(self, image_ref, member_name, mime, data):
        name = "Contents/content.hpf"
        tree = self.package_trees.get(name)
        if tree is None:
            return False
        manifest = next((node for node in tree.getroot().iter()
                         if local_name(node.tag) == "manifest"), None)
        if manifest is None:
            return False
        item = ET.Element(sibling_tag(manifest.tag, "item"), {
            "id": image_ref, "href": member_name, "media-type": mime,
            "isEmbeded": "1",
            "hashkey": base64.b64encode(hashlib.md5(data).digest()).decode("ascii"),
        })
        children = list(manifest)
        insert_at = next((index for index, child in enumerate(children)
                          if (child.get("href") or "").startswith("Contents/section")),
                         len(children))
        manifest.insert(insert_at, item)
        self.package_dirty.add(name)
        return True

    @staticmethod
    def _manifest_attr_name(entry, wanted, namespace):
        return next((key for key in entry.attrib if local_name(key) == wanted),
                    f"{{{namespace}}}{wanted}" if namespace else wanted)

    def _register_odf_manifest(self, member_name, mime):
        name = "META-INF/manifest.xml"
        tree = self.package_trees.get(name)
        if tree is None:
            return False
        entries = [node for node in tree.getroot().iter()
                   if local_name(node.tag) == "file-entry"]
        # Hancom's current real archive keeps this file empty.  Only participate
        # when the source archive already uses ODF file-entry registrations.
        if not entries:
            return False
        namespace = (tree.getroot().tag.rsplit("}", 1)[0][1:]
                     if "}" in tree.getroot().tag else "")
        template = entries[-1]
        attrs = {
            self._manifest_attr_name(template, "media-type", namespace): mime,
            self._manifest_attr_name(template, "full-path", namespace): member_name,
        }
        tree.getroot().append(ET.Element(sibling_tag(template.tag, "file-entry"), attrs))
        self.package_dirty.add(name)
        return True

    def _register_image(self, image_ref, member_name, mime, extension, data):
        registrations = []
        if self._register_header_bindata(image_ref, member_name, mime, extension):
            registrations.append("header.xml")
        if self._register_content_hpf(image_ref, member_name, mime, data):
            registrations.append("content.hpf")
        if self._register_odf_manifest(member_name, mime):
            registrations.append("META-INF/manifest.xml")
        if not registrations:
            raise LookupError("insert_picture:manifest")
        self.added_members[member_name] = data
        return registrations

    def insert_picture(self, cursor, op):
        path = Path(op.get("path", ""))
        if not path.is_file():
            raise LookupError("insert_picture:path")
        data = path.read_bytes()
        pixel_width, pixel_height, mime, extension = self._image_info(data)

        if "width_mm" in op:
            width_value = op["width_mm"]
            if (not isinstance(width_value, (int, float)) or isinstance(width_value, bool)
                    or width_value <= 0):
                raise LookupError("insert_picture:width")
            width = round(width_value * HWPUNIT_PER_MM)
            width_mm = float(width_value)
        else:
            width_value = op.get("width_hwpunit", op.get("width_hwp", op.get("width")))
            unit = str(op.get("unit") or "HWPUNIT").upper()
            if (not isinstance(width_value, (int, float)) or isinstance(width_value, bool)
                    or width_value <= 0):
                raise LookupError("insert_picture:width")
            if unit in {"MM", "MILLIMETER", "MILLIMETERS"}:
                width = round(width_value * HWPUNIT_PER_MM)
                width_mm = float(width_value)
            elif unit == "HWPUNIT":
                width = round(width_value)
                width_mm = width / HWPUNIT_PER_MM
            else:
                raise LookupError("insert_picture:unit")
        height = max(1, round(width * pixel_height / pixel_width))

        image_number = self._next_image_id()
        image_ref = f"image{image_number}"
        member_name = f"BinData/{image_ref}.{extension}"
        registrations = self._register_image(
            image_ref, member_name, mime, extension, data)

        body_charpr = cursor["charpr"]
        if body_charpr is None:
            raise LookupError("insert_picture:charPr")
        own_paragraph = op.get("own_paragraph", True)
        if own_paragraph:
            if self.center_parapr is None or self.justify_parapr is None:
                raise LookupError("insert_picture:paraPr")
            para = self._new_paragraph(cursor, self.center_parapr, body_charpr)
            run = self._new_run(cursor, para, {"charPrIDRef": body_charpr})
        else:
            para = cursor["current"] or cursor["anchor_para"]
            if cursor["current"] is None:
                run = cursor["anchor_run"]
            else:
                runs = [child for child in para if local_name(child.tag) == "run"]
                run = runs[-1] if runs else self._new_run(
                    cursor, para, {"charPrIDRef": body_charpr})

        object_id = self.next_object_id
        pic = ET.SubElement(run, sibling_tag(cursor["p_tag"], "pic"), {
            "id": str(object_id), "zOrder": str(self.next_zorder),
            "numberingType": "PICTURE", "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None",
            "href": "", "groupLevel": "0", "instid": str(object_id), "reverse": "0",
        })
        self.next_object_id += 1
        self.next_zorder += 1
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "offset"), {"x": "0", "y": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "orgSz"), {
            "width": str(width), "height": str(height)})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "curSz"), {
            "width": "0", "height": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "flip"), {
            "horizontal": "0", "vertical": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "rotationInfo"), {
            "angle": "0", "centerX": str(width // 2), "centerY": str(height // 2),
            "rotateimage": "1"})
        rendering = ET.SubElement(pic, sibling_tag(cursor["p_tag"], "renderingInfo"))
        matrix_attrs = {"e1": "1", "e2": "0", "e3": "0",
                        "e4": "0", "e5": "1", "e6": "0"}
        for name in ("transMatrix", "scaMatrix", "rotMatrix"):
            ET.SubElement(rendering, f"{{{HC_NS}}}{name}", matrix_attrs)
        ET.SubElement(pic, f"{{{HC_NS}}}img", {
            "binaryItemIDRef": image_ref, "bright": "0", "contrast": "0",
            "effect": "REAL_PIC", "alpha": "0"})
        rect = ET.SubElement(pic, sibling_tag(cursor["p_tag"], "imgRect"))
        for name, x, y in (("pt0", 0, 0), ("pt1", width, 0),
                           ("pt2", width, height), ("pt3", 0, height)):
            ET.SubElement(rect, f"{{{HC_NS}}}{name}", {"x": str(x), "y": str(y)})
        dim_width = max(1, round(pixel_width * HWPUNIT_PER_PIXEL_96_DPI))
        dim_height = max(1, round(pixel_height * HWPUNIT_PER_PIXEL_96_DPI))
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "imgClip"), {
            "left": "0", "right": str(dim_width), "top": "0", "bottom": str(dim_height)})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "inMargin"), {
            "left": "0", "right": "0", "top": "0", "bottom": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "imgDim"), {
            "dimwidth": str(dim_width), "dimheight": str(dim_height)})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "effects"))
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "sz"), {
            "width": str(width), "height": str(height), "widthRelTo": "ABSOLUTE",
            "heightRelTo": "ABSOLUTE", "protect": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "pos"), {
            "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
            "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
            "horzRelTo": "COLUMN", "vertAlign": "TOP", "horzAlign": "LEFT",
            "vertOffset": "0", "horzOffset": "0"})
        ET.SubElement(pic, sibling_tag(cursor["p_tag"], "outMargin"), {
            "left": "0", "right": "0", "top": "0", "bottom": "0"})
        comment = ET.SubElement(pic, sibling_tag(cursor["p_tag"], "shapeComment"))
        comment.text = (f"Picture.\nOriginal file: {path.name}\n"
                        f"Original size: {pixel_width} x {pixel_height} pixels")
        ET.SubElement(run, cursor["t_tag"])
        self.dirty.add(cursor["section"])

        caption = op.get("caption")
        if own_paragraph or caption is not None:
            if self.justify_parapr is None:
                raise LookupError("insert_picture:paraPr")
            caption_charpr = self._charpr_at_height(900) or body_charpr
            following = self._new_paragraph(
                cursor, self.justify_parapr, caption_charpr if caption is not None else body_charpr)
            if caption is not None:
                if not isinstance(caption, str):
                    raise LookupError("insert_picture:caption")
                self._append_run(cursor, following, caption, False,
                                 normal_charpr=caption_charpr)
                cursor["current"] = None
        else:
            cursor["current"] = para
        return {"picture": str(path.resolve()), "binary_item": image_ref,
                "member": member_name, "width_mm": width_mm,
                "width_hwpunit": width, "height_hwpunit": height,
                "pixel_size": [pixel_width, pixel_height],
                "registrations": registrations, "own_paragraph": bool(own_paragraph)}

    def insert_table(self, cursor, op):
        data = op.get("data")
        if (not isinstance(data, list) or not data or
                any(not isinstance(row, list) or not row for row in data)):
            raise LookupError("insert_table")
        cols = len(data[0])
        if any(len(row) != cols for row in data):
            raise LookupError("insert_table")
        ratios = op.get("col_ratios")
        if ratios is None:
            ratios = [1] * cols
        if (not isinstance(ratios, list) or len(ratios) != cols or
                any(not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
                    for value in ratios)):
            raise LookupError("insert_table")
        total_width = self._section_usable_width(cursor)
        if total_width is None or self.justify_parapr is None:
            raise LookupError("insert_table")
        self._ensure_table_border_fill()
        font_pt = op.get("font_pt")
        if font_pt is not None:
            if not isinstance(font_pt, (int, float)) or isinstance(font_pt, bool) or font_pt <= 0:
                raise LookupError("insert_table")
            target_height = round(font_pt * 100)
            body_charpr = self._nearest_charpr(self.normal_charprs, target_height)
        else:
            body_charpr = cursor["charpr"]
        if body_charpr is None:
            raise LookupError("insert_table")

        widths = self._column_widths(total_width, ratios)
        body_height = self._charpr_height(body_charpr)
        row_height = body_height + 282 if body_height is not None else 282
        table_charpr = cursor["charpr"] or body_charpr
        para = self._new_paragraph(cursor, charpr=table_charpr)
        run = self._new_run(cursor, para, {"charPrIDRef": table_charpr})
        table = ET.SubElement(run, sibling_tag(cursor["p_tag"], "tbl"), {
            "id": str(self.next_object_id), "zOrder": str(self.next_zorder),
            "numberingType": "TABLE",
            "textWrap": "TOP_AND_BOTTOM", "textFlow": "BOTH_SIDES", "lock": "0",
            "dropcapstyle": "None",
            "pageBreak": "CELL", "repeatHeader": "1", "rowCnt": str(len(data)),
            "colCnt": str(cols), "cellSpacing": "0", "borderFillIDRef": self.border_fill,
            "noAdjust": "0",
        })
        self.next_object_id += 1
        self.next_zorder += 1
        ET.SubElement(table, sibling_tag(cursor["p_tag"], "sz"), {
            "width": str(total_width), "height": str(row_height * len(data)),
            "widthRelTo": "ABSOLUTE",
            "heightRelTo": "ABSOLUTE", "protect": "0",
        })
        ET.SubElement(table, sibling_tag(cursor["p_tag"], "pos"), {
            "treatAsChar": "1" if op.get("treat_as_char", True) else "0",
            "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0",
            "holdAnchorAndSO": "0",
            "vertRelTo": "PARA", "horzRelTo": "PARA", "vertAlign": "TOP",
            "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0",
        })
        ET.SubElement(table, sibling_tag(cursor["p_tag"], "outMargin"), {
            "left": "141", "right": "141", "top": "141", "bottom": "141",
        })
        ET.SubElement(table, sibling_tag(cursor["p_tag"], "inMargin"), {
            "left": "510", "right": "510", "top": "141", "bottom": "141",
        })
        for row_index, row_data in enumerate(data):
            row = ET.SubElement(table, sibling_tag(cursor["p_tag"], "tr"))
            for col_index, value in enumerate(row_data):
                cell = ET.SubElement(row, sibling_tag(cursor["p_tag"], "tc"), {
                    "name": "", "header": "0",
                    "hasMargin": "0", "protect": "0", "editable": "0", "dirty": "0",
                    "borderFillIDRef": self.border_fill,
                })
                sublist = ET.SubElement(cell, sibling_tag(cursor["p_tag"], "subList"), {
                    "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK",
                    "vertAlign": "CENTER", "linkListIDRef": "0", "linkListNextIDRef": "0",
                    "textWidth": "0", "textHeight": "0", "hasTextRef": "0", "hasNumRef": "0",
                })
                cell_para = ET.SubElement(sublist, cursor["p_tag"], {
                    "id": "0", "paraPrIDRef": self.justify_parapr,
                    "styleIDRef": "0", "pageBreak": "0", "columnBreak": "0",
                    "merged": "0",
                })
                self._track_inserted(cursor["section"], cell_para)
                cell_run = ET.SubElement(cell_para, cursor["run_tag"], {
                    "charPrIDRef": body_charpr})
                cell_text = ET.SubElement(cell_run, cursor["t_tag"])
                cell_text.text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                self._append_lineseg(cursor, cell_para, body_charpr,
                                     max(1, widths[col_index] - 1020), 0.6)
                ET.SubElement(cell, sibling_tag(cursor["p_tag"], "cellAddr"), {
                    "colAddr": str(col_index), "rowAddr": str(row_index)})
                ET.SubElement(cell, sibling_tag(cursor["p_tag"], "cellSpan"), {
                    "colSpan": "1", "rowSpan": "1"})
                ET.SubElement(cell, sibling_tag(cursor["p_tag"], "cellSz"), {
                    "width": str(widths[col_index]), "height": "282"})
                ET.SubElement(cell, sibling_tag(cursor["p_tag"], "cellMargin"), {
                    "left": "510", "right": "510", "top": "141", "bottom": "141"})
        ET.SubElement(run, cursor["t_tag"])
        self.dirty.add(cursor["section"])
        post_table_para = self._new_paragraph(cursor, self.justify_parapr)
        caption = op.get("caption")
        if caption is not None:
            if not isinstance(caption, str):
                raise LookupError("insert_table")
            self._append_run(cursor, post_table_para, caption, False)
            cursor["current"] = None
        else:
            cursor["current"] = post_table_para


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        emit(summary(False), 2)
        raise SystemExit(2)


def parse_args(argv=None):
    parser = JsonArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    edit = sub.add_parser("edit")
    edit.add_argument("--file", required=True)
    edit.add_argument("--ops", required=True)
    edit.add_argument("--save-as", required=True)
    edit.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        source = Path(args.file)
        destination = Path(args.save_as)
        if not source.is_file():
            raise ValueError(f"input file not found: {source}")
        if source.resolve() == destination.resolve():
            raise ValueError("--save-as must differ from --file")
        ops = load_ops(args.ops)

        unsupported = []
        for op in ops:
            name = op["op"]
            if name not in SUPPORTED_OPS and name not in unsupported:
                unsupported.append(name)
            elif name == "insert_equation" and not balanced_equation_script(op.get("hwpeqn")):
                if name not in unsupported:
                    unsupported.append(name)
        if unsupported:
            return emit(summary(False, unsupported=unsupported), 4)

        document = HwpxDocument(source)
        if document.bold_charpr is None:
            if any(op["op"] == "insert_text" and
                   any(bool(seg.get("bold")) for seg in op.get("segments", [])
                       if isinstance(seg, dict)) for op in ops):
                return emit(summary(False, unsupported=["insert_text:bold"]), 4)

        applied = 0
        anchors_missing = []
        results = []
        partial_notes = []
        cursor = None
        for op in ops:
            name = op["op"]
            if name == "goto_text":
                cursor = document.goto_text(op["text"])
                if cursor is None:
                    anchors_missing.append(op["text"])
                else:
                    applied += 1
                    results.append({"op": name, "anchor": op["text"]})
                continue
            if anchors_missing:
                continue
            try:
                op_result = None
                if name == "replace_all":
                    op_result = document.replace_all(op)
                elif name == "page_binding":
                    op_result = document.page_binding(op)
                elif name == "insert_blank_before":
                    op_result = document.insert_blank_before(op.get("text"))
                    if op_result is None:
                        anchors_missing.append(op.get("text"))
                        continue
                elif name == "set_line_spacing":
                    op_result = document.set_line_spacing(cursor, op)
                else:
                    if cursor is None:
                        raise ValueError(
                            f"{name} requires a preceding successful goto_text")
                if name == "insert_text":
                    document.insert_text(cursor, op)
                elif name == "insert_equation":
                    document.insert_equation(cursor, op)
                elif name == "insert_table":
                    document.insert_table(cursor, op)
                elif name == "insert_picture":
                    op_result = document.insert_picture(cursor, op)
            except LookupError as exc:
                missing_feature = str(exc)
                if missing_feature not in unsupported:
                    unsupported.append(missing_feature)
                break
            applied += 1
            result_entry = {"op": name}
            if op_result:
                result_entry.update(op_result)
                if op_result.get("partial") and op_result.get("note"):
                    partial_notes.append(op_result["note"])
            results.append(result_entry)

        if unsupported:
            return emit(summary(False, applied, unsupported, anchors_missing,
                                results, partial_notes), 4)
        if anchors_missing:
            return emit(summary(False, applied, [], anchors_missing,
                                results, partial_notes), 3)

        document.save(destination)
        return emit(summary(True, applied, results=results, partial=partial_notes), 0)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile,
            ET.ParseError) as exc:
        return emit(summary(False), 2)


if __name__ == "__main__":
    raise SystemExit(main())
