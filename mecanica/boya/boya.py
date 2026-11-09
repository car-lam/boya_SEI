#!/usr/bin/env python3
"""Boya SEI — concepto «canto rodado» (MVP impreso en 3D), modelo paramétrico en CadQuery.

Forma: casco con fondo cónico suave y cubierta abombada, unidos por una banda de TPU
(parachoques que esconde la junta y los tornillos). Desde la cubierta crece una torre de
sección elíptica que lleva todo lo que asoma: la cabeza con la webcam (en vertical, tras
una ventana), el farol LED de estado arriba, la cámara de aire de los sensores con su
rejilla atrás y, por dentro, el conducto de cables y la antena de 433 MHz.

Colores (impresora con AMS): cuerpo blanco hueso · banda amarillo IALA (TPU) ·
cabeza y rejilla gris carbón · farol translúcido.

Ejes: +X = lado de la cámara (apunta a la regla). Z hacia arriba, z = 0 en el fondo.

Uso (con el venv de CadQuery):
    python boya.py            # STL/STEP, renders rápidos, ensamble para Blender y flotación
    python boya.py --sin-render

Las medidas de placas son APROXIMADAS: medir con calibrador y ajustar abajo.
"""
import argparse
import json
import math
from pathlib import Path

import cadquery as cq

# ---------------------------------------------------------------- parámetros (mm)
D = 240.0            # diámetro máximo del casco (cama de 256 mm)
R = D / 2
H_CASCO = 95.0       # altura del plano de cierre (casco ↔ tapa)
PIE_R = 102.0        # radio del pie plano (fondo)
CONO_H = 18.0        # altura del cono del fondo (45°)
PARED, PISO = 4.0, 4.0
FLANGE = 16.0        # reborde interior del casco (o-ring + insertos)
RIM_T = 6.0          # espesor del aro plano de la tapa (bajo la banda)
DOMO_R, DOMO_H = 100.0, 40.0   # cubierta abombada (semielipse)

ORING = 3.0                      # cordón NBR
RANURA_W, RANURA_H = 4.0, 2.2    # ~27 % de compresión
R_RANURA = R - 6
R_TORN = R - 12
N_TORN = 8
INSERTO_D, INSERTO_L = 4.0, 7.0  # agujero para inserto M3 (ajustar a tu inserto)
M3_PASO, M3_CABEZA = 3.4, 6.5

# torre (coordenadas de la tapa: z = 0 en el plano de cierre)
TX = 35.0                                             # centro de la torre sobre +X
TORRE = [(RIM_T, 46, 34), (55, 34, 25), (140, 28, 23)]   # (z, semieje X, semieje Y)
TORRE_TOP = TORRE[-1][0]
ENCAJE = (25.0, 20.0, 12.0)                           # alojamiento de la cabeza (a, b, prof.)
CAMARA_SENS = dict(x0=TX - 24, x1=TX - 6, y=11, z0=60, z1=108)
REJILLA = dict(x0=TX - 45, x1=TX - 24, y=9, z0=58, z1=110)

# cabeza (coordenadas propias: z = 0 en la cima de la torre)
CABEZA_A, CABEZA_B, CABEZA_H = 28.0, 23.0, 95.0
ESPIGA = (24.7, 19.7, 12.0)        # entra en ENCAJE
LENTE_Z = CABEZA_H / 2             # altura del lente (centro de la webcam)
VENTANA_D, VENTANA_T = 30.0, 1.2   # disco de acrílico de 30 × 1 mm
VISOR_X = 19.5                     # cara frontal plana de la cabeza (visor, ~33 mm de ancho)
FAROL_D = 26.0

# placas y piezas (APROXIMADO: medir)
PYNQ = (140.0, 87.0)             # PYNQ-Z2 (Farnell/Hackerboards: 87 × 140)
PSOC = (120.0, 30.0)             # CY8CKIT-059 entero (aprox.)
E220 = (37.0, 21.0)
IMU = (27.0, 27.0)               # IMU de la boya (inclinación → corrige la cámara)
POWERBANK = (150.0, 70.0, 25.0)  # 20 000 mAh típica: L × A × alto
WEBCAM = (25.0, 32.0, 73.0)      # C270 sin clip, en vertical: fondo × ancho × alto

