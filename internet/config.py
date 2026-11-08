# Configuracion de la central de monitoreo.
# Lo que cambie el grupo (claves, cifrado, umbrales) se cambia aqui y en ningun otro lado.
import os

# Clave que el gateway manda en la cabecera X-Clave para poder subir tramas.
CLAVE_INGESTA = os.environ.get('SEI_CLAVE', 'cambiar-esta-clave')

BASE_DATOS = os.path.join(os.path.dirname(__file__), 'datos', 'central.db')
PUERTO = int(os.environ.get('SEI_PUERTO', '8160'))

# Tramas version 0x02: el emisor hace  payload -> cifrar -> Hamming(7,4) -> CRC
# y la central deshace en orden inverso. Version 0x01 va en claro.
CIFRADO = 'vigenere'          # 'ninguno', 'vigenere' o 'aes-ctr'
USAR_HAMMING = True
# Las claves de abajo son de DEMOSTRACION (el repo es publico). Las reales se ponen en variables
# de entorno del servidor (SEI_VIGENERE, SEI_AES_1..3 en hex) y en el firmware de cada nodo.
CLAVE_VIGENERE = os.environ.get('SEI_VIGENERE', 'SEI2026').encode()
CLAVES_AES = {                # una clave de 16 bytes por nodo
    n: bytes.fromhex(os.environ.get('SEI_AES_%d' % n, demo))
    for n, demo in ((1, '000102030405060708090a0b0c0d0e0f'),
                    (2, '101112131415161718191a1b1c1d1e1f'),
                    (3, '202122232425262728292a2b2c2d2e2f'))
}

# Niveles del rio (cm sobre el cero de la regla). Se recalibran en sitio.
NIVEL_VIGILANCIA = 50
NIVEL_ALERTA = 100
SUBIDA_ALERTA_CM = 10         # subida en VENTANA_SUBIDA_S que tambien dispara alerta
VENTANA_SUBIDA_S = 600

# Cada nodo reporta cada PERIODO_S; se da por caido si no se le oye en 3 periodos.
PERIODO_S = 60

# Calidad de enlace (ppt WSN): WMEWMA y estimador de Kalman.
VENTANA_WMEWMA = 10           # tramas esperadas por ventana
ALFA_WMEWMA = 0.6             # peso de la historia
KALMAN_Q = 0.5                # ruido del proceso (dB^2)
KALMAN_R = 4.0                # ruido de la medicion de RSSI (dB^2)

# Radio LoRa (E220-400T22S, chip LLCC68). Velocidad en el aire de fabrica 2.4k = SF11 (manual Ebyte p. 8);
# el LLCC68 solo llega a SF11 con BW 500 kHz, y SF*BW/2^SF*CR = 2.1 kbps confirma los 2.4k nominales.
LORA_SF = 11
LORA_BW_HZ = 500_000
LORA_CR = 1                   # CR = 4/(4+1) = 4/5
LORA_PREAMBULO = 8            # simbolos (valor por defecto de LoRa)
LORA_I_TX_A = 0.110           # corriente al transmitir a 22 dBm: 90-110 mA (manual Ebyte)
LORA_VCC = 3.3                # tension del modulo en los nodos (se confirma con el INA219)

# SNR minimo para demodular: -7.5 dB en SF7 y 2.5 dB menos por cada SF (Semtech). Centro de la curva PRR vs SNR.
SNR_LIMITE_DB = -7.5 - 2.5 * (LORA_SF - 7)
