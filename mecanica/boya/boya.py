#!/usr/bin/env python3
"""Boya SEI (MVP impreso en 3D) — modelo paramétrico en CadQuery.

Concepto: disco ancho y bajo (estable) + mástil de cámara + palo flexible del viento.
Todo lo electrónico va dentro del casco, sobre una bandeja removible:
  - powerbank abajo (lastre), PYNQ-Z2 en un estante encima,
  - PSoC 5LP (CY8CKIT-059), E220 e IMU de la base al costado.
La tapa cierra con o-ring de cordón de 3 mm y 8 tornillos M3 en insertos de latón.

Ejes: +X = lado de la cámara (apunta a la regla). Z hacia arriba, z = 0 en el fondo.

Uso (con el venv de CadQuery):
    python boya.py            # exporta STL/STEP, renders y resumen de flotación
    python boya.py --sin-render

Todas las medidas de placas son APROXIMADAS: medir con calibrador y ajustar abajo.
"""
import argparse
import json
import math
from pathlib import Path

import cadquery as cq

# ---------------------------------------------------------------- parámetros (mm)
D = 240.0            # diámetro del casco y la tapa (cama de 256 mm)
H_CASCO = 95.0       # alto del casco
CHAFLAN = 10.0       # chaflán del fondo
PARED = 4.0          # pared lateral
PISO = 4.0           # espesor del fondo
FLANGE = 16.0        # ancho del reborde superior (o-ring + tornillos)
T_TAPA = 5.0         # espesor de la tapa

ORING = 3.0                      # cordón de o-ring (NBR)
RANURA_W, RANURA_H = 4.0, 2.2    # ranura: ~27 % de compresión
R_RANURA = D / 2 - 6             # radio medio de la ranura
R_TORN = D / 2 - 12              # radio de los tornillos de la tapa
N_TORN = 8
INSERTO_D, INSERTO_L = 4.0, 7.0  # agujero para inserto M3 (ajustar a tu inserto)
M3_PASO = 3.4

# placas y piezas (APROXIMADO: medir)
PYNQ = (140.0, 87.0)             # PYNQ-Z2 (Farnell/Hackerboards: 87 × 140)
PYNQ_ALTO = 20.0                 # placa + componentes más altos (RJ45)
PSOC = (120.0, 30.0)             # CY8CKIT-059 entero (foro Infineon, aprox.)
E220 = (37.0, 21.0)
IMU = (27.0, 27.0)               # BNO055/BNO085 breakout, aprox.
POWERBANK = (150.0, 70.0, 25.0)  # 20 000 mAh típica: L × A × alto
WEBCAM = (72.0, 32.0, 30.0)      # tipo Logitech C270, aprox.

# mástil de cámara y palo del viento
MASTIL_L, MASTIL_OD, MASTIL_ID = 200.0, 32.0, 26.0
MASTIL_X = 85.0                  # posición del mástil sobre +X
PALO_D = 8.0                     # palo flexible (fibra de vidrio / carbono)
PALO_L = 450.0                   # solo para el render
SENSOR_X = -70.0                 # caseta de sensores de aire (BME680 + SCD41)
ANTENA_POS = (0.0, -85.0)

PLA = 1.24          # g/cm3
RELLENO = 0.7       # fracción efectiva de material impreso (paredes + relleno)

SALIDA = Path(__file__).parent


# ---------------------------------------------------------------- utilidades
def caja(lx, ly, lz, x=0, y=0, z=0):
    """Caja con la base en z y centrada en (x, y)."""
    return cq.Workplane("XY").box(lx, ly, lz, centered=(True, True, False)).translate((x, y, z))


def cilindro(r, h, x=0, y=0, z=0):
    return cq.Workplane("XY").circle(r).extrude(h).translate((x, y, z))


def polar(r, ang_deg):
    a = math.radians(ang_deg)
    return (r * math.cos(a), r * math.sin(a))