Z_BANDEJA = 22.0                 # la bandeja va sobre el cono interior
LASTRE_G = 0                     # arandelas de acero bajo la bandeja (hay 18 mm libres)
ALTO_PATAS = POWERBANK[2] + 3

PLA, TPU = 1.24, 1.21            # g/cm3
PERIMETRO_CM, RELLENO = 0.22, 0.15   # 5 perímetros ≈ 2,2 mm; relleno 15 %

SALIDA = Path(__file__).parent


# ---------------------------------------------------------------- utilidades
def caja(lx, ly, lz, x=0, y=0, z=0):
    return cq.Workplane("XY").box(lx, ly, lz, centered=(True, True, False)).translate((x, y, z))


def cilindro(r, h, x=0, y=0, z=0):
    return cq.Workplane("XY").circle(r).extrude(h).translate((x, y, z))


def elipse(a, b, h, x=0, y=0, z=0):
    return cq.Workplane("XY").ellipse(a, b).extrude(h).translate((x, y, z))


def polar(r, ang_deg):
    a = math.radians(ang_deg)
    return (r * math.cos(a), r * math.sin(a))


def revolucion(perfil):
    return cq.Workplane("XZ").polyline(perfil).close().revolve(360, (0, 0, 0), (0, 1, 0))


def marco(lx, ly, alto, pared=2.0, holgura=0.6):
    ix, iy = lx + holgura, ly + holgura
    return caja(ix + 2 * pared, iy + 2 * pared, alto).cut(caja(ix, iy, alto))


def filetear(w, z, r, tol=0.6):
    """Filete en las aristas circulares que están a la altura z (si OCC puede)."""
    try:
        return w.edges(cq.selectors.BoxSelector((-300, -300, z - tol), (300, 300, z + tol))).fillet(r)
    except Exception as e:  # noqa: BLE001
        print(f"aviso: filete r={r} en z={z} no aplicado ({e})")
        return w


ANG_TORN = [22.5 + 45 * k for k in range(N_TORN)]
ANG_AMARRE = (30, 150, 270)
ANG_BANDEJA = (90, 210, 330)


# ---------------------------------------------------------------- piezas
def casco():
    H = H_CASCO
    perfil = [(0, 0), (PIE_R, 0), (R, CONO_H), (R, H), (R - FLANGE, H),
              (R - FLANGE, H - 10), (R - PARED, H - 10 - (FLANGE - PARED)),
              (R - PARED, Z_BANDEJA), (PIE_R - PARED, PISO), (0, PISO)]
    s = revolucion(perfil)
    s = filetear(s, 0, 5)          # canto del pie
    s = filetear(s, CONO_H, 18)    # cono → pared: la curva del «canto rodado»

    # ranura del o-ring e insertos de la tapa
    r0, r1 = R_RANURA - RANURA_W / 2, R_RANURA + RANURA_W / 2
    s = s.cut(revolucion([(r0, H - RANURA_H), (r1, H - RANURA_H), (r1, H + 1), (r0, H + 1)]))
    for a in ANG_TORN:
        x, y = polar(R_TORN, a)
        s = s.cut(cilindro(INSERTO_D / 2, INSERTO_L + 1, x, y, H - INSERTO_L))
    # surco donde engancha el nervio de la banda
    s = s.cut(revolucion([(R - 1, H - 12.4), (R + 1, H - 12.4), (R + 1, H - 8.6), (R - 1, H - 8.6)]))

    # torres de la bandeja
    for a in ANG_BANDEJA:
        x, y = polar(92, a)
        s = s.union(cilindro(5, Z_BANDEJA - PISO, x, y, PISO))
        s = s.cut(cilindro(INSERTO_D / 2, 6, x, y, Z_BANDEJA - 5.5))

    # ojales de amarre empotrados bajo el casco (barra puente que se imprime en el aire)
    for a in ANG_AMARRE:
        refuerzo = caja(18, 26, 11, 60, 0, PISO).rotate((0, 0, 0), (0, 0, 1), a)
        s = s.union(refuerzo)
    for a in ANG_AMARRE:
        bolsillo = caja(10, 18, 11, 60, 0, -0.1).cut(caja(12, 4, 3, 60, 0, 3))
        s = s.cut(bolsillo.rotate((0, 0, 0), (0, 0, 1), a))
    return s


