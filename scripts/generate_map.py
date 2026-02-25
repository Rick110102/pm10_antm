import requests
import folium
import pandas as pd
import os
import time
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════
CLIENT_ID     = "antamina"
CLIENT_SECRET = os.environ.get("METEOSIM_SECRET", "")
TOKEN_URL     = "https://sso.meteosim.com/realms/suite/protocol/openid-connect/token"
API_BASE      = "https://api.meteosim.com"
SITE_ID       = "antamina_prediction"
TOPIC         = "ai-daily-model"

PERU_TZ = timezone(timedelta(hours=-5))

ESTACIONES = [
    {
        "nombre":      "Dos Cruces",
        "record_code": "alertdata:ai-daily-model:antamina_predictions:antamina-daily_model-tft:AlertaPM10_diaria:2CRUCES:1771909200",
        "lat":         -9.56023,
        "lng":         -77.05986,
        "buffer_m":    2000,
    },
    {
        "nombre":      "Quebrada",
        "record_code": "alertdata:ai-daily-model:antamina_predictions:antamina-daily_model-tft:AlertaPM10_diaria:QUEBRADA:1771909200",
        "lat":         -9.55501,
        "lng":         -77.08584,
        "buffer_m":    1000,
    },
    {
        "nombre":      "Tucush",
        "record_code": "alertdata:ai-daily-model:antamina_predictions:antamina-daily_model-tft:AlertaPM10_diaria:TUCUSH:1771909200",
        "lat":         -9.51011,
        "lng":         -77.05715,
        "buffer_m":    2000,
    },
    {
        "nombre":      "Usupallares",
        "record_code": "alertdata:ai-daily-model:antamina_predictions:antamina-daily_model-tft:AlertaPM10_diaria:USUPALLARES:1771909200",
        "lat":         -9.55422,
        "lng":         -77.07305,
        "buffer_m":    2000,
    },
]

def get_token():
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    r.raise_for_status()
    print("[Token] Obtenido ✓")
    return r.json()["access_token"]

def get_timeserie(token, record_code):
    url = (f"{API_BASE}/v3/alertdata/{SITE_ID}"
           f"/topics/{TOPIC}/records/{record_code}/timeserie")
    r = requests.get(url, headers={
        "Accept":        "application/json",
        "Authorization": f"Bearer {token}"
    })
    r.raise_for_status()
    return r.json()["items"]

def procesar(items, now_peru):
    observados = []
    pronostico = []
    for item in items:
        t = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
        t = t.astimezone(PERU_TZ).replace(tzinfo=None)
        val = next((v["value"] for v in item.get("values", [])
                    if v["variableId"] == "PM10"), None)
        if val is None:
            continue
        row = {"time": t, "value": round(val, 4)}
        if t <= now_peru:
            observados.append(row)
        else:
            pronostico.append(row)
    return observados, pronostico

def get_color(val):
    if val > 2:   return "#ef4444", "ALTO",     "🔴"
    if val >= 1:  return "#f97316", "MODERADO", "🟠"
    return             "#22c55e",  "BUENO",    "🟢"

