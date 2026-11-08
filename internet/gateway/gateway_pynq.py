# Gateway del proyecto, corre en la PYNQ (Linux, Python 3).
#
#  1. Escucha el modulo LoRa E220 por UART: cada paquete que llega de un PSoC es una trama.
#  2. Lee el nivel que deja el programa de vision (N3 esta en la misma placa, no pasa por LoRa)
#     y lo convierte en trama con el mismo formato.
#  3. Guarda todo en un bufer en disco y lo sube a la central por HTTP. Solo borra del bufer
#     lo que la central confirmo; si no hay senal, guarda y reintenta.
#
# Salida a internet (opcion SALIDA):
#   'internet' -> la PYNQ ya tiene internet (Ethernet, modem USB 4G, celular compartido)
#   'sim800l'  -> la PYNQ manda los datos por el SIM800L con comandos AT por UART
#
#   python3 gateway_pynq.py              funcionamiento normal
#   python3 gateway_pynq.py --prueba     sin hardware: simula el E220 y la camara
import argparse
import json
import os
import sys
import time

import serial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import config  # noqa: E402
import trama   # noqa: E402

# ---------- Configuracion del gateway ----------
URL_CENTRAL = 'http://sei.silosense.dev/api/ingesta'
CLAVE = os.environ.get('SEI_CLAVE', config.CLAVE_INGESTA)
GW_ID = 'GW-PYNQ'

PUERTO_LORA = '/dev/ttyUSB0'      # E220 por un adaptador USB-UART de 3.3 V
BAUDIOS_LORA = 9600               # valor de fabrica del E220
LORA_CON_RSSI = True              # el E220 agrega 1 byte de RSSI al final de cada paquete
                                  # (manual E220: REG3 bit 7 "Enable RSSI bytes"; dBm = -(256 - byte))
LORA_PEDIR_RUIDO_S = 30           # cada 30 s pide el ruido ambiente (REG1 bit 5 activado); 0 = no pedir
PEDIDO_RUIDO = bytes([0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x01])   # respuesta: C1 00 01 <ruido>
SILENCIO_FIN_PAQUETE_S = 0.03     # si la UART se calla 30 ms, el paquete termino

SALIDA = 'internet'               # 'internet' o 'sim800l'
PUERTO_SIM800 = '/dev/ttyUSB1'
APN = 'claro.pe'                  # Claro: claro.pe · Movistar: movistar.pe · Entel: entel.pe (verificar)

ARCHIVO_NIVEL = '/home/xilinx/sei/n3_nivel.json'   # lo escribe el programa de vision
VERSION_TRAMA = 2                 # 1 = en claro, 2 = cifrado + Hamming (igual que los PSoC)
CARPETA = os.path.join(os.path.expanduser('~'), 'sei_gateway')
ARCHIVO_BUFER = os.path.join(CARPETA, 'bufer.jsonl')
ARCHIVO_SEQ = os.path.join(CARPETA, 'seq_n3.txt')
MAX_BUFER = 5000                  # si se llena, se pierden las tramas mas viejas
ENVIO_CADA_S = 10
MAX_POR_ENVIO = 50                # el SIM800L maneja mal cuerpos grandes


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------- LoRa: de bytes de la UART a tramas ----------

def separar_tramas(bloque, con_rssi):
    """Un paquete del E220 trae una trama (y quiza el byte de RSSI al final).
    Si llegaran varias pegadas, las separa usando el campo 'largo' de la cabecera.
    Devuelve (tramas, ruido): ruido es la respuesta C1 00 01 <byte> si vino en el bloque."""
    tramas = []
    ruido = None
    i = 0
    while i < len(bloque):
        resto = bloque[i:]
        if len(resto) >= 4 and resto[:3] == b'\xC1\x00\x01':
            ruido = -(256 - resto[3])
            i += 4
            continue
        if len(resto) >= trama.LARGO_CABECERA:
            total = trama.LARGO_CABECERA + resto[9] + 2
            extra = 1 if con_rssi else 0
            if len(resto) >= total + extra and resto[0] in (1, 2):
                datos = resto[:total]
                rssi = -(256 - resto[total]) if con_rssi else None
                tramas.append((datos, rssi))
                i += total + extra
                continue
        # no calza con el formato: se manda tal cual para que la central la registre como mala
        if con_rssi and len(resto) > 1:
            tramas.append((resto[:-1], -(256 - resto[-1])))
        else:
            tramas.append((resto, None))
        break
    return tramas, ruido