def _torre_solida():
    w = cq.Workplane("XY").workplane(offset=TORRE[0][0]).center(TX, 0).ellipse(TORRE[0][1], TORRE[0][2])
    z_prev = TORRE[0][0]
    for z, a, b in TORRE[1:]:
        w = w.workplane(offset=z - z_prev).ellipse(a, b)
        z_prev = z
    return w.loft(combine=True)


def tapa_torre():
    """Cubierta abombada + torre, una sola pieza (z = 0 en el plano de cierre)."""
    pts = [(DOMO_R * math.cos(math.radians(t)), RIM_T + DOMO_H * math.sin(math.radians(t)))
           for t in range(15, 91, 15)]
    domo = (cq.Workplane("XZ").moveTo(0, 0).lineTo(R - 0.5, 0).lineTo(R - 0.5, RIM_T).lineTo(DOMO_R, RIM_T)
            .spline(pts, tangents=[(0, 1), (-1, 0)], includeCurrent=True).close()
            .revolve(360, (0, 0, 0), (0, 1, 0)))
    s = domo.union(_torre_solida())

    # cubierta hueca (cáscara de 3,5 mm), pero la torre maciza hasta abajo para que no haga palanca.
    # Se imprime con soportes de árbol solo dentro de este hueco (se sacan por abajo).
    e = 3.5
    pts_i = [((DOMO_R - e) * math.cos(math.radians(t)), RIM_T + (DOMO_H - e) * math.sin(math.radians(t)))
             for t in range(15, 91, 15)]
    hueco = (cq.Workplane("XZ").moveTo(0, -1).lineTo(DOMO_R - e, -1).lineTo(DOMO_R - e, RIM_T)
             .spline(pts_i, tangents=[(0, 1), (-1, 0)], includeCurrent=True).close()
             .revolve(360, (0, 0, 0), (0, 1, 0)))
    s = s.cut(hueco.cut(_torre_solida()).cut(elipse(TORRE[0][1], TORRE[0][2], RIM_T + 1, TX, 0, -1)))

    # tornillos de cierre (con caja para que la cabeza quede al ras bajo la banda)
    for a in ANG_TORN:
        x, y = polar(R_TORN, a)
        s = s.cut(cilindro(M3_PASO / 2, RIM_T + 1, x, y, -0.5))
        s = s.cut(cilindro(M3_CABEZA / 2, 3, x, y, RIM_T - 2.2))

    # alojamiento de la cabeza; la torre es hueca (pared de 3 mm) y su interior es el conducto
    # de cables y la antena, abierto hacia el casco
    a, b, prof = ENCAJE
    s = s.cut(elipse(a, b, prof + 1, TX, 0, TORRE_TOP - prof))
    z_int = TORRE_TOP - prof
    interior = (cq.Workplane("XY").workplane(offset=-1).center(TX, 0).ellipse(TORRE[0][1] - 3, TORRE[0][2] - 3)
                .workplane(offset=TORRE[0][0] + 1).ellipse(TORRE[0][1] - 3, TORRE[0][2] - 3)
                .workplane(offset=TORRE[1][0] - TORRE[0][0]).ellipse(TORRE[1][1] - 3, TORRE[1][2] - 3)
                .workplane(offset=z_int - TORRE[1][0] + 0.5).ellipse(a + 0.5, b + 0.5)
                .loft(combine=True))
    s = s.cut(interior)

    # cámara de aire de los sensores: caja sellada dentro de la torre, abierta solo a la rejilla
    c, r = CAMARA_SENS, REJILLA
    paredes = caja(c["x1"] - c["x0"] + 5, 2 * c["y"] + 5, c["z1"] - c["z0"] + 5,
                   (c["x0"] + c["x1"]) / 2, 0, c["z0"] - 2.5)
    s = s.union(paredes.intersect(_torre_solida()))
    s = s.cut(caja(c["x1"] - c["x0"], 2 * c["y"], c["z1"] - c["z0"], (c["x0"] + c["x1"]) / 2, 0, c["z0"]))
    s = s.cut(caja(r["x1"] - r["x0"], 2 * r["y"], r["z1"] - r["z0"], (r["x0"] + r["x1"]) / 2, 0, r["z0"]))
    s = s.cut(cq.Workplane("YZ").circle(2.5).extrude(12).translate((c["x1"] - 2, 0, c["z0"] + 9)))
    return s


