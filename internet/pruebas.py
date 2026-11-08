# Pruebas de la central:  python pruebas.py
import os
import random
import tempfile

import config

config.BASE_DATOS = os.path.join(tempfile.mkdtemp(), 'prueba.db')
config.CLAVE_INGESTA = 'clave-de-prueba'

import app as central   # noqa: E402  (despues de cambiar la base de datos)
import capacidad        # noqa: E402
import enlace           # noqa: E402
import trama            # noqa: E402


def prueba_crc():
    assert trama.crc16(b'123456789') == 0x29B1          # vector estandar CRC-CCITT (0xFFFF)


def prueba_hamming():
    for n in range(16):
        palabra = trama.hamming_codificar_nibble(n)
        assert trama.hamming_decodificar_palabra(palabra) == (n, False)
        for bit in range(7):                             # cualquier bit malo se corrige
            assert trama.hamming_decodificar_palabra(palabra ^ (1 << bit)) == (n, True)
    datos = bytes(range(40))
    assert trama.hamming_decodificar(trama.hamming_codificar(datos)) == (datos, 0)


def prueba_cifrados():
    p = b'\x00\x8f\x41\x07\xff'
    assert trama.vigenere(trama.vigenere(p, b'SEI'), b'SEI', descifrar=True) == p
    c = trama.aes_ctr(p, 3, 77, 1700000000)
    assert c != p and len(c) == len(p)
    assert trama.aes_ctr(c, 3, 77, 1700000000) == p


def prueba_tramas():
    v3 = {'nivel_cm': 143, 'confianza': 87, 'id_frame': 5120}
    for cifrado in ('ninguno', 'vigenere', 'aes-ctr'):
        config.CIFRADO = cifrado
        for version in (1, 2):
            d = trama.armar_trama(version, 1, 3, 311, 1700000000, v3)
            r = trama.leer_trama(d)
            assert r['valida'] and r['valores'] == v3, (cifrado, version, r)
    config.CIFRADO = 'vigenere'
    v1 = {'temp_C': 19.25, 'hr_pct': 78.5, 'presion_hPa': 1011.3, 'gas_ohm': 52000}
    assert trama.leer_trama(trama.armar_trama(1, 1, 1, 5, 0, v1))['valores'] == v1
    assert len(trama.armar_trama(1, 1, 3, 1, 0, v3)) == 17                  # 10 + 5 + 2, como en el doc 03

    # 1 bit malo en el payload Hamming: se corrige y el CRC confirma
    d = bytearray(trama.armar_trama(2, 1, 3, 9, 1700000000, v3))
    d[12] ^= 0x04
    r = trama.leer_trama(bytes(d))
    assert r['valida'] and r['corregidos'] == 1 and r['valores'] == v3
    # bit malo en la cabecera: Hamming no la protege, el CRC lo detecta
    d = bytearray(trama.armar_trama(2, 1, 3, 9, 1700000000, v3))
    d[4] ^= 0x01
    assert trama.leer_trama(bytes(d))['error'] == 'CRC'
    # basura no rompe nada
    for _ in range(300):
        basura = bytes(random.randrange(256) for _ in range(random.randrange(0, 40)))
        assert trama.leer_trama(basura)['valida'] in (True, False)


def prueba_enlace():
    assert enlace.seq_ordenadas([65534, 65535, 0, 1]) == [65534, 65535, 65536, 65537]
    # nodo reiniciado (seq vuelve a 50): no son 7000 tramas perdidas
    assert enlace.seq_ordenadas([7100, 7101, 7103, 50, 51]) == [7100, 7101, 7103, 7104, 7105]
    # llegada un poco desordenada no se toma como reinicio
    assert enlace.seq_ordenadas([10, 12, 11, 13]) == [10, 12, 11, 13]
    filas = [{'seq': s, 'rssi': -90.0, 'ruido': -110.0, 'ts_nodo': 100 + s, 't_srv': 101 + s, 'bytes_payload': 5}
             for s in range(20) if s not in (3, 4)]
    q = enlace.calidad(filas)
    assert q['esperadas'] == 20 and q['recibidas'] == 18 and q['per_pct'] == 10.0
    assert q['snr_medio'] == 20.0 and q['latencia_media_s'] == 1.0