class LectorLora:
    def __init__(self, puerto):
        self.uart = puerto
        self.bloque = bytearray()
        self.ultimo = 0.0
        self.ruido = None               # ultimo ruido ambiente medido (dBm)
        self.proximo_ruido = 0.0

    def pedir_ruido(self):
        if LORA_PEDIR_RUIDO_S and time.time() >= self.proximo_ruido and not self.bloque:
            self.uart.write(PEDIDO_RUIDO)
            self.proximo_ruido = time.time() + LORA_PEDIR_RUIDO_S

    def leer(self):
        """Devuelve los paquetes completos que llegaron desde la ultima llamada."""
        self.pedir_ruido()
        n = self.uart.in_waiting
        if n:
            self.bloque += self.uart.read(n)
            self.ultimo = time.time()
        if self.bloque and time.time() - self.ultimo > SILENCIO_FIN_PAQUETE_S:
            paquete = bytes(self.bloque)
            self.bloque.clear()
            tramas, ruido = separar_tramas(paquete, LORA_CON_RSSI)
            if ruido is not None:
                self.ruido = ruido
            return tramas
        return []


# ---------- N3: el nivel de la camara ----------

class LectorNivel:
    def __init__(self, archivo):
        self.archivo = archivo
        self.ultima_t = None
        os.makedirs(CARPETA, exist_ok=True)
        try:
            with open(ARCHIVO_SEQ) as f:
                self.seq = int(f.read().strip())
        except (OSError, ValueError):
            self.seq = 0

    def leer(self):
        """Si la vision publico un nivel nuevo, arma la trama de N3."""
        try:
            with open(self.archivo) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        if d.get('t') == self.ultima_t:
            return None
        self.ultima_t = d.get('t')
        self.seq = (self.seq + 1) % 65536
        with open(ARCHIVO_SEQ, 'w') as f:
            f.write(str(self.seq))
        v = {'nivel_cm': int(d['nivel_cm']), 'confianza': int(d['confianza']), 'id_frame': int(d['id_frame']) % 65536}
        tipo = 1
        if v['nivel_cm'] >= config.NIVEL_ALERTA:
            tipo, v['nivel_alerta'] = 4, 2
        return trama.armar_trama(VERSION_TRAMA, tipo, 3, self.seq, int(time.time()), v)


# ---------- Bufer en disco ----------

class Bufer:
    def __init__(self, archivo):
        self.archivo = archivo
        self.items = []
        try:
            with open(archivo) as f:
                self.items = [json.loads(x) for x in f if x.strip()]
            log('bufer recuperado:', len(self.items), 'tramas pendientes')
        except (OSError, ValueError):
            pass

    def guardar(self):
        tmp = self.archivo + '.tmp'
        with open(tmp, 'w') as f:
            for it in self.items:
                f.write(json.dumps(it) + '\n')
        os.replace(tmp, self.archivo)        # si se corta la luz, queda el archivo viejo o el nuevo, nunca uno a medias

    def agregar(self, item):
        self.items.append(item)
        if len(self.items) > MAX_BUFER:
            del self.items[:len(self.items) - MAX_BUFER]
        self.guardar()

    def quitar(self, n):
        del self.items[:n]
        self.guardar()


# ---------- Subida a la central ----------

def subir_internet(cuerpo):
    import requests
    r = requests.post(URL_CENTRAL, json=cuerpo, headers={'X-Clave': CLAVE}, timeout=20)
    return r.status_code, r.text


