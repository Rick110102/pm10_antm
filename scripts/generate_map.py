import requests
import folium
import pandas as pd
import os
import time
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════
CONFIG = {
    "client_id":     "antamina",
    "client_secret": os.environ.get("METEOSIM_SECRET", ""),  # viene del secret de GitHub
    "token_url":     "https://sso.meteosim.com/realms/suite/protocol/openid-connect/token",
    "api_base":      "https://api.meteosim.com",
    "site_id":       "antamina_prediction",
    "topic":         "ai-daily-model",
    "record_code":   "alertdata:ai-daily-model:antamina_predictions:antamina-daily_model-tft:AlertaPM10_diaria:2CRUCES:1771909200",
    "lat":           -9.5602,
    "lng":           -77.0598,
    "buffer_m":      2000,
}

PERU_TZ = timezone(timedelta(hours=-5))

# ══════════════════════════════════════════════════════════
# TOKEN
# ══════════════════════════════════════════════════════════
def get_token():
    r = requests.post(CONFIG["token_url"], data={
        "grant_type":    "client_credentials",
        "client_id":     CONFIG["client_id"],
        "client_secret": CONFIG["client_secret"]
    })
    r.raise_for_status()
    print("[Token] Obtenido ✓")
    return r.json()["access_token"]

# ══════════════════════════════════════════════════════════
# CONSULTAR API
# ══════════════════════════════════════════════════════════
def get_timeserie(token):
    url = (f"{CONFIG['api_base']}/v3/alertdata/{CONFIG['site_id']}"
           f"/topics/{CONFIG['topic']}/records/{CONFIG['record_code']}/timeserie")
    r = requests.get(url, headers={
        "Accept":        "application/json",
        "Authorization": f"Bearer {token}"
    })
    r.raise_for_status()
    print(f"[API] Datos obtenidos ✓")
    return r.json()["items"]

# ══════════════════════════════════════════════════════════
# PROCESAR
# ══════════════════════════════════════════════════════════
def procesar(items):
    now_peru = datetime.now(PERU_TZ).replace(tzinfo=None)
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

    print(f"[Datos] Observados: {len(observados)} | Pronóstico: {len(pronostico)}")
    return observados, pronostico, now_peru

def get_color(val):
    if val > 2:   return "#ef4444", "ALTO",     "🔴"
    if val >= 1:  return "#f97316", "MODERADO", "🟠"
    return             "#22c55e",  "BUENO",    "🟢"