def generar_mapa(resultados, now_peru):
    lat_c = sum(e["lat"] for e in ESTACIONES) / len(ESTACIONES)
    lng_c = sum(e["lng"] for e in ESTACIONES) / len(ESTACIONES)

    m = folium.Map(location=[lat_c, lng_c], zoom_start=13, tiles="CartoDB dark_matter")

    for est in resultados:
        lat      = est["lat"]
        lng      = est["lng"]
        max_val  = est["max_val"]
        max_time = est["max_time"]
        color, categoria, emoji = get_color(max_val)
        buffer_m  = est["buffer_m"]
        buffer_km = buffer_m / 1000

        folium.Circle(
            location=[lat, lng], radius=buffer_m,
            color=color, fill=True, fill_color=color,
            fill_opacity=0.2, weight=2,
            tooltip=f"{est['nombre']} · PM10 Máx: {max_val:.2f} μg/m³ · Buffer {buffer_km:.0f}km"
        ).add_to(m)

        folium.CircleMarker(
            location=[lat, lng], radius=7,
            color="#ffffff", fill=True, fill_color=color,
            fill_opacity=1, weight=2,
            popup=folium.Popup(f"""
                <div style='font-family:monospace;min-width:220px;padding:4px'>
                <b>📍 {est['nombre']}</b><br>
                <hr style='margin:4px 0'>
                PM10 Máx Pronóstico: <b>{max_val:.2f} μg/m³</b><br>
                Categoría: <b style='color:{color}'>{emoji} {categoria}</b><br>
                Hora del máximo: <b>{max_time.strftime('%d/%m/%Y %H:%M') if max_time else '—'}</b><br>
                Buffer: <b>{buffer_km:.0f} km</b><br>
                <hr style='margin:4px 0'>
                Obs: {est['n_obs']} | Pron: {est['n_pron']}<br>
                Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')} (Perú)
                </div>
            """, max_width=260)
        ).add_to(m)

        folium.Marker(
            location=[lat + 0.003, lng],
            icon=folium.DivIcon(html=f"""
                <div style='font-family:monospace;background:rgba(0,0,0,0.75);
                color:{color};border:1px solid {color};border-radius:4px;
                padding:2px 7px;font-size:11px;white-space:nowrap;font-weight:bold;'>
                    {est['nombre']} · {max_val:.1f} μg/m³
                </div>
            """)
        ).add_to(m)

    leyenda_html = """
    <div style='position:fixed;bottom:30px;right:15px;
        background:rgba(10,14,20,0.92);border:1px solid #1e2d3d;border-radius:8px;
        padding:12px 16px;font-family:monospace;font-size:12px;color:#c9d8e8;z-index:9999;'>
        <b style='color:#00c8ff;letter-spacing:1px'>PM10 · PRONÓSTICO</b><br><br>
        <span style='color:#22c55e'>●</span> &lt; 1 μg/m³ — Bueno<br>
        <span style='color:#f97316'>●</span> 1–2 μg/m³ — Moderado<br>
        <span style='color:#ef4444'>●</span> &gt; 2 μg/m³ — Alto<br><br>
        <span style='color:#4a6070;font-size:10px'>Buffer 2km: Dos Cruces, Tucush, Usupallares<br>Buffer 1km: Quebrada</span>
    </div>"""
    m.get_root().html.add_child(folium.Element(leyenda_html))
    return m._repr_html_()

def tabla_resumen(resultados):
    filas = ""
    for est in resultados:
        color, categoria, emoji = get_color(est["max_val"])
        filas += f"""<tr>
            <td>{est['nombre']}</td>
            <td style='color:{color};font-weight:bold'>{est['max_val']:.2f}</td>
            <td><span style='color:{color}'>{emoji} {categoria}</span></td>
            <td style='color:#4a6070'>{est['max_time'].strftime('%H:%M') if est['max_time'] else '—'}</td>
            <td style='color:#4a6070'>{est['buffer_m']//1000} km</td>
            <td style='color:#00c8ff'>{est['n_obs']}</td>
            <td style='color:#00c8ff'>{est['n_pron']}</td>
        </tr>"""
    return f"""<table class='tabla-datos'>
        <thead><tr>
            <th>Estación</th><th>PM10 Máx (μg/m³)</th><th>Categoría</th>
            <th>Hora Máx</th><th>Buffer</th><th>Obs.</th><th>Pron.</th>
        </tr></thead>
        <tbody>{filas}</tbody>
    </table>"""