def rejilla():
    """Inserto de color que cierra la cámara de sensores, al ras de la torre."""
    r = REJILLA
    bloque = caja(r["x1"] - r["x0"], 2 * (r["y"] - 0.2), r["z1"] - r["z0"] - 0.4,
                  (r["x0"] + r["x1"]) / 2, 0, r["z0"] + 0.2)
    s = _torre_solida().intersect(bloque)
    for k in range(10):
        s = s.cut(caja(40, 12, 2.2, (r["x0"] + r["x1"]) / 2, 0, r["z0"] + 4 + 4.6 * k))
    return s


def cabeza():
    """Cabeza de la cámara (z = 0 en la cima de la torre)."""
    s = elipse(CABEZA_A, CABEZA_B, CABEZA_H)
    s = filetear(s, CABEZA_H, 8)
    ea, eb, eh = ESPIGA
    s = s.union(elipse(ea, eb, eh, 0, 0, -eh))
    s = s.cut(elipse(ea - 1.8, eb - 1.8, eh + 2, 0, 0, -eh - 1))          # se mete la webcam por abajo
    s = s.cut(caja(20, 60, CABEZA_H + 20, VISOR_X + 10, 0, 12))             # visor plano (deja un collar abajo)
    s = s.cut(elipse(CABEZA_A - 2.5, CABEZA_B - 2.5, CABEZA_H - 3, 0, 0, 0)
              .intersect(caja(2 * CABEZA_A, 2 * CABEZA_B, CABEZA_H, VISOR_X - 2.5 - CABEZA_A, 0, 0)))
    # lente: apertura Ø24 + asiento empotrado para la ventana de acrílico
    s = s.cut(cq.Workplane("YZ").circle(12).extrude(10).translate((VISOR_X - 5, 0, LENTE_Z)))
    s = s.cut(cq.Workplane("YZ").circle(VENTANA_D / 2 + 0.3).extrude(5)
              .translate((VISOR_X - VENTANA_T, 0, LENTE_Z)))
    s = s.cut(cilindro(4, 10, 0, 0, CABEZA_H - 5))                       # cables del farol
    return s


def farol():
    """Cúpula translúcida del LED de estado (imprimir en PLA/PETG natural)."""
    rr = FAROL_D / 2
    s = cilindro(rr, 3).union(cq.Workplane("XY").sphere(rr).translate((0, 0, 3)).intersect(cilindro(rr, rr, 0, 0, 3)))
    s = s.union(cilindro(3.8, 4, 0, 0, -4))
    s = s.cut(cilindro(rr - 1.6, 3, 0, 0, -0.01))
    s = s.cut(cq.Workplane("XY").sphere(rr - 1.6).translate((0, 0, 3)))
    s = s.cut(cilindro(2.5, 6, 0, 0, -5))
    return s


def banda():
    """Parachoques de TPU (z = 0 en el plano de cierre). Se imprime con el labio sobre la cama."""
    ri, ro = R + 0.3, R + 4.5
    perfil = [(ri, -16), (ro - 2, -16), (ro, -14), (ro, 6.5), (ro - 2, 8.5),
              (DOMO_R + 1, 8.5), (DOMO_R + 1, RIM_T), (ri, RIM_T)]
    s = revolucion(perfil)
    s = s.union(revolucion([(R - 0.7, -12), (ri + 0.1, -12), (ri + 0.1, -9), (R - 0.7, -9)]))  # nervio
    return s


