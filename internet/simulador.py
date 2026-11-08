# Simula los 3 nodos y el gateway mientras no tengamos la radio funcionando.
# Arma tramas reales (mismo formato que los nodos), les mete los problemas de un enlace
# de verdad y las sube a la central por HTTP, igual que lo haria el gateway con el SIM800L.
#
#   python simulador.py                       -> manda a http://127.0.0.1:8160
#   python simulador.py --url https://sei.silosense.dev --rapido 10
import argparse
import math
import random
import time

import requests

import capacidad
import config
import trama

# Distancia de cada nodo al gateway (m): define su RSSI y cuantas tramas pierde.
DISTANCIA = {1: 120, 2: 600, 3: 30}
RUIDO_DBM = -110.0
# Los choques entre nodos siguen el modelo ALOHA de capacidad.py (dependen del periodo y del tiempo en el aire).


def rssi_por_distancia(d):
    """Modelo log-distancia: perdida = 40 dB a 1 m + 10*n*log10(d), n = 3.5 (orilla con vegetacion);
    Ptx = 22 dBm (E220-400T22S)."""
    return 22 - (40 + 10 * 3.5 * math.log10(d)) + random.gauss(0, 2.5)


def prob_llegar(snr):
    return 1 / (1 + math.exp(-(snr - config.SNR_LIMITE_DB) / 1.5))


CICLO_MIN = 40       # cada 40 min se repite: calma, crecida, pico, bajada


def nivel_rio(t, t0):
    """Base de 35 cm con ola suave. En cada ciclo: 10 min de calma, 10 min subiendo
    hasta ~125 cm, 5 min en el pico y 15 min bajando."""
    m = ((t - t0) / 60) % CICLO_MIN
    base = 35 + 3 * math.sin(m / 3)
    if m < 10:
        crecida = 0
    elif m < 20:
        crecida = (m - 10) * 9
    elif m < 25:
        crecida = 90
    else:
        crecida = max(0, 90 - (m - 25) * 6)
    return base + crecida + random.gauss(0, 0.8)


def valores_nodo(id_nodo, t, t0, n_frame):
    if id_nodo == 1:
        return {'temp_C': round(19 + random.gauss(0, 0.3), 2), 'hr_pct': round(78 + random.gauss(0, 1), 2),
                'presion_hPa': round(1011 - (t - t0) / 600 + random.gauss(0, 0.2), 1),
                'gas_ohm': int(52000 + random.gauss(0, 1500))}
    if id_nodo == 2:
        return {'co2_ppm': int(430 + random.gauss(0, 12)), 'temp_C': round(18.6 + random.gauss(0, 0.3), 2),
                'hr_pct': round(80 + random.gauss(0, 1), 2)}
    nivel = nivel_rio(t, t0)
    return {'nivel_cm': int(round(nivel)), 'confianza': random.randint(70, 98), 'id_frame': n_frame % 65536}


def voltear_bit(datos, cuantos):
    b = bytearray(datos)
    for _ in range(cuantos):
        i = random.randrange(len(b))
        b[i] ^= 1 << random.randrange(8)
    return bytes(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:%d' % config.PUERTO)
    ap.add_argument('--clave', default=config.CLAVE_INGESTA)
    ap.add_argument('--rapido', type=float, default=6, help='cada cuantos segundos reales reporta cada nodo')
    ap.add_argument('--version', type=int, default=2, help='1 = en claro, 2 = cifrado + Hamming')
    a = ap.parse_args()

    t0 = time.time()
    seq = {1: random.randint(0, 100), 2: random.randint(0, 100), 3: random.randint(0, 100)}
    bufer = []                      # lo que el gateway no pudo subir todavia
    n = 0
    print('Simulando N1, N2, N3 -> %s (Ctrl+C para parar)' % a.url)
    while True:
        t = time.time()
        for id_nodo in (1, 2, 3):
            seq[id_nodo] = (seq[id_nodo] + 1) % 65536
            tipo = 5 if n % 10 == 9 else 1                       # cada 10 ciclos, un HEARTBEAT
            if tipo == 5:
                v = {'vbat_mV': 4950 + random.randint(-30, 30), 'reinicios': 0}
            else:
                v = valores_nodo(id_nodo, t, t0, n)
                if id_nodo == 3 and v['nivel_cm'] >= config.NIVEL_ALERTA:
                    tipo, v['nivel_alerta'] = 4, 2                  # la camara manda ALERT
            datos = trama.armar_trama(a.version, tipo, id_nodo, seq[id_nodo], int(t), v)

            rssi = rssi_por_distancia(DISTANCIA[id_nodo])
            ruido = RUIDO_DBM + random.gauss(0, 1.5)
            choque = capacidad.prob_choque(len(DISTANCIA), a.rapido, capacidad.tiempo_en_aire(len(datos)))
            if random.random() > prob_llegar(rssi - ruido) or random.random() < choque:
                continue                                         # trama perdida en el aire
            r = random.random()
            if r < 0.04:
                datos = voltear_bit(datos, 1)                    # 1 bit malo: Hamming lo arregla si cae en el payload
            elif r < 0.06:
                datos = voltear_bit(datos, 3)                    # varios bits: el CRC lo detecta
            item = {'hex': datos.hex(), 'rssi': round(rssi, 1), 'ruido': round(ruido, 1), 't_rx': round(time.time(), 3)}
            bufer.append(item)
            if random.random() < 0.02:
                bufer.append(dict(item))                         # el gateway reenvia: duplicado

        try:
            resp = requests.post(a.url + '/api/ingesta', json={'gw': 'GW-SIM', 'tramas': bufer[:200]},
                                 headers={'X-Clave': a.clave}, timeout=10)
            resp.raise_for_status()
            js = resp.json()
            if js.get('ok'):
                print('ciclo %d: subidas %d, validas %d' % (n, js['recibidas'], js['validas']))
                del bufer[:200]
        except requests.RequestException as e:
            print('sin conexion (%s); guardo %d tramas en el bufer' % (type(e).__name__, len(bufer)))
            del bufer[:-2000]                                    # tope del bufer: se pierden las mas viejas
        n += 1
        time.sleep(a.rapido)


if __name__ == '__main__':
    main()
