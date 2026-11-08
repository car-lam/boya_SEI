# Gateway en la PYNQ

Recibe por LoRa (E220) las tramas de los PSoC, agrega el nivel de la cámara (N3 está en la misma placa) y sube todo a la central (`sei.silosense.dev`). Si no hay señal, guarda en disco y reintenta; las ALERT se suben al instante.

```
PSoC #1 ─┐                        ┌── vision (N3) escribe n3_nivel.json
PSoC #2 ─┴─LoRa─► E220 ─UART─► gateway_pynq.py ─► SIM800L (AT) o internet de la PYNQ ─► central
```

## Probarlo sin hardware

```bash
python3 gateway_pynq.py --prueba --url http://sei.silosense.dev/api/ingesta
python3 pruebas_gateway.py
```

`--prueba` simula el E220 y la cámara y sube a la central de verdad.

## Instalar en la PYNQ

1. Copiar a `/home/xilinx/sei/` la carpeta `gateway/` junto con `trama.py` y `config.py` (el gateway usa el mismo formato de trama y el mismo cifrado que la central).
2. `pip3 install pyserial requests`
3. Poner la clave (la tiene Raith) en `/home/xilinx/sei/clave.env` con la línea `SEI_CLAVE=<clave>`. Para correrlo a mano: `export $(cat /home/xilinx/sei/clave.env)`.
4. Revisar al inicio de `gateway_pynq.py`: `PUERTO_LORA`, `SALIDA` (`internet` o `sim800l`), `PUERTO_SIM800`, `APN`.
5. Correr: `python3 gateway/gateway_pynq.py`. Para que arranque solo al prender la placa, copiar `sei-gateway.service` a `/etc/systemd/system/` y ejecutar `sudo systemctl enable --now sei-gateway`.

## Conexiones

| Módulo | A la PYNQ | Notas |
|---|---|---|
| E220-400T22S | Adaptador USB-UART 3.3 V → `/dev/ttyUSB0` | TX↔RX cruzados, GND común. M0 = M1 = 0 (modo normal). AUX libre. |
| SIM800L | Otro USB-UART → `/dev/ttyUSB1` | Fuente propia de 3.7–4.2 V que entregue picos de 2 A (con la de la PYNQ se reinicia). Chip con datos. |

También se pueden usar las UART de la PYNQ por los pines PMOD/Arduino, pero eso exige agregarlas al overlay de Vivado. Con el adaptador USB no hay que tocar el overlay.

## Configurar el E220 (una vez)

Con la herramienta de Ebyte (RF_Setting) o en modo configuración (M0 = M1 = 1):

- Mismo canal, velocidad de aire y dirección en los 3 módulos.
- **REG3 bit 7, "Enable RSSI bytes"**: cada paquete recibido trae al final un byte con el RSSI (dBm = −(256 − byte)). Si no se activa, poner `LORA_CON_RSSI = False`.
- **REG1 bit 5, "RSSI Ambient Noise Enable"**: el gateway pide el ruido cada 30 s con `C0 C1 C2 C3 00 01` y la central calcula SNR = RSSI − ruido. Si no se activa, poner `LORA_PEDIR_RUIDO_S = 0`.
- Referencia: `datasheets/LoRa_E220/E220-400T22S_UserManual_Ebyte.pdf`, sección de registros.

## Lo que tiene que hacer el programa de visión

Cada vez que mide, llamar:

```python
from gateway_pynq import publicar_nivel
publicar_nivel('/home/xilinx/sei/n3_nivel.json', nivel_cm, confianza, id_frame)
```

Con eso basta: el gateway lo detecta, arma la trama de N3 (o ALERT si pasa el umbral) y la sube.

## Pendiente de probar con hardware

- El parser del E220 y la subida por internet están probados con un puerto simulado (`loop://`) y con la central real.
- Los comandos AT del SIM800L siguen la guía del fabricante, pero **no se han probado en un módulo real**. Primero hay que confirmar que registra en la red 2G (`AT+CREG?` → `0,1`).
