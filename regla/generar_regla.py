#!/usr/bin/env python3
"""Genera la regla limnimétrica de la boya SEI como PDF para imprimir al 100 %.

Formato tipo SENAMHI (10 cm de ancho, graduación de 1 cm), partida en tramos que
entran en una hoja A4. Cada página trae marcas de corte y una barra de 10 cm para
comprobar que la impresora no escaló.

Diseño (pensado para el algoritmo de visión, sirve en blanco y negro):
- Escalera de franjas negras/blancas de 1 cm a la izquierda (período 2 cm): es la
  zona donde se mide y la que permite encontrar la regla (muchas transiciones
  regulares por columna). No lleva lomo ni números encima.
- Línea y número cada 10 cm a la derecha, línea corta cada 5 cm.
- Cabezal arriba con un marcador ArUco (DICT_4X4_50, id 0) para que el PS ubique
  la regla y corrija la perspectiva con OpenCV.
- Borde: blanco (por defecto) o rojo (opcional, ayuda a ubicarla por color).

Uso:
    python3 generar_regla.py                  # 44 cm graduados + cabezal = 50 cm (2 hojas A4)
    python3 generar_regla.py --largo 94       # 1 m físico (4 hojas, piscina)
    python3 generar_regla.py --borde rojo     # con borde rojo
    python3 generar_regla.py --sin-aruco --largo 50
"""
import argparse
import math

import cairo

MM = 72 / 25.4  # puntos por mm
HOJAS = {"A4": (210, 297), "A3": (297, 420)}
MAX_TRAMO_MM = {"A4": 250, "A3": 370}  # alto útil por hoja, dejando sitio a los rótulos

ANCHO = 100.0        # ancho de la regla (mm)
BORDE = 6.0          # margen a cada lado (mm)
ESCALERA = 44.0      # ancho de la zona de franjas (mm)
CABEZAL = 60.0       # alto del cabezal con el ArUco (mm)
ARUCO_MM = 40.0      # lado del marcador ArUco, borde negro incluido (mm)
ROJO = (0.85, 0.10, 0.10)
FUENTE = "DejaVu Sans"

# ArUco DICT_4X4_50, id 0: 6×6 celdas (borde negro + 4×4 de datos), 1 = blanco.
# Sacado de cv2.aruco.drawMarker(DICT_4X4_50, 0, 6).
ARUCO_ID0 = [
    [0, 0, 0, 0, 0, 0],
    [0, 1, 0, 1, 1, 0],
    [0, 0, 1, 0, 1, 0],
    [0, 0, 0, 1, 1, 0],
    [0, 0, 0, 1, 0, 0],
    [0, 0, 0, 0, 0, 0],
]


def alto_total(largo_cm, aruco, borde):
    return largo_cm * 10 + (CABEZAL if aruco else 0) + (BORDE if borde == "rojo" else 0)