# ══════════════════════════════════════════════════════════
# GENERAR HTML
# ══════════════════════════════════════════════════════════
def generar_html(observados, pronostico, now_peru):
    lat, lng = CONFIG["lat"], CONFIG["lng"]

    # Valor máximo pronóstico
    if pronostico:
        max_item = max(pronostico, key=lambda x: x["value"])
        max_val  = max_item["value"]
        max_time = max_item["time"]
    else:
        max_val  = 0
        max_time = None

    color, categoria, emoji = get_color(max_val)

    # ── Mapa Folium ────────────────────────────────────────
    m = folium.Map(
        location   = [lat, lng],
        zoom_start = 14,
        tiles      = "CartoDB dark_matter"
    )

    # Buffer 2km
    folium.Circle(
        location     = [lat, lng],
        radius       = CONFIG["buffer_m"],
        color        = color,
        fill         = True,
        fill_color   = color,
        fill_opacity = 0.25,
        weight       = 2,
        tooltip      = f"Buffer 2km · PM10 Máx: {max_val:.2f} μg/m³"
    ).add_to(m)

    # Punto central
    folium.CircleMarker(
        location     = [lat, lng],
        radius       = 7,
        color        = "#ffffff",
        fill         = True,
        fill_color   = color,
        fill_opacity = 1,
        weight       = 2,
        popup        = folium.Popup(f"""
            <div style='font-family:monospace;min-width:220px;padding:4px'>
            <b>📍 Dos Cruces</b><br>
            <hr style='margin:4px 0'>
            PM10 Máx Pronóstico: <b>{max_val:.2f} μg/m³</b><br>
            Categoría: <b style='color:{color}'>{emoji} {categoria}</b><br>
            Hora del máximo: <b>{max_time.strftime('%d/%m/%Y %H:%M') if max_time else '—'}</b><br>
            <hr style='margin:4px 0'>
            Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')} (Hora Perú)
            </div>
        """, max_width=260)
    ).add_to(m)

    # Leyenda
    leyenda_html = """
    <div style='
        position: fixed; bottom: 30px; right: 15px;
        background: rgba(10,14,20,0.92);
        border: 1px solid #1e2d3d; border-radius: 8px;
        padding: 12px 16px; font-family: monospace;
        font-size: 12px; color: #c9d8e8; z-index: 9999;
    '>
        <b style='color:#00c8ff;letter-spacing:1px'>PM10 · PRONÓSTICO</b><br><br>
        <span style='color:#22c55e'>●</span> &lt; 1 μg/m³ — Bueno<br>
        <span style='color:#f97316'>●</span> 1–2 μg/m³ — Moderado<br>
        <span style='color:#ef4444'>●</span> &gt; 2 μg/m³ — Alto
    </div>
    """
    m.get_root().html.add_child(folium.Element(leyenda_html))

    # Obtener HTML del mapa
    mapa_html = m._repr_html_()

    # ── Tabla pronóstico ───────────────────────────────────
    if pronostico:
        df = pd.DataFrame(pronostico)
        df["Hora"]         = df["time"].apply(lambda x: x.strftime("%d/%m %H:%M"))
        df["PM10 (μg/m³)"] = df["value"]
        df["Tipo"]         = df.apply(lambda r:
            f"<span style='color:#f59e0b;font-weight:bold'>★ MÁXIMO</span>"
            if r["value"] == max_val else
            "<span style='color:#00c8ff'>Pronóstico</span>", axis=1)
        tabla_html = df[["Hora", "PM10 (μg/m³)", "Tipo"]].to_html(
            index=False, escape=False,
            classes="tabla-datos",
            border=0
        )
    else:
        tabla_html = "<p style='color:#4a6070'>Sin datos de pronóstico disponibles.</p>"

    # ── HTML final completo ────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="refresh" content="3600"/> <!-- auto-recarga cada hora -->
  <title>Monitor PM10 · Dos Cruces · Antamina</title>
  <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --bg:     #0a0e14;
      --panel:  #111820;
      --border: #1e2d3d;
      --accent: #00c8ff;
      --text:   #c9d8e8;
      --muted:  #4a6070;
    }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Barlow', sans-serif;
      min-height: 100vh;
    }}

    /* HEADER */
    header {{
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 14px 28px;
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .logo {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 13px;
      color: var(--accent);
      letter-spacing: 2px;
    }}
    .updated {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 11px;
      color: var(--muted);
      margin-left: auto;
    }}

    /* LAYOUT */
    .container {{
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 0;
      height: calc(100vh - 54px);
    }}

    /* SIDEBAR */
    aside {{
      background: var(--panel);
      border-right: 1px solid var(--border);
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .card {{
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .card-title {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 2px;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    .big-val {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 48px;
      font-weight: 700;
      line-height: 1;
      color: {color};
    }}
    .big-unit {{
      font-size: 13px;
      color: var(--muted);
      margin-top: 4px;
    }}
    .badge {{
      display: inline-block;
      margin-top: 8px;
      padding: 4px 12px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 1px;
      background: {'rgba(239,68,68,.15)' if max_val > 2 else 'rgba(249,115,22,.15)' if max_val >= 1 else 'rgba(34,197,94,.15)'};
      color: {color};
    }}
    .max-time {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 11px;
      color: var(--muted);
      margin-top: 8px;
    }}

    /* Stats */
    .stat-row {{
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }}
    .stat-row:last-child {{ border-bottom: none; }}
    .stat-label {{ color: var(--muted); }}
    .stat-val {{
      font-family: 'Share Tech Mono', monospace;
      color: var(--accent);
    }}

    /* Tabla */
    .tabla-datos {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .tabla-datos th {{
      font-family: 'Share Tech Mono', monospace;
      font-size: 10px;
      color: var(--muted);
      text-align: left;
      padding: 4px 6px;
      border-bottom: 1px solid var(--border);
      letter-spacing: 1px;
    }}
    .tabla-datos td {{
      padding: 5px 6px;
      border-bottom: 1px solid rgba(30,45,61,.5);
      font-family: 'Share Tech Mono', monospace;
    }}

    /* Mapa */
    .map-container {{
      width: 100%;
      height: 100%;
    }}
    .map-container iframe {{
      width: 100%;
      height: 100%;
      border: none;
    }}

    ::-webkit-scrollbar {{ width: 4px; }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
  </style>
</head>
<body>

<header>
  <div class="logo">⬡ ANTAMINA · MONITOR PM10 · DOS CRUCES</div>
  <div class="updated">
    Actualizado: {now_peru.strftime('%d/%m/%Y %H:%M')} (Hora Perú) &nbsp;·&nbsp;
    Próx. actualización en ~1h
  </div>
</header>

<div class="container">

  <!-- SIDEBAR -->
  <aside>

    <div class="card">
      <div class="card-title">PM10 · Máx. Pronóstico</div>
      <div class="big-val">{max_val:.1f}</div>
      <div class="big-unit">μg/m³</div>
      <span class="badge">{emoji} {categoria}</span>
      <div class="max-time">
        {'↑ Hora máximo: ' + max_time.strftime('%d/%m/%Y %H:%M') if max_time else ''}
      </div>
    </div>

    <div class="card">
      <div class="card-title">Resumen</div>
      <div class="stat-row">
        <span class="stat-label">Punto</span>
        <span class="stat-val">Dos Cruces</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Coordenadas</span>
        <span class="stat-val">{lat}, {lng}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Buffer</span>
        <span class="stat-val">2 km</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Obs. hoy</span>
        <span class="stat-val">{len(observados)} registros</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Pronóstico</span>
        <span class="stat-val">{len(pronostico)} registros</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Corte obs/pron</span>
        <span class="stat-val">{now_peru.strftime('%H:%M')}</span>
      </div>
    </div>

    <div class="card" style="flex:1;overflow:hidden;display:flex;flex-direction:column">
      <div class="card-title">Serie de pronóstico</div>
      <div style="overflow-y:auto;flex:1">{tabla_html}</div>
    </div>

  </aside>

  <!-- MAPA -->
  <div class="map-container">
    {mapa_html}
  </div>

</div>
</body>
</html>"""

    return html

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 50)
    print("  PM10 Monitor · Antamina · Dos Cruces")
    print(f"  {datetime.now(PERU_TZ).strftime('%d/%m/%Y %H:%M:%S')} (Hora Perú)")
    print("=" * 50)

    token                        = get_token()
    items                        = get_timeserie(token)
    observados, pronostico, now  = procesar(items)
    html                         = generar_html(observados, pronostico, now)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[✓] index.html generado correctamente")
