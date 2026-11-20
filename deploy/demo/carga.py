"""Prueba de carga: paneles abiertos (como panel.js) + ESP32 enviando + "tormenta" opcional.

Solo rama demo. Contra una COPIA del servidor (otra base, otro puerto), nunca contra el real:

    python carga.py --base http://127.0.0.1:5002 --paneles 80 --esp32 5 --tormenta

- Paneles: /api/panel cada 5 s (30 s tras un 429/503), /api/tuneles cada 10 s y de vez en
  cuando Historial o Estadísticas, igual que backend/static/panel.js.
- ESP32 (con CARGA_CLAVE = clave principal de la copia): reservan secuencias y mandan eventos
  válidos cada 5 s; cada ~30 s un lote de 9, como al vaciar la cola tras reconectar.
- --tormenta: a los 15 s, 20 visitantes piden "Todo el historial" a la vez (caché fría);
  a los 25 s, 15 visitantes descargan la exportación completa a 1,5 MB/s (subida hogareña).
- --solo-lectura: solo paneles (para probar el camino público por Cloudflare sin escribir).
"""
import argparse
import http.client
import json
import os
import random
import ssl
import statistics
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

p = argparse.ArgumentParser()
p.add_argument("--base", default="http://127.0.0.1:5002")
p.add_argument("--paneles", type=int, default=80)
p.add_argument("--esp32", type=int, default=5)
p.add_argument("--duracion", type=int, default=60)
p.add_argument("--rampa", type=float, default=10, help="segundos en que van entrando los paneles")
p.add_argument("--tormenta", action="store_true")
p.add_argument("--solo-lectura", action="store_true")
p.add_argument("--preparar", type=int, default=0, help="crear pasos hasta tunel-NN para los ESP32")
args = p.parse_args()

U = urlsplit(args.base)
CLAVE = os.environ.get("CARGA_CLAVE", "")
K = {"X-API-Key": CLAVE}
PASOS = ["tunel-01", "tunel-02", "tunel-03", "tunel-04"]
DEMO = ["tunel-02", "tunel-03", "tunel-04"]  # los que tienen 84.000 eventos
lock = threading.Lock()
res = defaultdict(list)  # tipo -> [(t_rel, ms, código)]
T0 = time.time()
FIN = T0 + args.duracion


def conectar():
    if U.scheme == "https":
        return http.client.HTTPSConnection(U.hostname, U.port or 443, timeout=40,
                                           context=ssl.create_default_context())
    return http.client.HTTPConnection(U.hostname, U.port or 80, timeout=40)


class Cliente:
    """Una conexión persistente por visitante o dispositivo, como un navegador."""

    def __init__(self):
        self.c = None

    def pedir(self, tipo, metodo, ruta, cuerpo=None, headers=None, bytes_s=None):
        h = {"Accept": "application/json", "User-Agent": "alertar-carga", **(headers or {})}
        if cuerpo is not None:
            cuerpo = json.dumps(cuerpo).encode()
            h["Content-Type"] = "application/json"
        t0 = time.perf_counter()
        codigo, datos, espera = "error", b"", None
        for intento in (0, 1):  # un reintento si la conexión persistente se había cerrado
            try:
                if self.c is None:
                    self.c = conectar()
                self.c.request(metodo, ruta, body=cuerpo, headers=h)
                r = self.c.getresponse()
                if bytes_s:  # descarga a ritmo limitado: el hilo del servidor queda ocupado
                    total = 0
                    while chunk := r.read(64 * 1024):
                        total += len(chunk)
                        atraso = total / bytes_s - (time.perf_counter() - t0)
                        if atraso > 0:
                            time.sleep(atraso)
                else:
                    datos = r.read()
                codigo, espera = r.status, r.getheader("Retry-After")
                if (r.getheader("Connection") or "").lower() == "close":
                    self.c.close()
                    self.c = None
                break
            except (http.client.HTTPException, OSError) as e:
                if self.c:
                    self.c.close()
                self.c = None
                codigo = type(e).__name__
        with lock:
            res[tipo].append((time.time() - T0, (time.perf_counter() - t0) * 1000, codigo))
        return codigo, datos, espera


def dormir_hasta(t):
    while (falta := t - time.time()) > 0:
        time.sleep(min(falta, 1))


def panel(i):
    time.sleep(random.uniform(0, args.rampa))
    cl, paso = Cliente(), random.choice(PASOS)
    cl.pedir("tuneles", "GET", "/api/tuneles")
    prox_sitios = time.time() + 10
    while time.time() < FIN:
        codigo, _, _ = cl.pedir("panel", "GET", f"/api/panel/{paso}")
        hasta = time.time() + (30 if codigo in (429, 503) else 5)
        while time.time() < min(hasta, FIN):
            if time.time() >= prox_sitios:
                cl.pedir("tuneles", "GET", "/api/tuneles")
                prox_sitios += 10
            if random.random() < 0.01:
                cl.pedir("historial", "GET", f"/api/pasos/{paso}/historial?limite=50&offset=0")
            if random.random() < 0.01:
                rango = random.choice(["1h", "6h", "24h", "7d"])
                cl.pedir("estadisticas", "GET", f"/api/pasos/{paso}/estadisticas?rango={rango}")
            time.sleep(min(1, max(0.0, hasta - time.time())))


def stats_todo(i):
    """Como loadStats(): ante 429 espera Retry-After y reintenta hasta 4 veces."""
    dormir_hasta(T0 + 15)
    cl, paso = Cliente(), random.choice(DEMO)
    t0 = time.perf_counter()
    for intento in range(5):
        codigo, _, espera = cl.pedir("stats_todo_pedido", "GET", f"/api/pasos/{paso}/estadisticas?rango=all")
        if codigo != 429 or intento == 4:
            break
        time.sleep(float(espera or 2))
    with lock:  # lo que ve la persona: desde que tocó el botón hasta tener el gráfico (o error)
        res["stats_todo_visto"].append((time.time() - T0, (time.perf_counter() - t0) * 1000, codigo))


