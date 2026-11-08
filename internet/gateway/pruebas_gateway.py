# Pruebas del gateway sin hardware:  python pruebas_gateway.py
import os
import sys
import time

import serial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import trama               # noqa: E402
import gateway_pynq as gw  # noqa: E402

v1 = {'temp_C': 19.3, 'hr_pct': 78.0, 'presion_hPa': 1011.0, 'gas_ohm': 51000}
a = trama.armar_trama(2, 1, 1, 7, 1700000000, v1)
b = trama.armar_trama(1, 1, 1, 8, 1700000001, v1)
RUIDO = bytes([0xC1, 0x00, 0x01, 256 - 110])          # respuesta del E220 al pedido de ruido

# un paquete con su byte de RSSI (-92 dBm)
assert gw.separar_tramas(a + bytes([256 - 92]), True) == ([(a, -92)], None)
# dos paquetes pegados en la UART
assert gw.separar_tramas(a + bytes([164]) + b + bytes([150]), True) == ([(a, -92), (b, -106)], None)
# sin byte de RSSI
assert gw.separar_tramas(a, False) == ([(a, None)], None)
# respuesta de ruido sola, antes o entre paquetes
assert gw.separar_tramas(RUIDO, True) == ([], -110)
assert gw.separar_tramas(RUIDO + a + bytes([164]) + RUIDO + b + bytes([150]), True) == ([(a, -92), (b, -106)], -110)
# basura: se manda igual para que la central la cuente como mala
assert gw.separar_tramas(b'\x99\x01\x02', True) == ([(b'\x99\x01', -(256 - 2))], None)
# la central entiende lo que separa el gateway
assert trama.leer_trama(gw.separar_tramas(a + bytes([164]), True)[0][0][0])['valores'] == v1

# por un puerto simulado, con pausas como en el aire
gw.LORA_PEDIR_RUIDO_S = 0
uart = serial.serial_for_url('loop://', timeout=0)
lector = gw.LectorLora(uart)
uart.write(RUIDO)
lector.leer(); time.sleep(0.05)
assert lector.leer() == [] and lector.ruido == -110
uart.write(a + bytes([256 - 95]))
lector.leer(); time.sleep(0.05)
assert lector.leer() == [(a, -95)]
print('pruebas del gateway: ok')