class Sim800:
    """SIM800L por comandos AT (2G, GPRS). Ver README de la central."""

    def __init__(self, puerto):
        self.s = serial.Serial(puerto, 9600, timeout=0.2)
        self.listo = False

    def at(self, cmd, espera=('OK',), timeout=5.0):
        self.s.reset_input_buffer()
        self.s.write((cmd + '\r\n').encode())
        return self.esperar(espera, timeout)

    def esperar(self, espera=('OK',), timeout=5.0):
        resp = ''
        fin = time.time() + timeout
        while time.time() < fin:
            resp += self.s.read(256).decode(errors='replace')
            if any(e in resp for e in espera) or 'ERROR' in resp:
                break
        return resp

    def conectar(self):
        if 'OK' not in self.at('AT'):
            raise IOError('el SIM800L no responde')
        reg = self.at('AT+CREG?')
        if ',1' not in reg and ',5' not in reg:
            raise IOError('sin registro en la red 2G: ' + reg.strip())
        self.at('AT+SAPBR=3,1,"CONTYPE","GPRS"')
        self.at('AT+SAPBR=3,1,"APN","%s"' % APN)
        self.at('AT+SAPBR=1,1', timeout=30)           # da ERROR si ya estaba abierta, no importa
        if '0.0.0.0' in self.at('AT+SAPBR=2,1'):
            raise IOError('no obtuvo direccion IP (revisar APN y saldo de datos)')
        self.listo = True
        log('SIM800L conectado, senal', self.at('AT+CSQ').strip().replace('\r\n', ' '))

    def post(self, cuerpo):
        if not self.listo:
            self.conectar()
        datos = json.dumps(cuerpo, separators=(',', ':')).encode()
        url = URL_CENTRAL.replace('https://', 'http://')    # el HTTPS del SIM800L es antiguo
        self.at('AT+HTTPTERM')
        self.at('AT+HTTPINIT')
        self.at('AT+HTTPPARA="CID",1')
        self.at('AT+HTTPPARA="URL","%s"' % url)
        self.at('AT+HTTPPARA="CONTENT","application/json"')
        self.at('AT+HTTPPARA="USERDATA","X-Clave: %s"' % CLAVE)
        if 'DOWNLOAD' not in self.at('AT+HTTPDATA=%d,10000' % len(datos), espera=('DOWNLOAD',)):
            self.listo = False
            raise IOError('el SIM800L no acepto los datos')
        self.s.write(datos)
        self.esperar(timeout=5)                         # el modulo responde OK al recibir todo
        r = self.at('AT+HTTPACTION=1', espera=('+HTTPACTION:',), timeout=40)
        try:
            codigo = int(r.split('+HTTPACTION:')[1].split(',')[1])
        except (IndexError, ValueError):
            self.listo = False
            raise IOError('sin respuesta HTTP: ' + r.strip())
        texto = self.at('AT+HTTPREAD', timeout=5)
        self.at('AT+HTTPTERM')
        cuerpo_resp = texto[texto.find('{'):texto.rfind('}') + 1] if '{' in texto else ''
        return codigo, cuerpo_resp


def enviar(bufer, sim, max_lotes=5):
    """Sube de a MAX_POR_ENVIO tramas; tras un corte vacia el bufer en varios lotes seguidos."""
    for _ in range(max_lotes):
        if not bufer.items:
            return
        lote = bufer.items[:MAX_POR_ENVIO]
        cuerpo = {'gw': GW_ID, 'tramas': lote}
        try:
            codigo, texto = sim.post(cuerpo) if sim else subir_internet(cuerpo)
            resp = json.loads(texto) if texto else {}
        except Exception as e:                  # sin senal, sin respuesta, etc.: se reintenta luego
            log('no se pudo subir (%s); %d tramas en el bufer' % (e, len(bufer.items)))
            return
        if codigo != 200 or not resp.get('ok'):
            log('la central respondio %s; se reintenta' % codigo)
            return
        bufer.quitar(len(lote))
        log('subidas %d (validas %d), quedan %d' % (resp['recibidas'], resp['validas'], len(bufer.items)))


# ---------- Modo prueba (sin hardware) ----------

