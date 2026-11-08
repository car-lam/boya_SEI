# Arma y lee la trama de aplicacion del proyecto.
#
#  version(1) tipo(1) id_nodo(1) seq(2) timestamp(4) largo(1) payload(largo) crc(2)
#  todo en big-endian; el CRC cubre cabecera + payload (antes de Hamming, ver armar_trama).
#
# Metodos de las ppts del curso:
#  - CRC-CCITT  x^16 + x^12 + x^5 + 1  (ppt "Deteccion y correccion de errores")
#  - Hamming (7,4): 3 bits de paridad protegen 4 de datos, corrige 1 error
#  - Vigenere (polialfabetico) y AES (ppt "Criptografia")
import struct
import config

TIPOS = {1: 'DATA', 2: 'REQ', 3: 'ACK', 4: 'ALERT', 5: 'HEARTBEAT', 6: 'TIME_SYNC'}
NODOS = {0: 'GW', 1: 'N1', 2: 'N2', 3: 'N3'}
LARGO_CABECERA = 10


# ---------- CRC ----------

def crc16(datos):
    """CRC-CCITT, valor inicial 0xFFFF. '123456789' da 0x29B1."""
    crc = 0xFFFF
    for b in datos:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


# ---------- Hamming (7,4) ----------
# Posiciones 1..7 = p1 p2 d1 p3 d2 d3 d4. Cada byte se manda como dos palabras de 7 bits.

def hamming_codificar_nibble(n):
    d1, d2, d3, d4 = (n >> 3) & 1, (n >> 2) & 1, (n >> 1) & 1, n & 1
    p1 = d1 ^ d2 ^ d4
    p2 = d1 ^ d3 ^ d4
    p3 = d2 ^ d3 ^ d4
    bits = [p1, p2, d1, p3, d2, d3, d4]
    palabra = 0
    for b in bits:
        palabra = (palabra << 1) | b
    return palabra


def hamming_decodificar_palabra(palabra):
    """Devuelve (nibble, corregido). El sindrome da la posicion del bit malo."""
    bits = [(palabra >> (6 - i)) & 1 for i in range(7)]   # bits[0] es la posicion 1
    s1 = bits[0] ^ bits[2] ^ bits[4] ^ bits[6]
    s2 = bits[1] ^ bits[2] ^ bits[5] ^ bits[6]
    s3 = bits[3] ^ bits[4] ^ bits[5] ^ bits[6]
    sindrome = s1 + 2 * s2 + 4 * s3
    if sindrome:
        bits[sindrome - 1] ^= 1
    nibble = (bits[2] << 3) | (bits[4] << 2) | (bits[5] << 1) | bits[6]
    return nibble, sindrome != 0


def hamming_codificar(datos):
    salida = bytearray()
    for b in datos:
        salida.append(hamming_codificar_nibble(b >> 4))
        salida.append(hamming_codificar_nibble(b & 0x0F))
    return bytes(salida)


def hamming_decodificar(datos):
    """Devuelve (bytes, cantidad de bits corregidos)."""
    if len(datos) % 2:
        raise ValueError('Hamming: largo impar')
    salida = bytearray()
    corregidos = 0
    for i in range(0, len(datos), 2):
        alto, c1 = hamming_decodificar_palabra(datos[i] & 0x7F)
        bajo, c2 = hamming_decodificar_palabra(datos[i + 1] & 0x7F)
        salida.append((alto << 4) | bajo)
        corregidos += c1 + c2
    return bytes(salida), corregidos


# ---------- Cifrado ----------

def vigenere(datos, clave, descifrar=False):
    """Vigenere sobre bytes (mod 256)."""
    signo = -1 if descifrar else 1
    return bytes((b + signo * clave[i % len(clave)]) % 256 for i, b in enumerate(datos))