def prueba_api():
    c = central.app.test_client()
    v3 = {'nivel_cm': 40, 'confianza': 90, 'id_frame': 1}
    buena = trama.armar_trama(2, 1, 3, 1, 1700000000, v3).hex()
    mala = bytearray(bytes.fromhex(buena))
    mala[3] ^= 0xFF
    cuerpo = {'gw': 'GW-T', 'tramas': [{'hex': buena, 'rssi': -80, 'ruido': -110},
                                       {'hex': buena},                   # duplicada
                                       {'hex': mala.hex()},              # CRC malo
                                       {'hex': 'zz'}]}                   # hex invalido
    assert c.post('/api/ingesta', json=cuerpo).status_code == 401       # sin clave
    r = c.post('/api/ingesta', json=cuerpo, headers={'X-Clave': 'clave-de-prueba'}).get_json()
    assert r['ok'] and r['recibidas'] == 4 and r['validas'] == 2
    assert [x['duplicada'] for x in r['detalle']] == [False, True, False, False]
    assert r['detalle'][2]['error'] == 'CRC' and r['detalle'][3]['error'] == 'HEX_INVALIDO'
    res = c.get('/api/resumen').get_json()
    assert res['nivel_cm'] == 40 and res['rio'] == 'NORMAL' and res['tramas']['duplicadas'] == 1

    # sube 20 cm de golpe: alerta por velocidad de subida, y UNA sola aunque sigan llegando lecturas altas
    for s, nivel in ((2, 60), (3, 120), (4, 125)):
        d = trama.armar_trama(2, 1, 3, s, 1700000000 + s, {'nivel_cm': nivel, 'confianza': 90, 'id_frame': s})
        c.post('/api/ingesta', json={'tramas': [{'hex': d.hex()}]}, headers={'X-Clave': 'clave-de-prueba'})
    alertas = c.get('/api/alertas').get_json()
    assert [a['estado'] for a in alertas] == ['ALERTA'] and 'subio' in alertas[0]['motivo'], alertas
    for ruta in ('/', '/nodos', '/enlace', '/capacidad', '/alertas', '/tramas',
                 '/api/enlace', '/api/tramas', '/api/serie', '/api/capacidad'):
        assert c.get(ruta).status_code == 200, ruta


def prueba_capacidad():
    # 20 bytes en SF7 / 125 kHz / 4/5 dura 56.6 ms (calculadora de The Things Network)
    assert abs(capacidad.tiempo_en_aire(20, sf=7, bw=125000, cr=1) - 0.05658) < 0.0001
    # SF12 / 125 kHz activa la optimizacion de baja tasa: 20 bytes = 1318.9 ms (misma calculadora)
    assert abs(capacidad.tiempo_en_aire(20, sf=12, bw=125000, cr=1) - 1.3189) < 0.001
    assert abs(capacidad.tasa_bits(7, 125000, 1) - 5468.75) < 0.01
    assert capacidad.prob_choque(1, 60, 0.2) == 0
    # la simulacion de Monte Carlo coincide con la formula de ALOHA (menos de 1.5 puntos de diferencia)
    for n in (3, 10, 40):
        assert abs(capacidad.simular(n, 60, 0.2) - capacidad.prob_choque(n, 60, 0.2)) < 0.015, n
    n = capacidad.nodos_maximos(60, 0.2, 0.05)
    assert capacidad.prob_choque(n, 60, 0.2) <= 0.05 < capacidad.prob_choque(n + 1, 60, 0.2)


if __name__ == '__main__':
    for nombre, f in list(globals().items()):
        if nombre.startswith('prueba_'):
            f()
            print('ok', nombre)
    print('todas las pruebas pasaron')