def dibujar_regla(ctx, largo_cm, aruco, borde):
    """Dibuja la regla completa. Origen = esquina superior izquierda. Unidades: mm."""
    alto = alto_total(largo_cm, aruco, borde)
    y = lambda v: alto - v * 10  # valor en cm -> mm desde arriba

    ctx.set_source_rgb(1, 1, 1)
    ctx.rectangle(0, 0, ANCHO, alto)
    ctx.fill()

    # Escalera: negro en [n, n+1) para n par
    ctx.set_source_rgb(0, 0, 0)
    for n in range(0, math.ceil(largo_cm), 2):
        b = min(n + 1, largo_cm)
        ctx.rectangle(BORDE, y(b), ESCALERA, (b - n) * 10)
    ctx.fill()

    # Líneas de 10 cm (y cortas de 5 cm) en la zona de números
    x_num = BORDE + ESCALERA
    ancho_num = ANCHO - 2 * BORDE - ESCALERA
    for v in range(5, math.ceil(largo_cm), 5):
        largo_linea = ancho_num if v % 10 == 0 else ancho_num / 2
        ctx.rectangle(x_num, y(v) - 0.75, largo_linea, 1.5)
    ctx.fill()

    # Números cada 10 cm, sobre su línea
    ctx.select_font_face(FUENTE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(17)
    for v in range(10, math.ceil(largo_cm), 10):
        texto = str(v)
        ext = ctx.text_extents(texto)
        if y(v) - 4 - ext.height < y(largo_cm):
            continue  # no entra debajo del final de la graduación
        ctx.move_to(x_num + ancho_num / 2 - ext.width / 2 - ext.x_bearing, y(v) - 4)
        ctx.show_text(texto)

    # Cabezal con el ArUco, centrado y con zona blanca alrededor
    if aruco:
        celda = ARUCO_MM / 6
        y_cab = y(largo_cm) - CABEZAL
        x0, y0 = (ANCHO - ARUCO_MM) / 2, y_cab + (CABEZAL - ARUCO_MM) / 2
        ctx.set_source_rgb(0, 0, 0)
        for f, fila in enumerate(ARUCO_ID0):
            for c, blanco in enumerate(fila):
                if not blanco:
                    # +0.05 mm para que no queden rendijas entre celdas
                    ctx.rectangle(x0 + c * celda, y0 + f * celda, celda + 0.05, celda + 0.05)
        ctx.fill()

    if borde == "rojo":
        ctx.set_source_rgb(*ROJO)
        ctx.rectangle(0, 0, BORDE, alto)
        ctx.rectangle(ANCHO - BORDE, 0, BORDE, alto)
        ctx.rectangle(0, 0, ANCHO, BORDE)
        ctx.fill()


def marcas_corte(ctx, x, y, w, h, largo=6, sep=2):
    ctx.set_source_rgb(0, 0, 0)
    ctx.set_line_width(0.2)
    for cx, dx in ((x, -1), (x + w, 1)):
        for cy, dy in ((y, -1), (y + h, 1)):
            ctx.move_to(cx + dx * sep, cy)
            ctx.line_to(cx + dx * (sep + largo), cy)
            ctx.move_to(cx, cy + dy * sep)
            ctx.line_to(cx, cy + dy * (sep + largo))
    ctx.stroke()


def rotulo(ctx, s, x, y, tam=3.5, negrita=False):
    ctx.set_source_rgb(0.3, 0.3, 0.3)
    ctx.select_font_face(FUENTE, cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if negrita else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(tam)
    ctx.move_to(x, y)
    ctx.show_text(s)


def tramos(alto, max_mm):
    """Corta la regla (mm, medidos desde abajo) en tramos parejos de cm enteros."""
    n = math.ceil(alto / max_mm)
    paso = math.ceil(alto / n / 10) * 10
    return [(d, min(d + paso, alto)) for d in range(0, math.ceil(alto), paso)]


def generar_pdf(salida, largo, hoja, aruco, borde):
    hw, hh = HOJAS[hoja]
    alto = alto_total(largo, aruco, borde)
    partes = tramos(alto, MAX_TRAMO_MM[hoja])
    n = len(partes)
    sup = cairo.PDFSurface(salida, hw * MM, hh * MM)
    ctx = cairo.Context(sup)
    ctx.scale(MM, MM)
    for i, (desde, hasta) in enumerate(partes):
        h = hasta - desde
        x0, y0 = (hw - ANCHO) / 2, (hh - h) / 2

        ctx.save()
        ctx.rectangle(x0, y0, ANCHO, h)
        ctx.clip()
        ctx.translate(x0, y0 - (alto - hasta))  # ventana [desde, hasta] de la regla
        dibujar_regla(ctx, largo, aruco, borde)
        ctx.restore()
        marcas_corte(ctx, x0, y0, ANCHO, h)

        yb = y0 - 12
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(x0, yb, 100, 2)
        ctx.fill()
        rotulo(ctx, "Esta barra debe medir 10,0 cm. Si no, imprime al 100 % / tamaño real.",
               x0, yb - 2.5, 3)
        if desde / 10 >= largo:
            rango = "cabezal"
        elif hasta / 10 > largo:
            rango = f"{desde / 10:g}–{largo:g} cm + cabezal"
        else:
            rango = f"{desde / 10:g}–{hasta / 10:g} cm"
        rotulo(ctx, f"Regla SEI · tramo {i + 1} de {n} · {rango}", x0, y0 + h + 9, 3.5, negrita=True)
        pie = "El 0 cm (abajo) es el extremo que va al fondo." if i == 0 else f"Va encima del tramo {i}."
        if aruco and i == n - 1:
            pie += " ArUco DICT_4X4_50, id 0, lado 40 mm."
        rotulo(ctx, "Cortar por las marcas. " + pie, x0, y0 + h + 14, 3)
        ctx.show_page()
    sup.finish()
    return n


def generar_vista(salida, largo, aruco, borde, px_mm=3):
    """PNG de la regla completa, para revisar el diseño o probar la detección."""
    alto = alto_total(largo, aruco, borde)
    sup = cairo.ImageSurface(cairo.FORMAT_RGB24, int(ANCHO * px_mm) + 80, int(alto * px_mm) + 80)
    ctx = cairo.Context(sup)
    ctx.set_source_rgb(0.85, 0.85, 0.85)
    ctx.paint()
    ctx.translate(40, 40)
    ctx.scale(px_mm, px_mm)
    dibujar_regla(ctx, largo, aruco, borde)
    sup.write_to_png(salida)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--largo", type=float, default=44, help="cm graduados (44 → 50 cm con el cabezal)")
    p.add_argument("--hoja", choices=HOJAS, default="A4")
    p.add_argument("--borde", choices=("blanco", "rojo"), default="blanco")
    p.add_argument("--sin-aruco", action="store_true", help="sin el cabezal con el marcador")
    p.add_argument("--vista", help="además, guarda un PNG de la regla completa")
    a = p.parse_args()
    aruco = not a.sin_aruco
    nombre = f"regla_{a.largo:g}cm_{a.hoja}" + ("_rojo" if a.borde == "rojo" else "") + ".pdf"
    n = generar_pdf(nombre, a.largo, a.hoja, aruco, a.borde)
    print(f"{nombre}: {n} página(s), {alto_total(a.largo, aruco, a.borde) / 10:g} cm de largo físico")
    if a.vista:
        generar_vista(a.vista, a.largo, aruco, a.borde)
        print(f"vista: {a.vista}")
