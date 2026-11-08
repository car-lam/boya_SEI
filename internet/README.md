# Central de monitoreo SEI

Recibe las tramas que sube el gateway, las valida (Hamming, CRC, duplicados), las descifra, las guarda en SQLite y las muestra en **https://sei.silosense.dev**.

```
Nodos N1 N2 N3 --LoRa--> Gateway --HTTP POST--> Central (Flask + SQLite) --> Web
                          (SIM800L o Ethernet)
```

## Dónde corre

En AWS: EC2 `SEI` (t3.micro, Ohio; la IP y la llave SSH se guardan fuera del repo, en `~/.sei/ip` y `~/.sei/llave`), con tres servicios que arrancan solos: `sei-central`, `sei-simulador` (datos de demostración hasta tener la radio) y `cloudflared` (túnel hacia `sei.silosense.dev`; el servidor no tiene puertos web abiertos).

```bash
bash desplegar.sh                                   # subir cambios del codigo y reiniciar
ssh -i <llave> ubuntu@<ip> 'sudo systemctl stop sei-simulador && sudo systemctl disable sei-simulador'   # cuando llegue la radio real
python pruebas.py                                   # pruebas (en la laptop)
```

`iniciar.ps1` levanta todo en la laptop. **No usarlo mientras corre en AWS**: el mismo túnel quedaría en dos máquinas y Cloudflare repartiría las visitas entre ambas.

La clave del gateway está en la variable de usuario `SEI_CLAVE` (no va en el código). Para empezar de cero se borra `datos/central.db`.

## Cómo sube datos el gateway

`POST http://sei.silosense.dev/api/ingesta` (también por https) con la cabecera `X-Clave: <SEI_CLAVE>` y el cuerpo:

```json
{"gw": "GW1",
 "tramas": [{"hex": "0201030137...", "rssi": -87, "ruido": -112, "t_rx": 1762560000}]}
```

| Campo | Qué es |
|---|---|
| `hex` | La trama tal como llegó por LoRa, en hexadecimal |
| `rssi` | RSSI de esa trama en dBm (el E220 lo agrega como un byte extra si se activa en su registro; dBm = −(256 − byte); verificar en el manual del E220) |
| `ruido` | Ruido ambiente en dBm (el E220 lo reporta por comando; opcional) |
| `t_rx` | Hora Unix en que el gateway la recibió (opcional) |

Respuesta: `{"ok": true, "recibidas": n, "validas": m, "detalle": [...]}`. **El gateway borra su búfer solo si recibe `ok: true`**; si no hay respuesta, guarda y reintenta. Las tramas repetidas no se duplican en la base de datos.

### Con el SIM800L (comandos AT por UART)

```
AT                                   -> OK
AT+CSQ                               -> señal (0-31; 99 = sin señal)
AT+CREG?                             -> +CREG: 0,1  registrado
AT+SAPBR=3,1,"CONTYPE","GPRS"
AT+SAPBR=3,1,"APN","<apn del operador>"
AT+SAPBR=1,1                         -> abre la conexión de datos
AT+HTTPINIT
AT+HTTPPARA="CID",1
AT+HTTPPARA="URL","http://sei.silosense.dev/api/ingesta"
AT+HTTPPARA="CONTENT","application/json"
AT+HTTPPARA="USERDATA","X-Clave: <SEI_CLAVE>"
AT+HTTPDATA=<largo del json>,10000   -> DOWNLOAD, enviar el JSON
AT+HTTPACTION=1                      -> +HTTPACTION: 1,200,<largo>
AT+HTTPREAD                          -> respuesta
AT+HTTPTERM
```

Se usa HTTP simple porque el HTTPS del SIM800L es antiguo. El payload ya va cifrado desde el nodo. El SIM800L es 2G: primero hay que comprobar con un chip que registra en Lima (`AT+CREG?`).

## Trama (la misma que arman los nodos)

`version(1) tipo(1) id_nodo(1) seq(2) timestamp(4) largo(1) payload crc(2)`, big-endian.

- Versión 1: payload en claro. Versión 2: payload cifrado + Hamming (7,4).
- El nodo hace **payload → cifrar → CRC-CCITT → Hamming**. El CRC va antes de Hamming para que la central primero corrija y después compruebe.
- Tipos: 1 DATA, 2 REQ, 3 ACK, 4 ALERT, 5 HEARTBEAT, 6 TIME_SYNC.
- Payloads: N1 `temp int16 ×0.01 °C, hr uint16 ×0.01 %, presión uint16 ×0.1 hPa, gas uint32 Ω`; N2 `co2 uint16 ppm, temp int16, hr uint16`; N3 `nivel int16 cm, confianza uint8, id_frame uint16`; HEARTBEAT `vbat uint16 mV, reinicios uint16`.

El cifrado (`ninguno`, `vigenere`, `aes-ctr`), las claves y los umbrales se cambian en `config.py`.

## Qué calcula (métodos de las ppts del curso)

| Página | Métodos |
|---|---|
| Resumen | Nivel, estado NORMAL / VIGILANCIA / ALERTA (por nivel o por velocidad de subida) |
| Calidad de enlace | PER por número de secuencia, RSSI, SNR = RSSI − ruido, WMEWMA, Kalman (KLE), latencia, throughput (ppt *Red de Sensores Inalámbricos*) |
| Capacidad | Tiempo en el aire (T<sub>s</sub> = 2^SF/BW, DR = SF·BW/2^SF·CR; ppt *Comunicaciones inalámbricas*), probabilidad de choque ALOHA, nodos máximos, simulación de Monte Carlo y verificación con la carga medida; energía de radio por trama |
| Alertas | Solo se registra el cambio de estado, como TEEN |
| Tramas | Hamming (7,4), CRC-CCITT (ppt *Detección y corrección de errores*); Vigenère / AES (ppt *Criptografía*) |

## Archivos

| Archivo | Qué hace |
|---|---|
| `app.py` | Servidor: ingesta, base de datos, API y páginas |
| `trama.py` | Arma y lee tramas: CRC, Hamming, cifrados, payloads |
| `enlace.py` | Métricas de calidad de enlace |
| `capacidad.py` | Capacidad de la red: tiempo en el aire, choques, nodos máximos |
| `simulador.py` | Simula los 3 nodos y el gateway (pérdidas, bits malos, duplicados, crecida) |
| `config.py` | Claves, cifrado, umbrales, parámetros |
| `pruebas.py` | Pruebas de todo lo anterior |