def generar_html(resultados, mapa_html, now_peru):
    resumen_tabla = tabla_resumen(resultados)
    cards_html = ""
    for est in resultados:
        color, categoria, emoji = get_color(est["max_val"])
        bg = ('rgba(239,68,68,.15)' if est["max_val"] > 2
              else 'rgba(249,115,22,.15)' if est["max_val"] >= 1
              else 'rgba(34,197,94,.15)')
        cards_html += f"""
        <div class="card">
            <div class="card-title">📍 {est['nombre']} · {est['buffer_m']//1000}km</div>
            <div class="big-val" style="color:{color}">{est['max_val']:.2f}</div>
            <div class="big-unit">μg/m³</div>
            <span class="badge" style="background:{bg};color:{color}">{emoji} {categoria}</span>
            <div class="max-time">
                {('Máx: ' + est['max_time'].strftime('%H:%M')) if est['max_time'] else ''}
                &nbsp;·&nbsp; Pron: {est['n_pron']} reg.
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="refresh" content="3600"/>
  <title>Monitor PM10 · Antamina</title>
  <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600&display=swap" rel="stylesheet"/>
  <style>
    :root {{ --bg:#0a0e14; --panel:#111820; --border:#1e2d3d; --accent:#00c8ff; --text:#c9d8e8; --muted:#4a6070; }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:var(--bg); color:var(--text); font-family:'Barlow',sans-serif;
            height:100vh; display:grid; grid-template-rows:54px 1fr;
            grid-template-columns:300px 1fr; overflow:hidden; }}
    header {{ grid-column:1/-1; background:var(--panel); border-bottom:1px solid var(--border);
              padding:0 24px; display:flex; align-items:center; gap:16px; }}
    .logo {{ font-family:'Share Tech Mono',monospace; font-size:12px; color:var(--accent); letter-spacing:2px; }}
    .updated {{ font-family:'Share Tech Mono',monospace; font-size:11px; color:var(--muted); margin-left:auto; }}
    aside {{ background:var(--panel); border-right:1px solid var(--border);
             padding:16px; overflow-y:auto; display:flex; flex-direction:column; gap:12px; }}
    .card {{ background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:14px; }}
    .card-title {{ font-family:'Share Tech Mono',monospace; font-size:10px; color:var(--muted);
                   letter-spacing:1px; text-transform:uppercase; margin-bottom:8px; }}
    .big-val {{ font-family:'Share Tech Mono',monospace; font-size:32px; font-weight:700; line-height:1; }}
    .big-unit {{ font-size:12px; color:var(--muted); margin-top:3px; }}
    .badge {{ display:inline-block; margin-top:6px; padding:3px 10px; border-radius:4px;
              font-size:11px; font-weight:600; letter-spacing:1px; }}
    .max-time {{ font-family:'Share Tech Mono',monospace; font-size:10px; color:var(--muted); margin-top:6px; }}
    .map-wrap {{ width:100%; height:100%; overflow:hidden; }}
    .map-wrap iframe {{ width:100%; height:100%; border:none; }}
    .tabla-datos {{ width:100%; border-collapse:collapse; font-size:12px; }}
    .tabla-datos th {{ font-family:'Share Tech Mono',monospace; font-size:10px; color:var(--muted);
                       text-align:left; padding:4px 8px; border-bottom:1px solid var(--border); letter-spacing:1px; }}
    .tabla-datos td {{ padding:5px 8px; border-bottom:1px solid rgba(30,45,61,.5);
                       font-family:'Share Tech Mono',monospace; }}
    ::-webkit-scrollbar {{ width:4px; }}
    ::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:2px; }}
  </style>
</head>
<body>
<header>
  <div class="logo">⬡ ANTAMINA · MONITOR PM10 · 4 ESTACIONES</div>
  <div class="updated">Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')} (Hora Perú) &nbsp;·&nbsp; Próx. ~1h</div>
</header>
<aside>{cards_html}</aside>
<div style="display:flex;flex-direction:column;overflow:hidden">
  <div style="background:var(--panel);border-bottom:1px solid var(--border);padding:12px 16px;overflow-x:auto">
    {resumen_tabla}
  </div>
  <div class="map-wrap" style="flex:1">{mapa_html}</div>
</div>
</body>
</html>"""

if __name__ == "__main__":
    now_peru = datetime.now(PERU_TZ).replace(tzinfo=None)
    print("=" * 55)
    print("  PM10 Monitor · Antamina · 4 Estaciones")
    print(f"  {now_peru.strftime('%d/%m/%Y %H:%M:%S')} (Hora Perú)")
    print("=" * 55)

    token      = get_token()
    resultados = []

    for est in ESTACIONES:
        print(f"\n[{est['nombre']}] Consultando...")
        try:
            items            = get_timeserie(token, est["record_code"])
            observados, pron = procesar(items, now_peru)
            max_item         = max(pron, key=lambda x: x["value"]) if pron else None
            max_val          = max_item["value"] if max_item else 0
            max_time         = max_item["time"]  if max_item else None
            _, categoria, emoji = get_color(max_val)
            print(f"  PM10 Máx: {max_val:.2f} μg/m³ {emoji} {categoria}")
            resultados.append({
                "nombre":   est["nombre"],
                "lat":      est["lat"],
                "lng":      est["lng"],
                "buffer_m": est["buffer_m"],
                "max_val":  max_val,
                "max_time": max_time,
                "n_obs":    len(observados),
                "n_pron":   len(pron),
            })
        except Exception as e:
            print(f"  ❌ Error: {e}")
            resultados.append({
                "nombre":   est["nombre"],
                "lat":      est["lat"],
                "lng":      est["lng"],
                "buffer_m": est["buffer_m"],
                "max_val":  0,
                "max_time": None,
                "n_obs":    0,
                "n_pron":   0,
            })

    mapa_html = generar_mapa(resultados, now_peru)
    html      = generar_html(resultados, mapa_html, now_peru)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[✓] index.html generado con {len(resultados)} estaciones")