def aes_ctr(datos, id_nodo, seq, ts):
    """AES-128 en modo CTR: no agrega bytes. Cifrar y descifrar es la misma operacion."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    contador = bytes([0x01, id_nodo]) + struct.pack('>HI', seq, ts) + bytes(8)
    c = Cipher(algorithms.AES(config.CLAVES_AES[id_nodo]), modes.CTR(contador)).encryptor()
    return c.update(datos) + c.finalize()


def cifrar(payload, id_nodo, seq, ts):
    if config.CIFRADO == 'vigenere':
        return vigenere(payload, config.CLAVE_VIGENERE)
    if config.CIFRADO == 'aes-ctr':
        return aes_ctr(payload, id_nodo, seq, ts)
    return payload


def descifrar(payload, id_nodo, seq, ts):
    if config.CIFRADO == 'vigenere':
        return vigenere(payload, config.CLAVE_VIGENERE, descifrar=True)
    if config.CIFRADO == 'aes-ctr':
        return aes_ctr(payload, id_nodo, seq, ts)
    return payload


# ---------- Payload de cada nodo ----------

def leer_payload(id_nodo, tipo, p):
    """Convierte los bytes del payload en variables con unidades."""
    if tipo == 5:                                           # HEARTBEAT
        vbat, reinicios = struct.unpack('>HH', p[:4])
        return {'vbat_mV': vbat, 'reinicios': reinicios}
    if tipo not in (1, 4):
        return {}
    if id_nodo == 1:                                        # BME680
        t, hr, pres, gas = struct.unpack('>hHHI', p[:10])
        return {'temp_C': t / 100, 'hr_pct': hr / 100, 'presion_hPa': pres / 10, 'gas_ohm': gas}
    if id_nodo == 2:                                        # SCD41
        co2, t, hr = struct.unpack('>HhH', p[:6])
        return {'co2_ppm': co2, 'temp_C': t / 100, 'hr_pct': hr / 100}
    if id_nodo == 3:                                        # camara
        nivel, conf, frame = struct.unpack('>hBH', p[:5])
        r = {'nivel_cm': nivel, 'confianza': conf, 'id_frame': frame}
        if tipo == 4 and len(p) >= 6:
            r['nivel_alerta'] = p[5]
        return r
    return {}


def armar_payload(id_nodo, tipo, v):
    if tipo == 5:
        return struct.pack('>HH', v['vbat_mV'], v['reinicios'])
    if id_nodo == 1:
        return struct.pack('>hHHI', round(v['temp_C'] * 100), round(v['hr_pct'] * 100),
                           round(v['presion_hPa'] * 10), v['gas_ohm'])
    if id_nodo == 2:
        return struct.pack('>HhH', v['co2_ppm'], round(v['temp_C'] * 100), round(v['hr_pct'] * 100))
    if id_nodo == 3:
        p = struct.pack('>hBH', v['nivel_cm'], v['confianza'], v['id_frame'])
        if tipo == 4:
            p += bytes([v.get('nivel_alerta', 2)])
        return p
    return b''


# ---------- Trama completa ----------

def armar_trama(version, tipo, id_nodo, seq, ts, valores):
    """Lo que haria un nodo: payload -> cifrar -> CRC -> Hamming.

    El CRC se calcula ANTES de Hamming: asi el receptor primero corrige con Hamming
    y luego comprueba con el CRC que lo corregido es correcto. Si fuera al reves,
    un solo bit malo haria fallar el CRC y Hamming nunca llegaria a corregir nada.
    """
    payload = armar_payload(id_nodo, tipo, valores)
    if version == 2:
        payload = cifrar(payload, id_nodo, seq, ts)
    usa_hamming = version == 2 and config.USAR_HAMMING
    largo = len(payload) * 2 if usa_hamming else len(payload)
    cabecera = struct.pack('>BBBHIB', version, tipo, id_nodo, seq, ts, largo)
    crc = struct.pack('>H', crc16(cabecera + payload))
    if usa_hamming:
        payload = hamming_codificar(payload)
    return cabecera + payload + crc


def leer_trama(datos):
    """Valida y decodifica una trama. Nunca lanza excepcion: devuelve 'error' si algo falla."""
    r = {'valida': False, 'error': None, 'corregidos': 0, 'valores': {}}
    if len(datos) < LARGO_CABECERA + 2:
        r['error'] = 'MUY_CORTA'
        return r
    version, tipo, id_nodo, seq, ts, largo = struct.unpack('>BBBHIB', datos[:LARGO_CABECERA])
    r.update(version=version, tipo=TIPOS.get(tipo, '?%d' % tipo), id_nodo=id_nodo,
             nodo=NODOS.get(id_nodo, '?%d' % id_nodo), seq=seq, ts_nodo=ts)
    if len(datos) != LARGO_CABECERA + largo + 2:
        r['error'] = 'LARGO_INCORRECTO'
        return r
    cabecera = datos[:LARGO_CABECERA]
    payload = datos[LARGO_CABECERA:LARGO_CABECERA + largo]
    if version == 2 and config.USAR_HAMMING:
        try:
            payload, r['corregidos'] = hamming_decodificar(payload)
        except ValueError as e:
            r['error'] = 'HAMMING: %s' % e
            return r
    crc_recibido = struct.unpack('>H', datos[-2:])[0]
    if crc16(cabecera + payload) != crc_recibido:
        r['error'] = 'CRC'
        return r
    if version not in (1, 2) or tipo not in TIPOS or id_nodo not in NODOS:
        r['error'] = 'CABECERA'
        return r
    try:
        if version == 2:
            payload = descifrar(payload, id_nodo, seq, ts)
        r['valores'] = leer_payload(id_nodo, tipo, payload)
    except (struct.error, ValueError, KeyError) as e:
        r['error'] = 'PAYLOAD: %s' % e
        return r
    r['valida'] = True
    return r