def preparar_prueba():
    """Un puerto 'loop://' hace de E220: lo que se escribe se lee de vuelta."""
    import random
    uart = serial.serial_for_url('loop://', timeout=0)
    seq = {1: 0, 2: 0}

    def inyectar():
        uart.write(bytes([0xC1, 0x00, 0x01, 256 - random.randint(108, 114)]))   # respuesta de ruido del E220
        time.sleep(0.1)
        for nodo in (1, 2):
            seq[nodo] += 1
            if nodo == 1:
                v = {'temp_C': 19.3, 'hr_pct': 78.0, 'presion_hPa': 1011.0, 'gas_ohm': 51000}
            else:
                v = {'co2_ppm': 431, 'temp_C': 18.8, 'hr_pct': 80.0}
            d = trama.armar_trama(VERSION_TRAMA, 1, nodo, seq[nodo], int(time.time()), v)
            rssi = random.randint(-110, -85)
            uart.write(d + bytes([256 + rssi]))
            time.sleep(0.1)                 # silencio entre paquetes, como en el aire
        os.makedirs(os.path.dirname(ARCHIVO_NIVEL), exist_ok=True)
        publicar_nivel(ARCHIVO_NIVEL, 40 + random.randint(-2, 2), random.randint(75, 95), seq[1])
    return uart, inyectar


def publicar_nivel(archivo, nivel_cm, confianza, id_frame):
    """Lo que debe llamar el programa de vision cada vez que mide (escritura atomica)."""
    tmp = archivo + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'nivel_cm': nivel_cm, 'confianza': confianza, 'id_frame': id_frame, 't': time.time()}, f)
    os.replace(tmp, archivo)


def main():
    global ARCHIVO_NIVEL, CARPETA, ARCHIVO_BUFER, ARCHIVO_SEQ, URL_CENTRAL, LORA_PEDIR_RUIDO_S
    ap = argparse.ArgumentParser()
    ap.add_argument('--prueba', action='store_true', help='simula el E220 y la camara')
    ap.add_argument('--url', default=URL_CENTRAL)
    a = ap.parse_args()
    URL_CENTRAL = a.url

    inyectar = None
    if a.prueba:
        CARPETA = os.path.join(os.path.expanduser('~'), 'sei_gateway_prueba')
        ARCHIVO_BUFER = os.path.join(CARPETA, 'bufer.jsonl')
        ARCHIVO_SEQ = os.path.join(CARPETA, 'seq_n3.txt')
        ARCHIVO_NIVEL = os.path.join(CARPETA, 'n3_nivel.json')
        os.makedirs(CARPETA, exist_ok=True)
        LORA_PEDIR_RUIDO_S = 0          # en el puerto simulado no hay modulo que conteste; la respuesta se inyecta
        uart, inyectar = preparar_prueba()
    else:
        os.makedirs(CARPETA, exist_ok=True)
        uart = serial.Serial(PUERTO_LORA, BAUDIOS_LORA, timeout=0)

    lora = LectorLora(uart)
    nivel = LectorNivel(ARCHIVO_NIVEL)
    bufer = Bufer(ARCHIVO_BUFER)
    sim = Sim800(PUERTO_SIM800) if SALIDA == 'sim800l' and not a.prueba else None
    log('gateway listo; LoRa en', 'loop://' if a.prueba else PUERTO_LORA, '; sube a', URL_CENTRAL)

    proximo_envio = 0.0
    proxima_prueba = 0.0
    while True:
        if inyectar and time.time() >= proxima_prueba:
            inyectar()
            proxima_prueba = time.time() + 5
        hay_alerta = False
        for datos, rssi in lora.leer():
            bufer.agregar({'hex': datos.hex(), 'rssi': rssi, 'ruido': lora.ruido, 't_rx': round(time.time(), 3)})
            log('LoRa: %d bytes, RSSI %s dBm, ruido %s dBm' % (len(datos), rssi, lora.ruido))
            hay_alerta = hay_alerta or (len(datos) > 1 and datos[1] == 4)
        d = nivel.leer()
        if d:
            bufer.agregar({'hex': d.hex(), 'rssi': None, 't_rx': round(time.time(), 3)})
            hay_alerta = hay_alerta or d[1] == 4
        if hay_alerta or time.time() >= proximo_envio:     # una ALERT no espera al siguiente envio
            enviar(bufer, sim)
            proximo_envio = time.time() + ENVIO_CADA_S
        time.sleep(0.005)


if __name__ == '__main__':
    main()