def marco(lx, ly, alto, pared=2.0, holgura=0.6):
    """Marco rectangular que abraza una placa de lx × ly."""
    ix, iy = lx + holgura, ly + holgura
    return caja(ix + 2 * pared, iy + 2 * pared, alto).cut(caja(ix, iy, alto))


ANG_TORN = [22.5 + 45 * k for k in range(N_TORN)]  # evita el mástil en 0°


# ---------------------------------------------------------------- piezas
def casco():
    R, H = D / 2, H_CASCO
    perfil = [(0, 0), (R - CHAFLAN, 0), (R, CHAFLAN), (R, H), (R - FLANGE, H),
              (R - FLANGE, H - 10), (R - PARED, H - 10 - (FLANGE - PARED)),
              (R - PARED, PISO + 4), (R - PARED - 4, PISO), (0, PISO)]
    s = cq.Workplane("XZ").polyline(perfil).close().revolve(360, (0, 0, 0), (0, 1, 0))

    # ranura del o-ring en la cara superior del reborde
    r0, r1 = R_RANURA - RANURA_W / 2, R_RANURA + RANURA_W / 2
    ranura = (cq.Workplane("XZ").polyline([(r0, H - RANURA_H), (r1, H - RANURA_H), (r1, H + 1), (r0, H + 1)])
              .close().revolve(360, (0, 0, 0), (0, 1, 0)))
    s = s.cut(ranura)

    # insertos M3 para la tapa
    for a in ANG_TORN:
        x, y = polar(R_TORN, a)
        s = s.cut(cilindro(INSERTO_D / 2, INSERTO_L + 1, x, y, H - INSERTO_L))

    # 3 orejas de amarre (lejos de la cámara), con cartela a 45° para imprimir sin soportes
    for a in (60, 180, 300):
        oreja = (cq.Workplane("XZ").polyline([(R - 3, H), (R + 12, H), (R + 12, H - 8), (R - 3, H - 23)])
                 .close().extrude(6, both=True))
        oreja = oreja.cut(cilindro(2.6, 30, R + 6.5, 0, H - 25))
        s = s.union(oreja.rotate((0, 0, 0), (0, 0, 1), a))

    # 3 torres en el piso para atornillar la bandeja
    for a in (90, 210, 330):
        x, y = polar(100, a)
        s = s.union(cilindro(5, 6, x, y, PISO)).cut(cilindro(INSERTO_D / 2, 6, x, y, PISO + 1))
    return s


def tapa():
    T = T_TAPA
    s = cilindro(D / 2, T)
    for a in ANG_TORN:
        x, y = polar(R_TORN, a)
        s = s.cut(cilindro(M3_PASO / 2, T + 1, x, y, -0.5))

    # base del mástil de la cámara: encaje Ø32 y paso del cable USB (Ø22)
    s = s.union(cilindro(22, 18, MASTIL_X, 0, T))
    s = s.cut(cilindro(MASTIL_OD / 2 + 0.2, 16, MASTIL_X, 0, T + 3))
    s = s.cut(cilindro(11, 30, MASTIL_X, 0, -1))

    # base del palo del viento (ciego: la tapa queda sellada)
    s = s.union(cilindro(12, 30, 0, 0, T)).cut(cilindro(PALO_D / 2 + 0.2, 27, 0, 0, T + 4))
    # pasacables del IMU de la punta, con collar contra el agua
    s = s.union(cilindro(5, 4, 0, 22, T)).cut(cilindro(2.5, 20, 0, 22, -1))

    # caseta de sensores: anillo de encaje, poste con ranuras para bridas, paso de cables
    s = s.union(cilindro(25.2, 6, SENSOR_X, 0, T)).cut(cilindro(22, 7, SENSOR_X, 0, T))
    poste = caja(3, 24, 35, SENSOR_X, 0, T)
    for zz in (12, 28):
        for yy in (-6, 6):
            poste = poste.cut(caja(4, 4, 2.4, SENSOR_X, yy, T + zz))
    s = s.union(poste).cut(cilindro(4, 20, SENSOR_X + 10, -12, -1))

    # pasamuros SMA de la antena del E220
    ax, ay = ANTENA_POS
    s = s.union(cilindro(8, 3, ax, ay, T)).cut(cilindro(3.3, 20, ax, ay, -1))
    return s