def bandeja():
    s = cilindro(112, 3)
    for a in ANG_BANDEJA:
        x, y = polar(92, a)
        s = s.cut(cilindro(M3_PASO / 2, 5, x, y, -1))
    pl, pw, _ = POWERBANK
    s = s.union(marco(pl, pw, 12, pared=2.5, holgura=1.0).translate((0, 0, 3)))
    for x in (-45, 45):
        for y in (-(pw / 2 + 6.5), pw / 2 + 6.5):
            s = s.cut(caja(26, 4, 5, x, y, -1))
    for x in (-72, 72):
        for y in (-45, 45):
            s = s.cut(cilindro(1.65, 5, x, y, -1))
    s = s.union(marco(*PSOC, 6).translate((0, -72, 3)))
    s = s.union(marco(*E220, 6).translate((-40, 75, 3)))
    s = s.union(marco(*IMU, 6).translate((38, 75, 3)))
    return s


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
    return s.cut(caja(110, 50, 5, 0, 0, -1))


PIEZAS = {
    "casco": casco, "tapa_torre": tapa_torre, "cabeza": cabeza, "farol": farol,
    "rejilla": rejilla, "banda": banda, "bandeja": bandeja, "estante_pynq": estante_pynq,
}
MATERIAL = {"banda": TPU}


# ---------------------------------------------------------------- ensamble
Z_TOP = H_CASCO + TORRE_TOP


def posiciones():
    return {
        "casco": (0, 0, 0),
        "bandeja": (0, 0, Z_BANDEJA),
        "estante_pynq": (0, 0, Z_BANDEJA + 3 + ALTO_PATAS),
        "tapa_torre": (0, 0, H_CASCO),
        "rejilla": (0, 0, H_CASCO),
        "banda": (0, 0, H_CASCO),
        "cabeza": (TX, 0, Z_TOP),
        "farol": (TX, 0, Z_TOP + CABEZA_H),
    }


def pynq_maniqui(z):
    """PYNQ-Z2 simplificada (placa + conectores grandes). No es su distribución real."""
    L, W = PYNQ
    s = caja(L, W, 1.6, 0, 0, z)
    zc = z + 1.6
    for dims, x, y in [((21, 16, 14), L / 2 - 8, W / 2 - 14), ((14, 15, 15), L / 2 - 6, W / 2 - 34),
                       ((12, 15, 6), -L / 2 + 6, W / 2 - 14), ((12, 15, 6), -L / 2 + 6, W / 2 - 32),
                       ((23, 23, 2.5), 5, 0), ((51, 5, 8.5), -20, -W / 2 + 6), ((6, 6, 6), -L / 2 + 5, -W / 2 + 6)]:
        s = s.union(caja(*dims, x, y, zc))
    return s


def maniquies():
    """(sólido o None, masa g, z del centro de masa) — solo para render y flotación."""
    zb = Z_BANDEJA + 3
    ze = zb + ALTO_PATAS + 3
    pl, pw, ph = POWERBANK
    zl = Z_TOP + LENTE_Z
    wx, wy, wz = WEBCAM
    return {
        "powerbank": (caja(pl, pw, ph, 0, 0, zb), 420, zb + ph / 2),
        "pynq": (pynq_maniqui(ze + 4), 150, ze + 10),
        "psoc": (caja(*PSOC, 1.6, 0, -72, zb).union(caja(12, 12, 1.5, 15, -72, zb + 1.6)), 15, zb + 2),
        "e220": (caja(*E220, 6, -40, 75, zb), 10, zb + 3),
        "imu_base": (caja(*IMU, 5, 38, 75, zb), 5, zb + 2),
        "webcam": (caja(wx, wy, wz, TX, 0, zl - wz / 2), 75, zl),
        "ventana": (cq.Workplane("YZ").circle(VENTANA_D / 2).extrude(1.0)
                    .translate((TX + VISOR_X - VENTANA_T, 0, zl)), 2, zl),
        "sensores": (caja(4, 18, 40, CAMARA_SENS["x0"] + 6, 0, H_CASCO + CAMARA_SENS["z0"] + 4), 8,
                     H_CASCO + CAMARA_SENS["z0"] + 24),
        "cables_tornillos_oring_antena": (None, 100, 60),
    }


