# Capacidad de la red LoRa: cuanto soporta como maximo antes de que las tramas choquen.
# Lo que pidio el profe (clase S04): caracterizar con formulas, simular en Python la cantidad
# maxima y despues verificarlo con lo que mide la implementacion real.
#
#  1. Tiempo en el aire de cada trama (ppt Inalambricos: Ts = 2^SF / BW, DR = SF * BW / 2^SF * CR;
#     formula completa de Semtech / Augustin 2016, el paper que cita la ppt).
#  2. Los nodos transmiten sin coordinarse (no hay ACK ni turnos): es ALOHA puro.
#     Una trama choca si otra empieza dentro de su ventana vulnerable de 2 * ToA:
#         P(choque) = 1 - exp(-2 * lambda_otros * ToA)
#  3. Simulacion de Monte Carlo con instantes al azar para comprobar la formula.
import math
import random
from functools import lru_cache

import config
import trama

# Valores de ejemplo solo para medir el largo de cada trama (el largo no depende del valor).
EJEMPLOS = [
    ('N1 BME680', 1, 1, {'temp_C': 19.5, 'hr_pct': 78.0, 'presion_hPa': 1011.0, 'gas_ohm': 52000}),
    ('N2 SCD41', 2, 1, {'co2_ppm': 430, 'temp_C': 18.6, 'hr_pct': 80.0}),
    ('N3 cámara', 3, 1, {'nivel_cm': 40, 'confianza': 90, 'id_frame': 1}),
    ('N3 ALERT', 3, 4, {'nivel_cm': 110, 'confianza': 90, 'id_frame': 1, 'nivel_alerta': 2}),
    ('HEARTBEAT', 1, 5, {'vbat_mV': 4950, 'reinicios': 0}),
]


def tasa_bits(sf=None, bw=None, cr=None):
    sf, bw, cr = sf or config.LORA_SF, bw or config.LORA_BW_HZ, cr or config.LORA_CR
    return sf * bw / 2 ** sf * 4 / (4 + cr)


def tiempo_en_aire(n_bytes, sf=None, bw=None, cr=None, preambulo=None):
    """Segundos que la trama ocupa el canal (cabecera LoRa explicita y CRC de LoRa activados)."""
    sf, bw = sf or config.LORA_SF, bw or config.LORA_BW_HZ
    cr, preambulo = cr or config.LORA_CR, preambulo or config.LORA_PREAMBULO
    t_simbolo = 2 ** sf / bw
    de = 1 if t_simbolo > 0.016 else 0               # optimizacion de baja tasa (simbolos > 16 ms)
    simbolos = 8 + max(math.ceil((8 * n_bytes - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preambulo + 4.25) * t_simbolo + simbolos * t_simbolo


def largos(version=2):
    salida = []
    for nombre, nodo, tipo, v in EJEMPLOS:
        n = len(trama.armar_trama(version, tipo, nodo, 1, 0, v))
        salida.append({'trama': nombre, 'bytes': n, 'toa_ms': round(1000 * tiempo_en_aire(n), 1)})
    return salida


def prob_choque(n_nodos, periodo_s, toa_s):
    """ALOHA puro: cada uno de los otros n-1 nodos manda 1/periodo tramas por segundo."""
    return 1 - math.exp(-2 * (n_nodos - 1) / periodo_s * toa_s)


def nodos_maximos(periodo_s, toa_s, limite):
    """Mayor n con P(choque) <= limite."""
    return 1 + int(-math.log(1 - limite) * periodo_s / (2 * toa_s))


def simular(n_nodos, periodo_s, toa_s, periodos=400, semilla=1):
    """Monte Carlo: cada nodo transmite una vez por periodo en un instante al azar.
    Devuelve la fraccion de tramas que se solapan con otra."""
    rnd = random.Random(semilla)
    inicios = sorted(k * periodo_s + rnd.uniform(0, periodo_s)
                     for k in range(periodos) for _ in range(n_nodos))
    chocan = 0
    for i, t in enumerate(inicios):
        antes = i > 0 and t - inicios[i - 1] < toa_s
        despues = i + 1 < len(inicios) and inicios[i + 1] - t < toa_s
        chocan += antes or despues
    return chocan / len(inicios)


@lru_cache(maxsize=4)
def teoria(periodo_s, toa_s):
    curva = []
    for n in (3, 5, 10, 20, 40, 80, 150, 300):
        curva.append({'nodos': n, 'formula_pct': round(100 * prob_choque(n, periodo_s, toa_s), 2),
                      'simulado_pct': round(100 * simular(n, periodo_s, toa_s), 2)})
    return curva


def resumen(medido):
    """medido: {'tramas_min': ..., 'bytes_medio': ..., 'nodos': ..., 'per_pct': {...}} de la base de datos."""
    tabla = largos()
    toa = max(f['toa_ms'] for f in tabla if f['trama'] != 'N3 ALERT') / 1000   # peor caso de trama normal
    periodo = config.PERIODO_S
    energia_mj = 1000 * config.LORA_VCC * config.LORA_I_TX_A * toa
    salida = {
        'radio': {'sf': config.LORA_SF, 'bw_khz': config.LORA_BW_HZ / 1000, 'cr': '4/%d' % (4 + config.LORA_CR),
                  'tasa_bps': round(tasa_bits()), 't_simbolo_ms': round(1000 * 2 ** config.LORA_SF / config.LORA_BW_HZ, 3),
                  'preambulo': config.LORA_PREAMBULO},
        'tramas': tabla,
        'periodo_s': periodo,
        'toa_ms': round(1000 * toa, 1),
        'ocupacion_nodo_pct': round(100 * toa / periodo, 3),
        'choque_3_nodos_pct': round(100 * prob_choque(3, periodo, toa), 2),
        'max_nodos': {'1': nodos_maximos(periodo, toa, 0.01), '5': nodos_maximos(periodo, toa, 0.05),
                      '10': nodos_maximos(periodo, toa, 0.10)},
        'saturacion_nodos': int(0.5 * periodo / toa),      # ALOHA rinde lo maximo (18.4 %) con G = 0.5
        'energia_tx_mJ': round(energia_mj, 1),
        'energia_dia_J': round(energia_mj / 1000 * 86400 / periodo, 1),
        'curva': teoria(periodo, toa),
        'medido': medido,
    }
    if medido and medido.get('tramas_min'):
        toa_med = tiempo_en_aire(round(medido['bytes_medio']))
        lam = medido['tramas_min'] / 60
        salida['medido']['toa_ms'] = round(1000 * toa_med, 1)
        salida['medido']['ocupacion_canal_pct'] = round(100 * lam * toa_med, 2)
        # cada trama compite con las de los demas nodos
        otros = lam * (medido['nodos'] - 1) / medido['nodos'] if medido['nodos'] else 0
        salida['medido']['choque_esperado_pct'] = round(100 * (1 - math.exp(-2 * otros * toa_med)), 2)
    return salida
