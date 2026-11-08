# Calidad de enlace por nodo, con los estimadores de la ppt "Red de Sensores Inalambricos":
#  - por hardware: RSSI (lo da el modulo) y SNR = senal recibida - ruido ambiente
#  - por software: WMEWMA (ventanas de tramas esperadas) y Kalman sobre el RSSI (KLE)
#  - metricas de QoS: perdida de paquetes, latencia y throughput
import math
import config


SALTO_REINICIO = 100   # si el seq retrocede mas que esto (sin dar la vuelta), el nodo se reinicio


def seq_ordenadas(seqs):
    """Desenrolla el seq de 16 bits (65535 -> 0) para poder contar huecos.
    Si el nodo se reinicia, su seq vuelve a empezar: se sigue la cuenta donde iba
    para no contar como perdidas las tramas que nunca se enviaron."""
    salida, desplazo, anterior = [], 0, None
    for s in seqs:
        if anterior is not None:
            atras = anterior - s
            if atras > 32768:
                desplazo += 65536
            elif atras > SALTO_REINICIO:
                desplazo = max(salida) + 1 - s
        salida.append(s + desplazo)
        anterior = s
    return salida


def wmewma(seqs):
    """Para cada ventana de W tramas esperadas: PRR = recibidas / W.
    Estimado = alfa * estimado_anterior + (1 - alfa) * PRR_ventana."""
    if not seqs:
        return None, []
    s = sorted(set(seq_ordenadas(seqs)))
    w = config.VENTANA_WMEWMA
    estimado, historia = None, []
    inicio = s[0]
    while inicio + w - 1 <= s[-1]:
        recibidas = sum(1 for x in s if inicio <= x < inicio + w)
        prr = recibidas / w
        estimado = prr if estimado is None else config.ALFA_WMEWMA * estimado + (1 - config.ALFA_WMEWMA) * prr
        historia.append(round(estimado, 3))
        inicio += w
    return estimado, historia


def kalman_rssi(rssis):
    """Filtro de Kalman de una variable: el RSSI real cambia lento (Q) y la medida es ruidosa (R)."""
    x, p = None, 1.0
    historia = []
    for z in rssis:
        if z is None:
            continue
        if x is None:
            x = float(z)
        p = p + config.KALMAN_Q               # prediccion
        k = p / (p + config.KALMAN_R)         # ganancia
        x = x + k * (z - x)                   # correccion con la medida
        p = (1 - k) * p
        historia.append(round(x, 2))
    return x, historia


def prr_desde_snr(snr):
    """Curva PRR vs SNR (forma logistica). El punto medio es el SNR limite de LoRa en SF7;
    la pendiente es supuesta y se calibra con mediciones reales."""
    return 1 / (1 + math.exp(-(snr - config.SNR_LIMITE_DB) / 1.0))


def calidad(filas):
    """filas: tramas validas de UN nodo ordenadas por llegada, con seq, rssi, ruido, ts_nodo, t_srv, bytes_payload."""
    if not filas:
        return None
    seqs = [f['seq'] for f in filas]
    ordenadas = seq_ordenadas(seqs)
    esperadas = max(ordenadas) - min(ordenadas) + 1
    recibidas = len(set(ordenadas))
    per = 1 - recibidas / esperadas

    rssis = [f['rssi'] for f in filas if f['rssi'] is not None]
    ruidos = [f['ruido'] for f in filas if f['ruido'] is not None]
    snrs = [f['rssi'] - f['ruido'] for f in filas if f['rssi'] is not None and f['ruido'] is not None]

    rssi_k, hist_k = kalman_rssi(rssis)
    ruido_medio = sum(ruidos) / len(ruidos) if ruidos else None
    snr_kle = rssi_k - ruido_medio if rssi_k is not None and ruido_medio is not None else None
    est_w, hist_w = wmewma(seqs)

    latencias = [f['t_srv'] - f['ts_nodo'] for f in filas if f['ts_nodo']]
    duracion = filas[-1]['t_srv'] - filas[0]['t_srv']
    bits = 8 * sum(f['bytes_payload'] for f in filas)

    def prom(v):
        return round(sum(v) / len(v), 2) if v else None

    return {
        'recibidas': recibidas,
        'esperadas': esperadas,
        'per_pct': round(100 * per, 2),
        'rssi_medio': prom(rssis),
        'rssi_kalman': round(rssi_k, 2) if rssi_k is not None else None,
        'snr_medio': prom(snrs),
        'snr_kle': round(snr_kle, 2) if snr_kle is not None else None,
        'prr_kle_pct': round(100 * prr_desde_snr(snr_kle), 1) if snr_kle is not None else None,
        'prr_wmewma_pct': round(100 * est_w, 1) if est_w is not None else None,
        'latencia_media_s': prom(latencias),
        'latencia_max_s': round(max(latencias), 2) if latencias else None,
        'throughput_bps': round(bits / duracion, 2) if duracion > 0 else None,
        'hist_rssi': rssis[-120:],
        'hist_rssi_kalman': hist_k[-120:],
        'hist_wmewma': hist_w[-60:],
    }