def mastil():
    L = MASTIL_L
    s = cq.Workplane("XY").circle(MASTIL_OD / 2).circle(MASTIL_ID / 2).extrude(L)
    s = s.union(cq.Workplane("XY").circle(MASTIL_OD / 2).circle(9).extrude(4).translate((0, 0, L)))
    for y in (-10, 10):  # horquilla para la bisagra de la cámara
        s = s.union(caja(18, 6, 25, 0, y, L + 4))
    eje = cq.Workplane("XZ").circle(M3_PASO / 2).extrude(20, both=True).translate((0, 0, L + 4 + 15))
    return s.cut(eje)


def soporte_camara():
    """Lengüeta con bisagra M3 + placa vertical con ranuras para cinta/bridas.

    Origen = eje de la bisagra. La cámara se sujeta sobre la cara +X; se puede
    montar girada 90° (vertical) para ver más alto de la regla.
    """
    lengua = caja(31, 13.4, 16, 6.5, 0, -8)
    placa = caja(4, 50, 70, 24, 0, -20)
    s = lengua.union(placa)
    s = s.cut(cq.Workplane("XZ").circle(M3_PASO / 2).extrude(20, both=True))
    for y in (-20, 20):
        s = s.cut(caja(10, 3, 24, 24, y, 3))      # cinta horizontal
    for z in (-14, 41):
        s = s.cut(caja(10, 24, 3, 24, 0, z))      # cinta vertical
    return s


def caseta_sensores():
    """Protector tipo garita (se imprime con el techo sobre la cama)."""
    alto = 50
    s = cq.Workplane("XY").circle(28).circle(25.5).extrude(alto)
    s = s.union(cilindro(32, 3, 0, 0, alto))      # techo con alero
    for k in range(12):
        ranura = caja(10, 3, 30, 28, 0, 8).rotate((0, 0, 0), (0, 0, 1), k * 30)
        s = s.cut(ranura)
    return s


def bandeja():
    s = cilindro(112, 3)
    for a in (90, 210, 330):
        x, y = polar(100, a)
        s = s.cut(cilindro(M3_PASO / 2, 5, x, y, -1))
    pl, pw, _ = POWERBANK
    s = s.union(marco(pl, pw, 12, pared=2.5, holgura=1.0).translate((0, 0, 3)))
    for x in (-45, 45):                            # ranuras para cinta velcro
        for y in (-(pw / 2 + 6.5), pw / 2 + 6.5):
            s = s.cut(caja(26, 4, 5, x, y, -1))
    for x in (-72, 72):                            # agujeros de las patas del estante
        for y in (-45, 45):
            s = s.cut(cilindro(1.65, 5, x, y, -1))
    s = s.union(marco(*PSOC, 6).translate((0, -72, 3)))
    s = s.union(marco(*E220, 6).translate((-40, 75, 3)))
    s = s.union(marco(*IMU, 6).translate((38, 75, 3)))
    return s


ALTO_PATAS = POWERBANK[2] + 3


def estante_pynq():
    s = caja(152, 98, 3)
    for x in (-72, 72):
        for y in (-45, 45):
            s = s.union(caja(8, 8, ALTO_PATAS, x, y, -ALTO_PATAS))
            s = s.union(cilindro(1.5, 3, x, y, -ALTO_PATAS - 3))
    bx, by = PYNQ[0] / 2 + 0.3, PYNQ[1] / 2 + 0.3
    hueco = caja(2 * bx, 2 * by, 20, 0, 0, 3 + 4)
    for sx in (-1, 1):
        for sy in (-1, 1):
            s = s.union(caja(10, 10, 9, sx * bx, sy * by, 3).cut(hueco))
    s = s.cut(caja(110, 50, 5, 0, 0, -1))        # ventilación y menos peso
    return s