# ---------------------------------------------------------------- masa y flotación
def masa_impresa(sol, densidad):
    v = sol.Volume() / 1000            # cm3
    a = sol.Area() / 100               # cm2
    cascara = min(v, a * PERIMETRO_CM)
    return densidad * (cascara + max(0.0, v - cascara) * RELLENO)


def flotacion(piezas, lastre_g=LASTRE_G):
    pos = posiciones()
    masas = []
    for n, w in piezas.items():
        sol = w.val()
        masas.append((n, masa_impresa(sol, MATERIAL.get(n, PLA)), pos[n][2] + sol.Center().z))
    for n, (_, m, zc) in maniquies().items():
        masas.append((n, m, zc))
    if lastre_g:
        masas.append(("lastre", lastre_g, PISO + 6))
    M = sum(m for _, m, _ in masas)
    KG = sum(m * z for _, m, z in masas) / M

    # carena: volumen exterior del casco bajo el agua (agua dulce 1 g/cm3), por bisección
    exterior = revolucion([(0, 0), (PIE_R, 0), (R, CONO_H), (R, H_CASCO), (0, H_CASCO)])
    exterior = filetear(filetear(exterior, 0, 5), CONO_H, 18)

    def sumergido(d):
        return exterior.intersect(caja(400, 400, d)).val()

    lo, hi = 1.0, H_CASCO
    for _ in range(30):
        d = (lo + hi) / 2
        if sumergido(d).Volume() / 1000 > M:
            hi = d
        else:
            lo = d
    d = (lo + hi) / 2
    sub = sumergido(d)
    V = sub.Volume()                     # mm3
    KB = sub.Center().z
    cara = exterior.intersect(caja(400, 400, d + 0.01).translate((0, 0, 0))).faces(">Z").val()
    r_wl = math.sqrt(cara.Area() / math.pi)
    BM = (math.pi * r_wl ** 4 / 4) / V
    GM = KB + BM - KG
    return {
        "masa_total_g": round(M), "calado_mm": round(d, 1), "francobordo_mm": round(H_CASCO - d, 1),
        "KG_mm": round(KG, 1), "KB_mm": round(KB, 1), "BM_mm": round(BM, 1), "GM_mm": round(GM, 1),
        "lente_sobre_agua_mm": round(Z_TOP + LENTE_Z - d),
        "lente_x_mm": TX + VISOR_X, "lente_z_mm": Z_TOP + LENTE_Z,
        "altura_total_mm": round(Z_TOP + CABEZA_H + FAROL_D / 2 + 3),
        "masas_g": {n: round(m) for n, m, _ in masas},
    }


# ---------------------------------------------------------------- render rápido (matplotlib)
COLORES = {
    "casco": "#ece6da", "tapa_torre": "#ece6da", "banda": "#f0b000", "cabeza": "#2b2e33",
    "rejilla": "#2b2e33", "farol": "#f4f1e8", "bandeja": "#d8d2c6", "estante_pynq": "#d8d2c6",
    "powerbank": "#3b3b3b", "pynq": "#b03a48", "psoc": "#2e86c1", "e220": "#6c3483",
    "imu_base": "#d4ac0d", "webcam": "#111111", "ventana": "#0b0d10", "sensores": "#1f6f43",
}
OCULTAS_INTERIOR = {"tapa_torre", "cabeza", "farol", "rejilla", "banda", "webcam", "ventana", "sensores"}


