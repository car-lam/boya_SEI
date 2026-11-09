"""Render fotorrealista de la boya SEI con Blender (Cycles).

Antes: python boya.py   (genera renders/ensamble_stl/ con las piezas ya ubicadas)
Uso:   blender -b --factory-startup -P render_blender.py -- [--muestras 128] [--rapido]

Salida: renders/blender_exterior.png y renders/blender_interior.png
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

AQUI = Path(__file__).resolve().parent
ENS = AQUI / "renders" / "ensamble_stl"
MM = 0.001

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MUESTRAS = int(args[args.index("--muestras") + 1]) if "--muestras" in args else 128
RAPIDO = "--rapido" in args

escena_info = json.loads((ENS / "escena.json").read_text())
CALADO = escena_info["calado_mm"] * MM
COLORES = escena_info["colores"]

# acabado de cada pieza: (rugosidad, metálico)
ACABADO = {
    "powerbank": (0.35, 0.0), "webcam": (0.3, 0.0), "palo": (0.25, 0.0),
    "pynq": (0.4, 0.0), "psoc": (0.4, 0.0), "e220": (0.4, 0.0),
}
TAPA_Y_ARRIBA = {"tapa", "mastil_camara", "soporte_camara", "caseta_sensores", "palo",
                 "punta_palo", "imu_punta", "webcam"}


def srgb_a_lineal(hexcol):
    h = hexcol.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]


def material_pla(nombre, hexcol, rug=0.55, met=0.0):
    m = bpy.data.materials.new(nombre)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = srgb_a_lineal(hexcol)
    bsdf.inputs["Roughness"].default_value = rug
    bsdf.inputs["Metallic"].default_value = met
    return m


def limpiar():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def importar_piezas():
    objs = {}
    for stl in sorted(ENS.glob("*.stl")):
        bpy.ops.wm.stl_import(filepath=str(stl))
        o = bpy.context.selected_objects[0]
        o.name = stl.stem
        o.scale = (MM, MM, MM)
        me = o.data
        try:
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(35))
        except Exception:
            pass
        rug, met = ACABADO.get(stl.stem, (0.55, 0.0))
        me.materials.append(material_pla(f"mat_{stl.stem}", COLORES.get(stl.stem, "#cccccc"), rug, met))
        objs[stl.stem] = o
    return objs


def agua():
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, CALADO))
    p = bpy.context.object
    p.name = "agua"
    bpy.ops.object.modifier_add(type="SUBSURF")
    m = bpy.data.materials.new("agua")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.72, 0.86, 0.92, 1)
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.33
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    # ondas suaves con un bump de ruido
    ruido = nt.nodes.new("ShaderNodeTexNoise")
    ruido.inputs["Scale"].default_value = 18.0
    ruido.inputs["Detail"].default_value = 3.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(ruido.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    p.data.materials.append(m)

    # hueco del tamaño del casco: que no se vea agua dentro de la boya
    bpy.ops.mesh.primitive_cylinder_add(radius=0.1195, depth=0.2, location=(0, 0, CALADO), vertices=128)
    corte = bpy.context.object
    corte.name = "corte_agua"
    corte.hide_render = True
    corte.hide_viewport = True
    b = p.modifiers.new("hueco", "BOOLEAN")
    b.operation = "DIFFERENCE"
    b.object = corte
    b.solver = "EXACT"

    # fondo de la tina (da color al agua)
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, -0.35))
    f = bpy.context.object
    f.name = "fondo"
    f.data.materials.append(material_pla("fondo", "#5d8fa8", 0.8))


def regla():
    """Regla impresa (44 cm + ArUco) fija frente a la cámara, a ~45 cm."""
    alto, ancho = 0.50, 0.10
    x = 0.085 + 0.45
    z0 = -0.12  # parte sumergida
    bpy.ops.mesh.primitive_plane_add(size=1, location=(x, 0, z0 + alto / 2), rotation=(math.pi / 2, 0, -math.pi / 2))
    p = bpy.context.object
    p.name = "regla"
    p.scale = (ancho, alto, 1)
    bpy.ops.object.modifier_add(type="SOLIDIFY")
    p.modifiers["Solidify"].thickness = 0.006
    m = bpy.data.materials.new("regla")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.6
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(ENS / "regla_tex.png"))
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    p.data.materials.append(m)
    # poste que la sostiene
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x + 0.02, 0, z0 + (alto - 0.01) / 2))
    poste = bpy.context.object
    poste.scale = (0.03, 0.03, alto - 0.01)
    poste.data.materials.append(material_pla("poste", "#8a8f94", 0.5))


def luces_y_mundo():
    mundo = bpy.data.worlds.new("mundo")
    bpy.context.scene.world = mundo
    mundo.use_nodes = True
    bg = mundo.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.82, 0.86, 0.9, 1)
    bg.inputs["Strength"].default_value = 0.7

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 3), rotation=(math.radians(40), math.radians(15), math.radians(-35)))
    sol = bpy.context.object
    sol.data.energy = 3.5
    sol.data.angle = math.radians(4)

    bpy.ops.object.light_add(type="AREA", location=(-1.0, -1.2, 1.2))
    clave = bpy.context.object
    clave.data.energy = 120
    clave.data.size = 1.2
    apuntar(clave, Vector((0, 0, 0.15)))


def apuntar(obj, objetivo):
    d = objetivo - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camara(pos, objetivo, lente=50):
    bpy.ops.object.camera_add(location=pos)
    c = bpy.context.object
    c.data.lens = lente
    apuntar(c, Vector(objetivo))
    bpy.context.scene.camera = c
    return c


def configurar_render(ancho, alto):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 24 if RAPIDO else MUESTRAS
    sc.cycles.use_denoising = True
    sc.render.resolution_x = ancho // (2 if RAPIDO else 1)
    sc.render.resolution_y = alto // (2 if RAPIDO else 1)
    sc.render.film_transparent = False
    sc.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in [
        i.identifier for i in sc.view_settings.bl_rna.properties["look"].enum_items] else "None"


def render(archivo):
    bpy.context.scene.render.filepath = str(AQUI / "renders" / archivo)
    bpy.ops.render.render(write_still=True)
    print("render:", archivo)


def main():
    limpiar()
    objs = importar_piezas()
    agua()
    regla()
    luces_y_mundo()

    # 1) exterior: 3/4 desde atrás-izquierda, con la regla al fondo
    configurar_render(1600, 1400)
    cam = camara((-0.75, -1.05, 0.62), (0.18, 0.05, 0.2), lente=45)
    render("blender_exterior.png")

    # 2) interior: sin tapa ni lo que va encima, desde arriba
    for n in TAPA_Y_ARRIBA:
        if n in objs:
            objs[n].hide_render = True
    bpy.data.objects.remove(cam)
    configurar_render(1600, 1400)
    camara((-0.24, -0.30, 0.46), (0.0, 0.01, 0.05), lente=40)
    render("blender_interior.png")


main()