def punta_palo():
    """Caja del IMU de la punta. Se imprime con la abertura sobre la cama."""
    s = caja(34, 34, 14).cut(caja(IMU[0] + 1, IMU[1] + 1, 10, 0, 0, 4))
    s = s.union(cilindro(8, 18, 0, 0, -18)).cut(cilindro(PALO_D / 2 + 0.2, 16, 0, 0, -19))
    return s


PIEZAS = {
    "casco": casco, "tapa": tapa, "mastil_camara": mastil, "soporte_camara": soporte_camara,
    "caseta_sensores": caseta_sensores, "bandeja": bandeja, "estante_pynq": estante_pynq,
    "punta_palo": punta_palo,
}


# ---------------------------------------------------------------- ensamble
def posiciones():
    """Dónde va cada pieza en el ensamble (traslación y, si hace falta, giro)."""
    zt = H_CASCO
    z_mastil = zt + T_TAPA + 3
    z_bisagra = z_mastil + MASTIL_L + 4 + 15
    return {
        "casco": (0, 0, 0),
        "bandeja": (0, 0, PISO + 6),
        "estante_pynq": (0, 0, PISO + 6 + 3 + ALTO_PATAS),
        "tapa": (0, 0, zt),
        "mastil_camara": (MASTIL_X, 0, z_mastil),
        "soporte_camara": (MASTIL_X, 0, z_bisagra),
        "caseta_sensores": (SENSOR_X, 0, zt + T_TAPA),
        "punta_palo": (0, 0, zt + T_TAPA + 4 + PALO_L + 16),
    }


def pynq_maniqui(z):
    """PYNQ-Z2 simplificada (placa + conectores grandes). No es su distribución real."""
    L, W = PYNQ
    t = 1.6
    s = caja(L, W, t, 0, 0, z)
    zc = z + t
    s = s.union(caja(21, 16, 14, L / 2 - 8, W / 2 - 14, zc))      # RJ45
    s = s.union(caja(14, 15, 15, L / 2 - 6, W / 2 - 34, zc))      # USB-A
    s = s.union(caja(12, 15, 6, -L / 2 + 6, W / 2 - 14, zc))      # HDMI
    s = s.union(caja(12, 15, 6, -L / 2 + 6, W / 2 - 32, zc))      # HDMI
    s = s.union(caja(23, 23, 2.5, 5, 0, zc))                      # Zynq
    s = s.union(caja(51, 5, 8.5, -20, -W / 2 + 6, zc))            # header tipo RPi
    s = s.union(caja(6, 6, 6, -L / 2 + 5, -W / 2 + 6, zc))        # botón / jack
    return s


def maniquies():
    """Volúmenes de los componentes, solo para el render y el peso."""
    zb = PISO + 6 + 3
    ze = zb + ALTO_PATAS + 3
    pos = posiciones()
    zc = pos["soporte_camara"][2]
    pl, pw, ph = POWERBANK
    return {
        "powerbank": (caja(pl, pw, ph, 0, 0, zb), 420, zb + ph / 2),
        "pynq": (pynq_maniqui(ze + 4), 150, ze + 4 + 8),
        "psoc": (caja(*PSOC, 1.6, 0, -72, zb).union(caja(12, 12, 1.5, 15, -72, zb + 1.6))
                 .union(caja(15, 8, 3, -48, -72, zb + 1.6)), 15, zb + 5),
        "e220": (caja(*E220, 6, -40, 75, zb), 10, zb + 3),
        "imu_base": (caja(*IMU, 5, 38, 75, zb), 5, zb + 2),
        "webcam": (caja(WEBCAM[1], WEBCAM[0], WEBCAM[2], MASTIL_X + 26 + WEBCAM[1] / 2, 0, zc), 75, zc + 15),
        "palo": (cilindro(PALO_D / 2, PALO_L, 0, 0, H_CASCO + T_TAPA + 4), 25,
                 H_CASCO + T_TAPA + 4 + PALO_L / 2),
        "imu_punta": (caja(*IMU, 5, 0, 0, pos["punta_palo"][2] + 4), 5, pos["punta_palo"][2] + 6),
        "cables_tornillos_oring": (None, 100, 50),
    }