def render(mallas, archivo, vista=(22, -55), titulo=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    fig = plt.figure(figsize=(8, 9), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    luz = np.array([0.4, -0.5, 0.9]); luz /= np.linalg.norm(luz)
    tris, cols = [], []
    for nombre, m in mallas:
        tri = m.vertices[m.faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        base = np.array(matplotlib.colors.to_rgb(COLORES.get(nombre, "#bbbbbb")))
        k = 0.45 + 0.55 * np.clip(np.abs(n @ luz), 0, 1)
        tris.append(tri); cols.append(np.clip(base[None, :] * k[:, None], 0, 1))
    tri, col = np.concatenate(tris), np.concatenate(cols)
    ax.add_collection3d(Poly3DCollection(tri, facecolors=col, edgecolors="none", linewidths=0))
    pts = tri.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    c, r = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1)); ax.view_init(*vista); ax.set_axis_off()
    if titulo:
        ax.set_title(titulo, fontsize=11)
    fig.tight_layout(); fig.savefig(archivo, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-render", action="store_true")
    a = ap.parse_args()

    for sub in ("stl", "step", "renders"):
        (SALIDA / sub).mkdir(exist_ok=True)
    for viejo in list((SALIDA / "stl").glob("*.stl")) + list((SALIDA / "step").glob("*.step")):
        viejo.unlink()  # el diseño anterior tenía otras piezas

    piezas = {n: f() for n, f in PIEZAS.items()}
    info = {}
    for n, w in piezas.items():
        sol = w.val()
        if not sol.isValid():
            print(f"AVISO: {n} no es un sólido válido")
        bb = sol.BoundingBox()
        info[n] = {"bbox_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
                   "masa_g": round(masa_impresa(sol, MATERIAL.get(n, PLA)))}
        cq.exporters.export(w, str(SALIDA / "stl" / f"{n}.stl"), tolerance=0.05, angularTolerance=0.1)
        cq.exporters.export(w, str(SALIDA / "step" / f"{n}.step"))

    res = flotacion(piezas)
    con = flotacion(piezas, LASTRE_G + 300)
    res["con_300g_mas_de_lastre"] = {k: con[k] for k in ("masa_total_g", "calado_mm", "francobordo_mm", "GM_mm")}
    res["piezas"] = info
    (SALIDA / "resumen.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k not in ("masas_g", "piezas")}, indent=2))
    for n, d in info.items():
        print(f"{n:14s} {d['bbox_mm']} mm  ~{d['masa_g']} g")

    pos = posiciones()
    ens = cq.Assembly(name="boya_sei")
    for n, w in piezas.items():
        ens.add(w, name=n, loc=cq.Location(cq.Vector(*pos[n])))
    ens.export(str(SALIDA / "step" / "boya_ensamble.step"))

    # ensamble para Blender
    dir_bl = SALIDA / "renders" / "ensamble_stl"
    dir_bl.mkdir(parents=True, exist_ok=True)
    for viejo in dir_bl.glob("*.stl"):
        viejo.unlink()
    for n, w in piezas.items():
        cq.exporters.export(w.translate(pos[n]), str(dir_bl / f"{n}.stl"), tolerance=0.03, angularTolerance=0.05)
    for n, (w, _, _) in maniquies().items():
        if w is not None:
            cq.exporters.export(w, str(dir_bl / f"{n}.stl"), tolerance=0.05, angularTolerance=0.05)
    (dir_bl / "escena.json").write_text(json.dumps({
        "calado_mm": res["calado_mm"], "lente_x_mm": res["lente_x_mm"], "lente_z_mm": res["lente_z_mm"],
        "colores": COLORES, "ocultas_interior": sorted(OCULTAS_INTERIOR)}))

    if a.sin_render:
        return
    import trimesh
    mallas = []
    for n in list(piezas) + [k for k, v in maniquies().items() if v[0] is not None]:
        mallas.append((n, trimesh.load(dir_bl / f"{n}.stl")))
    render(mallas, SALIDA / "renders" / "boya_exterior.png", titulo="Boya SEI · canto rodado")
    render([(n, m) for n, m in mallas if n not in OCULTAS_INTERIOR], SALIDA / "renders" / "boya_interior.png",
           vista=(48, -60), titulo="Interior (sin tapa)")
    print("renders en", SALIDA / "renders")


if __name__ == "__main__":
    main()