def exportar(i):
    dormir_hasta(T0 + 25 + random.uniform(0, 2))
    cl, paso = Cliente(), random.choice(DEMO)
    for intento in range(2):  # ante 429 la persona vuelve a tocar "Descargar" una vez
        codigo, _, espera = cl.pedir("exportar", "GET", f"/api/pasos/{paso}/exportar?formato=csv", bytes_s=1.5e6)
        if codigo != 429:
            break
        time.sleep(float(espera or 5))


def evento(dev, paso, arranque, seq):
    return {"version": 1, "evento_id": f"carga-{arranque[:8]}-{seq}", "dispositivo_id": dev, "paso_id": paso,
            "arranque_id": arranque, "secuencia": seq, "uptime_ms": seq % 10**9,
            "medido_en": datetime.now(timezone.utc).isoformat(), "codigo": "OK-001",
            "diagnostico": "Prueba de carga", "obstruccion_carril1_cm": 0.0, "obstruccion_carril2_cm": 0.0,
            "sensor1_valido": True, "sensor2_valido": True, "agua_activa": False, "agua_pendiente": False}


def esp32(n, dispositivos):
    paso, dev = dispositivos[n]
    cl = Cliente()
    codigo, datos, _ = cl.pedir("reserva", "POST", f"/api/dispositivos/{dev}/reserva",
                                {"instalacion_id": uuid.uuid4().hex}, headers=K)
    if codigo not in (200, 201):
        print(f"{dev}: reserva {codigo} {datos[:120]!r}")
        return
    seq, arranque = json.loads(datos)["base"], uuid.uuid4().hex
    time.sleep(random.uniform(0, 5))
    ciclo = 0
    while time.time() < FIN:
        ciclo += 1
        lote = 9 if ciclo % 6 == 0 else 1
        eventos = [evento(dev, paso, arranque, seq + k) for k in range(lote)]
        seq += lote
        if lote == 1:
            cl.pedir("ingesta", "POST", "/api/eventos", eventos[0], headers=K)
        else:
            cl.pedir("ingesta_lote9", "POST", "/api/eventos/lote", {"eventos": eventos}, headers=K)
        time.sleep(5)


def preparar(hasta):
    cl = Cliente()
    for n in range(5, hasta + 1):
        codigo, datos, _ = cl.pedir("admin", "POST", "/api/tuneles", headers=K, cuerpo={
            "paso_id": f"tunel-{n:02d}", "dispositivo_id": f"esp32-{n:02d}", "nombre": f"Carga {n:02d}",
            "ubicacion": "Prueba de carga", "latitud": -34.6 + n / 1000, "longitud": -58.4})
        print(f"tunel-{n:02d}: {codigo}")


def pct(v, q):
    return v[min(len(v) - 1, int(len(v) * q))]


def informe():
    esp = "" if args.solo_lectura else f" + {args.esp32} ESP32"
    print(f"\n{args.paneles} paneles{esp} durante {args.duracion} s"
          f"{' + tormenta (20× Todo el historial a los 15 s, 15 exportaciones a los 25 s)' if args.tormenta else ''}")
    print(f"{'tipo':18} {'n':>5} {'mediana':>9} {'p95':>9} {'máx':>9}  códigos")
    for tipo in ("panel", "tuneles", "historial", "estadisticas", "ingesta", "ingesta_lote9", "reserva",
                 "stats_todo_pedido", "stats_todo_visto", "exportar"):
        filas = res.get(tipo)
        if not filas:
            continue
        ms = sorted(f[1] for f in filas)
        codigos = dict(Counter(str(f[2]) for f in filas))
        print(f"{tipo:18} {len(ms):5} {statistics.median(ms):8.0f}ms {pct(ms, .95):8.0f}ms {ms[-1]:8.0f}ms  {codigos}")
    if args.tormenta:
        print("\nPeor demora por tramo de 5 s (panel / ESP32), para ver el efecto de la tormenta:")
        for t in range(0, args.duracion, 5):
            fila = []
            for tipo in ("panel", "ingesta", "ingesta_lote9"):
                v = [f[1] for f in res.get(tipo, []) if t <= f[0] < t + 5]
                malos = sum(1 for f in res.get(tipo, []) if t <= f[0] < t + 5 and f[2] not in (200, 201))
                fila.append(f"{tipo} {max(v) if v else 0:6.0f}ms{f' ({malos} fallidos)' if malos else ''}")
            print(f"  {t:3}-{t + 5:<3}s  " + "   ".join(fila))


if args.preparar:
    preparar(args.preparar)
    raise SystemExit
hilos = [threading.Thread(target=panel, args=(i,), daemon=True) for i in range(args.paneles)]
if not args.solo_lectura:
    dispositivos = [(f"tunel-{n:02d}", f"esp32-{n:02d}") for n in range(1, args.esp32 + 1)]
    hilos += [threading.Thread(target=esp32, args=(n, dispositivos), daemon=True) for n in range(args.esp32)]
    if args.tormenta:
        hilos += [threading.Thread(target=stats_todo, args=(i,), daemon=True) for i in range(20)]
        hilos += [threading.Thread(target=exportar, args=(i,), daemon=True) for i in range(15)]
for h in hilos:
    h.start()
for h in hilos:
    h.join(timeout=max(1, FIN + 90 - time.time()))
informe()