# ---------------------------------------------------------------- flotación
def flotacion(vol_piezas):
    pos = posiciones()
    masas = []  # (nombre, g, z del centro de masa)
    for nombre, (vol_cm3, zc_local) in vol_piezas.items():
        m = vol_cm3 * PLA * RELLENO
        masas.append((nombre, m, pos[nombre][2] + zc_local))
    for nombre, (_, m, zc) in maniquies().items():
        masas.append((nombre, m, zc))
    M = sum(m for _, m, _ in masas)
    KG = sum(m * z for _, m, z in masas) / M

    # calado: frustum del chaflán + cilindro (agua dulce, 1 g/cm3)
    R, c = D / 2, CHAFLAN
    v_chaflan = math.pi * c / 3 * ((R - c) ** 2 + (R - c) * R + R ** 2) / 1000  # cm3
    v_obj = M  # cm3
    if v_obj <= v_chaflan:
        raise SystemExit("calado dentro del chaflán: revisar modelo")
    d = c + (v_obj - v_chaflan) * 1000 / (math.pi * R ** 2)
    # centro de carena (aprox.: chaflán en c/2, cilindro en su mitad)
    v_cil = v_obj - v_chaflan
    KB = (v_chaflan * c / 2 + v_cil * (c + (d - c) / 2)) / v_obj
    BM = (math.pi * R ** 4 / 4) / (v_obj * 1000)
    GM = KB + BM - KG
    altura_total = pos["punta_palo"][2] + 14
    return {
        "masa_total_g": round(M), "calado_mm": round(d, 1),
        "francobordo_mm": round(H_CASCO - d, 1),
        "KG_mm": round(KG, 1), "KB_mm": round(KB, 1), "BM_mm": round(BM, 1), "GM_mm": round(GM, 1),
        "camara_sobre_agua_mm": round(pos["soporte_camara"][2] + 15 - d),
        "altura_total_mm": round(altura_total),
        "masas_g": {n: round(m) for n, m, _ in masas},
    }


# ---------------------------------------------------------------- render
COLORES = {
    "casco": "#f4f4f2", "tapa": "#dcdcd8", "mastil_camara": "#c9ccd1", "soporte_camara": "#9aa3ad",
    "caseta_sensores": "#e8e8e4", "bandeja": "#7fb3d5", "estante_pynq": "#76c7a3",
    "punta_palo": "#9aa3ad", "powerbank": "#3b3b3b", "pynq": "#c0392b", "psoc": "#2e86c1",
    "e220": "#8e44ad", "imu_base": "#d4ac0d", "webcam": "#222222", "palo": "#555555",
    "imu_punta": "#d4ac0d",
}


