# -*- coding: utf-8 -*-
"""DGN V8 elements that cadkit keeps as Unknown get real geometry.

Layouts were confirmed on a MicroStation V8 drawing with 68 dimension leaders
(type 33) and 66 manhole cones (type 23); these tests use synthetic records with
the same layout so no client drawing is needed.
"""

import importlib.util
import math
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UOR = 10000.0


def load_dgn():
    spec = importlib.util.spec_from_file_location(
        "muuntaja_dgn_standalone", ROOT / "qgis_plugin" / "muuntaja_qgis" / "dgn.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dgn = load_dgn()


def element(code, low, high, length, fields, attribute_offset=None):
    raw = bytearray(length)
    struct.pack_into("<III", raw, 0, code, length // 2, (attribute_offset or length) // 2)
    struct.pack_into("<3q", raw, 0x38, *[round(v * UOR) for v in low])
    struct.pack_into("<3q", raw, 0x50, *[round((h - l) * UOR) for l, h in zip(low, high)])
    for offset, (fmt, values) in fields.items():
        struct.pack_into(fmt, raw, offset, *values)
    return list(raw)


def entity(code, raw, layer="JOHTO"):
    return {"id": 1, "layer": layer, "color": {"type": "by_layer"}, "linetype": None,
            "lineweight": {"type": "by_layer"}, "visible": True,
            "kind": {"type": "unknown", "type_name": f"dgn.type_{code}"}, "attributes": [],
            "props": {"dgn.type": code}, "raw": {"type_code": code, "bytes": raw}}


def document(*entities):
    return {"format": "dgn_v8", "layers": [], "blocks": [], "models": [{
        "name": "Default", "is_3d": True, "entities": list(entities),
        "props": {"dgn.uor_per_master": UOR, "dgn.global_origin": [0.0, 0.0, 0.0]}}]}


def cone(centre=(25495437.9755, 6674548.243), bottom=5.89, top=7.91, radius=0.5):
    x, y = centre
    return element(23, (x - radius, y - radius, bottom), (x + radius, y + radius, top), 0xD0, {
        0x68: ("<I", (1,)),
        0x70: ("<4d", (-1.0, 0.0, 0.0, 0.0)),
        0x90: ("<4d", (x * UOR, y * UOR, bottom * UOR, radius * UOR)),
        0xB0: ("<4d", (x * UOR, y * UOR, top * UOR, radius * UOR)),
    })


def leader(points, text=b"Sv 160 PVC", height=0.3):
    xs, ys, zs = zip(*points)
    fields = {0x98: ("<2d", (height * UOR, height * UOR)), 0xB4: ("<I", (len(points),)),
              0x1C8: ("<d", (-1.0,))}  # -1.0 = ... f0 bf: ei saa näkyä tekstinä
    for index, point in enumerate(points):
        fields[0x130 + 0x30 * index] = ("<3d", tuple(v * UOR for v in point))
    end = 0x1E8 + 2 * (len(text) + 1)
    fields[0x1E8] = (f"<{len(text) + 1}s{len(text) + 1}s", (text + b"\0", text + b"\0"))
    return element(33, (min(xs) - 0.3, min(ys) - 0.1, min(zs)), (max(xs) + 0.3, max(ys) + 0.5, max(zs)),
                   end + 0x20, fields, attribute_offset=end)


def test_cone_becomes_its_footprint_at_lid_level():
    data = document(entity(23, cone()))

    counts = dgn._reconstruct_unknown(data)

    assert counts == {(23, "decoded"): 1}
    kind = data["models"][0]["entities"][0]["kind"]
    assert kind["type"] == "polygon"
    ring = kind["exterior"]
    assert ring[0] == ring[-1] and len(ring) > 30
    for point in ring:
        assert math.hypot(point["x"] - 25495437.9755, point["y"] - 6674548.243) == pytest.approx(0.5, abs=1e-6)
        assert point["z"] == pytest.approx(7.91)


def test_dimension_leader_keeps_its_line_and_readable_text():
    points = [(25495438.9387, 6674549.0397, 6.77), (25495437.0302, 6674551.3514, 6.77),
              (25495438.7104, 6674552.7467, 6.77)]
    data = document(entity(33, leader(points)))

    counts = dgn._reconstruct_unknown(data)

    assert counts == {(33, "decoded"): 1}
    line, text = data["models"][0]["entities"][0]["kind"]["children"]
    assert line["kind"]["type"] == "polyline"
    assert [(v["position"]["x"], v["position"]["y"]) for v in line["kind"]["vertices"]] == \
        [pytest.approx(p[:2]) for p in points]
    assert text["kind"]["type"] == "text"
    assert text["kind"]["value"] == "Sv 160 PVC"
    assert text["kind"]["height"] == pytest.approx(0.3)
    assert -math.pi / 2 <= text["kind"]["rotation"] <= math.pi / 2
    assert text["layer"] == "JOHTO"


def test_leader_pointing_left_is_not_upside_down():
    points = [(10.0, 10.0, 0.0), (12.0, 12.0, 0.0), (9.0, 12.0, 0.0)]
    data = document(entity(33, leader(points, b"5.17")))

    dgn._reconstruct_unknown(data)

    text = data["models"][0]["entities"][0]["kind"]["children"][1]["kind"]
    assert text["value"] == "5.17"
    assert text["rotation"] == pytest.approx(0.0, abs=1e-9)
    assert text["position"]["x"] == pytest.approx(9.0)


def test_unknown_elements_inside_cells_are_replaced():
    cell = {"id": 2, "layer": "JOHTO", "color": {"type": "by_layer"}, "linetype": None,
            "lineweight": {"type": "by_layer"}, "visible": True, "attributes": [], "props": {"dgn.type": 2},
            "kind": {"type": "group", "group_kind": "cell", "name": "MANHOL", "origin": None,
                     "children": [entity(23, cone()), entity(23, cone(bottom=5.0, top=5.89))]}}
    data = document(cell)

    assert dgn._reconstruct_unknown(data) == {(23, "decoded"): 2}
    assert [c["kind"]["type"] for c in cell["kind"]["children"]] == ["polygon", "polygon"]


def test_undecodable_graphic_element_keeps_its_location():
    raw = element(36, (100.0, 200.0, 0.0), (102.0, 204.0, 2.0), 0x80, {})
    data = document(entity(36, raw))

    assert dgn._reconstruct_unknown(data) == {(36, "located"): 1}
    point = data["models"][0]["entities"][0]["kind"]["position"]
    assert (point["x"], point["y"], point["z"]) == pytest.approx((101.0, 202.0, 1.0))


def test_control_records_and_tags_are_left_alone():
    tag = entity(37, element(37, (0, 0, 0), (1, 1, 1), 0x80, {}))
    control = entity(66, element(66, (0, 0, 0), (1, 1, 1), 0x80, {}))
    data = document(tag, control)

    assert dgn._reconstruct_unknown(data) == {}
    assert all(e["kind"]["type"] == "unknown" for e in data["models"][0]["entities"])


def test_uor_offset_is_calibrated_from_decoded_lines():
    line = {"id": 3, "layer": "x", "color": {"type": "by_layer"}, "linetype": None,
            "lineweight": {"type": "by_layer"}, "visible": True, "attributes": [], "props": {},
            "kind": {"type": "line", "start": {"x": 1000.0, "y": 2000.0, "z": 0.0},
                     "end": {"x": 1001.0, "y": 2001.0, "z": 0.0}},
            "raw": {"type_code": 3, "bytes": element(3, (0, 0, 0), (1, 1, 0), 0x88, {})}}
    raw = element(36, (4.0, 4.0, 0.0), (6.0, 6.0, 0.0), 0x80, {})
    data = document(line, entity(36, raw))

    dgn._reconstruct_unknown(data)

    point = data["models"][0]["entities"][1]["kind"]["position"]
    assert (point["x"], point["y"]) == pytest.approx((1005.0, 2005.0))


def test_note_reports_what_was_reconstructed():
    note = dgn._reconstruction_note("topelius.dgn", {(33, "decoded"): 68, (23, "decoded"): 66,
                                                     (36, "located"): 1})
    assert "66 kartiota" in note and "68 mitoitusta" in note and "1 tyypin 36" in note


def test_readable_source_drops_handled_warnings(tmp_path, monkeypatch):
    data = document(entity(23, cone()))

    class FakeDocument:
        warnings = [{"code": "dgn.unknown_element.type_23", "message": "type 23 elements are kept as Unknown"},
                    {"code": "dgn.other", "message": "something else"}]

        def to_dict(self):
            return data

        @staticmethod
        def from_json(text):
            import json
            written = json.loads(text)
            assert "raw" not in json.dumps(written)
            return types_namespace(to_dxf=lambda: "0\nEOF\n")

    def types_namespace(**values):
        import types
        return types.SimpleNamespace(**values)

    kit = types_namespace(read=lambda path, keep_raw=False: FakeDocument() if keep_raw else None,
                          Document=FakeDocument)
    monkeypatch.setattr(dgn, "_cadkit", lambda: kit)
    notes = []

    output = dgn.readable_source(tmp_path / "x.dgn", tmp_path, notes)

    assert output.read_text() == "0\nEOF\n"
    assert any("kartiota" in note for note in notes)
    assert not any("type 23" in note for note in notes)
    assert any("something else" in note for note in notes)
