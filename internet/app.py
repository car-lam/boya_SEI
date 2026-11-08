# Central de monitoreo: recibe las tramas que sube el gateway, las valida,
# las guarda en SQLite y las muestra en la web.
#
#   python app.py            sirve en 127.0.0.1:8160 (el tunel de Cloudflare lo publica)
import hmac
import os
import sqlite3
import time

from flask import Flask, abort, g, jsonify, render_template, request

import capacidad
import config
import enlace
import trama

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 256 * 1024
MAX_TRAMAS_POR_ENVIO = 200

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tramas (
    id INTEGER PRIMARY KEY, t_srv REAL, gw TEXT, hex TEXT,
    valida INTEGER, error TEXT, version INTEGER, tipo TEXT, nodo TEXT,
    seq INTEGER, ts_nodo INTEGER, rssi REAL, ruido REAL, t_rx_gw REAL,
    duplicada INTEGER DEFAULT 0, corregidos INTEGER DEFAULT 0, bytes_payload INTEGER
);
CREATE INDEX IF NOT EXISTS i_tramas_nodo ON tramas(nodo, seq, ts_nodo);
CREATE TABLE IF NOT EXISTS lecturas (
    id INTEGER PRIMARY KEY, trama_id INTEGER, nodo TEXT, t REAL, variable TEXT, valor REAL
);
CREATE INDEX IF NOT EXISTS i_lecturas ON lecturas(nodo, variable, t);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY, t REAL, nodo TEXT, estado TEXT, nivel_cm REAL, motivo TEXT
);
CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT);
"""


def bd():
    if 'bd' not in g:
        g.bd = sqlite3.connect(config.BASE_DATOS, timeout=10)
        g.bd.row_factory = sqlite3.Row
    return g.bd


@app.teardown_appcontext
def cerrar_bd(_):
    c = g.pop('bd', None)
    if c is not None:
        c.close()


def crear_bd():
    os.makedirs(os.path.dirname(config.BASE_DATOS), exist_ok=True)
    c = sqlite3.connect(config.BASE_DATOS)
    c.executescript(ESQUEMA)
    c.execute('PRAGMA journal_mode=WAL')
    c.close()


# ---------- Estado del rio y alertas ----------

def leer_estado(c, clave, defecto=None):
    f = c.execute('SELECT valor FROM estado WHERE clave=?', (clave,)).fetchone()
    return f['valor'] if f else defecto


def evaluar_nivel(c, t, nivel, alerta_del_nodo):
    """Decide NORMAL / VIGILANCIA / ALERTA. Igual que TEEN (ppt WSN), solo se registra
    un evento cuando el estado cambia, no en cada lectura."""
    f = c.execute("SELECT MIN(valor) m FROM lecturas WHERE nodo='N3' AND variable='nivel_cm' AND t>=?",
                  (t - config.VENTANA_SUBIDA_S,)).fetchone()
    subida = nivel - f['m'] if f['m'] is not None else 0

    if alerta_del_nodo:
        nuevo, motivo = 'ALERTA', 'el nodo camara envio ALERT'
    elif nivel >= config.NIVEL_ALERTA:
        nuevo, motivo = 'ALERTA', 'nivel >= %d cm' % config.NIVEL_ALERTA
    elif subida >= config.SUBIDA_ALERTA_CM:
        nuevo, motivo = 'ALERTA', 'subio %.0f cm en %d min' % (subida, config.VENTANA_SUBIDA_S // 60)
    elif nivel >= config.NIVEL_VIGILANCIA:
        nuevo, motivo = 'VIGILANCIA', 'nivel >= %d cm' % config.NIVEL_VIGILANCIA
    else:
        nuevo, motivo = 'NORMAL', 'nivel bajo %d cm' % config.NIVEL_VIGILANCIA

    if nuevo != leer_estado(c, 'rio', 'NORMAL'):
        c.execute('INSERT INTO alertas(t, nodo, estado, nivel_cm, motivo) VALUES (?,?,?,?,?)',
                  (t, 'N3', nuevo, nivel, motivo))
        c.execute("INSERT OR REPLACE INTO estado VALUES ('rio', ?)", (nuevo,))


# ---------- Ingesta ----------

def numero(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def guardar_trama(c, gw, item, t_srv):
    hex_txt = str(item.get('hex', '')).strip().replace(' ', '')
    try:
        datos = bytes.fromhex(hex_txt)
    except ValueError:
        datos = None
    r = trama.leer_trama(datos) if datos is not None else {'valida': False, 'error': 'HEX_INVALIDO'}

    duplicada = 0
    if r['valida']:
        previa = c.execute('SELECT 1 FROM tramas WHERE valida=1 AND duplicada=0 AND nodo=? AND seq=? AND ts_nodo=?',
                           (r['nodo'], r['seq'], r['ts_nodo'])).fetchone()
        duplicada = 1 if previa else 0

    cur = c.execute(
        'INSERT INTO tramas(t_srv, gw, hex, valida, error, version, tipo, nodo, seq, ts_nodo, rssi, ruido,'
        ' t_rx_gw, duplicada, corregidos, bytes_payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (t_srv, gw, hex_txt[:600], int(r['valida']), r['error'], r.get('version'), r.get('tipo'), r.get('nodo'),
         r.get('seq'), r.get('ts_nodo'), numero(item.get('rssi')), numero(item.get('ruido')),
         numero(item.get('t_rx')), duplicada, r.get('corregidos', 0),
         len(datos) - 12 if datos and len(datos) >= 12 else 0))

    if r['valida'] and not duplicada:
        for var, valor in r['valores'].items():
            c.execute('INSERT INTO lecturas(trama_id, nodo, t, variable, valor) VALUES (?,?,?,?,?)',
                      (cur.lastrowid, r['nodo'], t_srv, var, valor))
        if r['nodo'] == 'N3' and 'nivel_cm' in r['valores']:
            evaluar_nivel(c, t_srv, r['valores']['nivel_cm'], r['tipo'] == 'ALERT')

    return {'valida': r['valida'], 'error': r['error'], 'duplicada': bool(duplicada),
            'nodo': r.get('nodo'), 'seq': r.get('seq'), 'corregidos': r.get('corregidos', 0)}


@app.post('/api/ingesta')
def ingesta():
    clave = request.headers.get('X-Clave', '')
    if not hmac.compare_digest(clave, config.CLAVE_INGESTA):
        abort(401)
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get('tramas'), list):
        return jsonify(ok=False, error='se espera {"gw": "...", "tramas": [{"hex": "..."}]}'), 400
    if len(cuerpo['tramas']) > MAX_TRAMAS_POR_ENVIO:
        return jsonify(ok=False, error='maximo %d tramas por envio' % MAX_TRAMAS_POR_ENVIO), 413
    gw = str(cuerpo.get('gw', 'GW?'))[:20]
    t_srv = time.time()
    c = bd()
    resultados = [guardar_trama(c, gw, it, t_srv) for it in cuerpo['tramas'] if isinstance(it, dict)]
    c.commit()
    validas = sum(1 for x in resultados if x['valida'])
    # El gateway solo borra su bufer cuando recibe ok=true
    return jsonify(ok=True, recibidas=len(resultados), validas=validas, detalle=resultados)


# ---------- Consultas para la web ----------

def ultimo_valor(c, nodo, variable):
    f = c.execute('SELECT valor, t FROM lecturas WHERE nodo=? AND variable=? ORDER BY t DESC, id DESC LIMIT 1',
                  (nodo, variable)).fetchone()
    return (f['valor'], f['t']) if f else (None, None)


@app.get('/api/resumen')
def api_resumen():
    c = bd()
    ahora = time.time()
    nodos = []
    for nombre, sensor in (('N1', 'BME680'), ('N2', 'SCD41'), ('N3', 'Camara PYNQ')):
        f = c.execute('SELECT MAX(t_srv) t FROM tramas WHERE nodo=? AND valida=1', (nombre,)).fetchone()
        visto = f['t']
        filas = c.execute('SELECT variable, valor FROM lecturas WHERE id IN '
                          '(SELECT MAX(id) FROM lecturas WHERE nodo=? GROUP BY variable)', (nombre,)).fetchall()
        nodos.append({'nodo': nombre, 'sensor': sensor, 'visto_hace_s': round(ahora - visto) if visto else None,
                      'en_linea': bool(visto and ahora - visto < 3 * config.PERIODO_S),
                      'valores': {x['variable']: x['valor'] for x in filas}})
    nivel, t_nivel = ultimo_valor(c, 'N3', 'nivel_cm')
    conf, _ = ultimo_valor(c, 'N3', 'confianza')
    tot = c.execute('SELECT COUNT(*) total, SUM(valida) validas, SUM(error=\'CRC\') crc,'
                    ' SUM(corregidos>0) corregidas, SUM(duplicada) duplicadas FROM tramas').fetchone()
    return jsonify(
        rio=leer_estado(c, 'rio', 'NORMAL'), nivel_cm=nivel, confianza=conf,
        nivel_hace_s=round(ahora - t_nivel) if t_nivel else None,
        umbrales={'vigilancia': config.NIVEL_VIGILANCIA, 'alerta': config.NIVEL_ALERTA},
        nodos=nodos, tramas={k: tot[k] or 0 for k in tot.keys()},
        cifrado=config.CIFRADO, hamming=config.USAR_HAMMING)


@app.get('/api/serie')
def api_serie():
    nodo = request.args.get('nodo', 'N3')
    variable = request.args.get('var', 'nivel_cm')
    horas = min(float(request.args.get('horas', 6)), 24 * 30)
    filas = bd().execute('SELECT t, valor FROM lecturas WHERE nodo=? AND variable=? AND t>=? ORDER BY t',
                         (nodo, variable, time.time() - horas * 3600)).fetchall()
    paso = max(1, len(filas) // 500)              # no mandar mas de ~500 puntos al navegador
    return jsonify([[round(f['t'] * 1000), f['valor']] for f in filas[::paso]])


@app.get('/api/enlace')
def api_enlace():
    c = bd()
    salida = {}
    for nodo in ('N1', 'N2', 'N3'):
        filas = c.execute('SELECT seq, rssi, ruido, ts_nodo, t_srv, bytes_payload FROM tramas'
                          ' WHERE nodo=? AND valida=1 AND duplicada=0 ORDER BY id DESC LIMIT 500',
                          (nodo,)).fetchall()
        salida[nodo] = enlace.calidad([dict(f) for f in reversed(filas)])
    return jsonify(salida)


@app.get('/api/capacidad')
def api_capacidad():
    """Teoria de capacidad + carga real de la ultima hora (tramas enviadas = huecos de seq incluidos)."""
    c = bd()
    desde = time.time() - 3600
    enviadas, nodos, pers, largos = 0, 0, {}, []
    for nodo in ('N1', 'N2', 'N3'):
        filas = c.execute('SELECT seq, t_srv, length(hex) / 2 AS b FROM tramas WHERE nodo=? AND valida=1'
                          ' AND duplicada=0 AND t_srv>=? ORDER BY id', (nodo, desde)).fetchall()
        if len(filas) < 2:
            continue
        s = enlace.seq_ordenadas([f['seq'] for f in filas])
        esperadas = max(s) - min(s) + 1
        minutos = (filas[-1]['t_srv'] - filas[0]['t_srv']) / 60
        if minutos <= 0:
            continue
        enviadas += esperadas / minutos
        nodos += 1
        pers[nodo] = round(100 * (1 - len(set(s)) / esperadas), 2)
        largos += [f['b'] for f in filas]
    medido = {'tramas_min': round(enviadas, 2), 'nodos': nodos, 'per_pct': pers,
              'bytes_medio': round(sum(largos) / len(largos), 1) if largos else None}
    return jsonify(capacidad.resumen(medido))


@app.get('/api/tramas')
def api_tramas():
    limite = min(int(request.args.get('limite', 100)), 500)
    filas = bd().execute('SELECT * FROM tramas ORDER BY id DESC LIMIT ?', (limite,)).fetchall()
    return jsonify([dict(f) for f in filas])


@app.get('/api/alertas')
def api_alertas():
    filas = bd().execute('SELECT * FROM alertas ORDER BY id DESC LIMIT 200').fetchall()
    return jsonify([dict(f) for f in filas])


# ---------- Paginas ----------

PAGINAS = {'/': 'resumen.html', '/nodos': 'nodos.html', '/enlace': 'enlace.html',
           '/capacidad': 'capacidad.html', '/alertas': 'alertas.html', '/tramas': 'tramas.html'}

for ruta, plantilla in PAGINAS.items():
    app.add_url_rule(ruta, plantilla.split('.')[0],
                     (lambda p: lambda: render_template(p, pagina=p.split('.')[0]))(plantilla))


crear_bd()

if __name__ == '__main__':
    from waitress import serve
    print('Central SEI en http://127.0.0.1:%d' % config.PUERTO, flush=True)
    serve(app, host='127.0.0.1', port=config.PUERTO, threads=8)
