"""Generate tests/data/cad_sample.dxf (requires ezdxf).

    python tests/data/make_cad_sample.py tests/data/cad_sample.dxf R2000

cad_sample_r2000.dwg was converted from it with LibreDWG: dxf2dwg -o cad_sample_r2000.dwg cad_sample.dxf
"""
import ezdxf, sys
out = sys.argv[1]; version = sys.argv[2] if len(sys.argv) > 2 else "R2000"
doc = ezdxf.new(version, setup=True)
msp = doc.modelspace()
for name, color in (("Tiet", 1), ("Rakennukset", 5), ("Tekstit", 7), ("Puut", 3)):
    doc.layers.add(name, color=color)
X, Y = 385000.0, 6672000.0
msp.add_lwpolyline([(X, Y), (X + 100, Y + 20), (X + 200, Y)], dxfattribs={"layer": "Tiet"})
msp.add_line((X, Y + 50), (X + 200, Y + 50), dxfattribs={"layer": "Tiet", "color": 2})
msp.add_lwpolyline([(X + 10, Y + 10), (X + 40, Y + 10), (X + 40, Y + 40), (X + 10, Y + 40)], close=True, dxfattribs={"layer": "Rakennukset"})
hatch = msp.add_hatch(color=5, dxfattribs={"layer": "Rakennukset"})
hatch.paths.add_polyline_path([(X + 60, Y + 10), (X + 90, Y + 10), (X + 90, Y + 40), (X + 60, Y + 40)], is_closed=True)
msp.add_text("Kauppakatu", height=4, rotation=30, dxfattribs={"layer": "Tekstit"}).set_placement((X + 20, Y + 60))
msp.add_mtext("Talo A", dxfattribs={"layer": "Tekstit", "char_height": 2.5, "insert": (X + 12, Y + 25)})
msp.add_point((X + 150, Y + 80), dxfattribs={"layer": "Puut"})
msp.add_circle((X + 170, Y + 80), radius=3, dxfattribs={"layer": "Puut"})
msp.add_arc((X + 120, Y + 120), radius=10, start_angle=0, end_angle=180, dxfattribs={"layer": "Tiet"})
blk = doc.blocks.new(name="PUU")
blk.add_circle((0, 0), radius=1.5)
blk.add_line((-1.5, 0), (1.5, 0))
msp.add_blockref("PUU", (X + 180, Y + 90), dxfattribs={"layer": "Puut"})
msp.add_line((X, Y), (X + 1, Y + 1), dxfattribs={"layer": "Defpoints"})
msp.add_line((X, Y), (X + 2, Y + 2), dxfattribs={"layer": "0"})
doc.paperspace().add_line((0, 0), (100, 100), dxfattribs={"layer": "Tiet"})
doc.saveas(out)