def render(mallas, archivo, vista=(22, -55), recorte=None, titulo=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import numpy as np

    fig = plt.figure(figsize=(8, 9), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    luz = np.array([0.4, -0.5, 0.9]); luz /= np.linalg.norm(luz)
    # Una sola colección: matplotlib ordena por profundidad solo dentro de una colección.
    tris, cols = [], []
    for nombre, m in mallas:
        tri = m.vertices[m.faces]
        if recorte is not None:  # se queda con la mitad y > recorte (vista desde -Y)
            tri = tri[tri[:, :, 1].mean(axis=1) > recorte]
            if len(tri) == 0:
                continue
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        base = np.array(matplotlib.colors.to_rgb(COLORES.get(nombre, "#bbbbbb")))
        k = 0.45 + 0.55 * np.clip(np.abs(n @ luz), 0, 1)
        tris.append(tri)
        cols.append(np.clip(base[None, :] * k[:, None], 0, 1))
    tri, col = np.concatenate(tris), np.concatenate(cols)
    ax.add_collection3d(Poly3DCollection(tri, facecolors=col, edgecolors="none", linewidths=0))
    pts = tri.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    c, r = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(*vista)
    ax.set_axis_off()
    if titulo:
        ax.set_title(titulo, fontsize=11)
    fig.tight_layout()
    fig.savefig(archivo, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-render", action="store_true")
    a = ap.parse_args()

    import trimesh

    (SALIDA / "stl").mkdir(exist_ok=True)
    (SALIDA / "step").mkdir(exist_ok=True)
    (SALIDA / "renders").mkdir(exist_ok=True)

    piezas = {n: f() for n, f in PIEZAS.items()}
    vol, info = {}, {}
    for n, w in piezas.items():
        sol = w.val()
        if not sol.isValid():
            print(f"AVISO: {n} no es un sólido válido")
        bb = sol.BoundingBox()
        vol[n] = (sol.Volume() / 1000, (bb.zmin + bb.zmax) / 2)
        info[n] = {"bbox_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
                   "vol_cm3": round(sol.Volume() / 1000, 1)}
        cq.exporters.export(w, str(SALIDA / "stl" / f"{n}.stl"), tolerance=0.1, angularTolerance=0.1)
        cq.exporters.export(w, str(SALIDA / "step" / f"{n}.step"))

    res = flotacion(vol)
    res["piezas"] = info
    (SALIDA / "resumen.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k not in ("masas_g", "piezas")}, indent=2))
    for n, d in info.items():
        print(f"{n:16s} {d['bbox_mm']} mm  {d['vol_cm3']} cm3")

    # ensamble STEP
    pos = posiciones()
    ens = cq.Assembly(name="boya_sei")
    for n, w in piezas.items():
        ens.add(w, name=n, loc=cq.Location(cq.Vector(*pos[n])))
    ens.save(str(SALIDA / "step" / "boya_ensamble.step"))

    # ensamble para Blender: cada pieza y maniquí ya en su posición (mm) + calado
    dir_bl = SALIDA / "renders" / "ensamble_stl"
    dir_bl.mkdir(parents=True, exist_ok=True)
    for n, w in piezas.items():
        cq.exporters.export(w.translate(pos[n]), str(dir_bl / f"{n}.stl"), tolerance=0.05, angularTolerance=0.05)
    for n, (w, _, _) in maniquies().items():
        if w is not None:
            cq.exporters.export(w, str(dir_bl / f"{n}.stl"), tolerance=0.05, angularTolerance=0.05)
    (dir_bl / "escena.json").write_text(json.dumps({"calado_mm": res["calado_mm"], "colores": COLORES}))

    if a.sin_render:
        return
    mallas = []
    def malla(w, desplazamiento=(0, 0, 0)):
        tmp = SALIDA / "renders" / "_tmp.stl"
        cq.exporters.export(w.translate(desplazamiento), str(tmp), tolerance=0.3, angularTolerance=0.2)
        m = trimesh.load(tmp); tmp.unlink()
        return m
    for n, w in piezas.items():
        mallas.append((n, malla(w, pos[n])))
    for n, (w, _, _) in maniquies().items():
        if w is not None:
            mallas.append((n, malla(w)))

    render(mallas, SALIDA / "renders" / "boya_exterior.png", titulo="Boya SEI · exterior")
    sin_tapa = [(n, m) for n, m in mallas if n not in ("tapa", "mastil_camara", "soporte_camara",
                                                       "caseta_sensores", "palo", "punta_palo",
                                                       "imu_punta", "webcam")]
    render(sin_tapa, SALIDA / "renders" / "boya_interior.png", vista=(48, -60),
           titulo="Interior (sin tapa)")
    render(mallas, SALIDA / "renders" / "boya_corte.png", vista=(8, -90), recorte=0.0,
           titulo="Corte por el plano XZ")
    print("renders en", SALIDA / "renders")


if __name__ == "__main__":
    main()
