import requests
import folium
import json
import os
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
PERU_TZ       = timezone(timedelta(hours=-5))

ESTACIONES = [
    {
        "nombre":        "Dos Cruces",
        "location_code": "2CRUCES",
        "lat": -9.56023, "lng": -77.05986, "buffer_m": 2000,
    },
    {
        "nombre":        "Quebrada",
        "location_code": "QUEBRADA",
        "lat": -9.55501, "lng": -77.08584, "buffer_m": 1000,
    },
    {
        "nombre":        "Tucush",
        "location_code": "TUCUSH",
        "lat": -9.51011, "lng": -77.05715, "buffer_m": 2000,
    },
    {
        "nombre":        "Usupallares",
        "location_code": "USUPALLARES",
        "lat": -9.55422, "lng": -77.07305, "buffer_m": 2000,
    },
]

# ══════════════════════════════════════════════════════════
# TOKEN
# ══════════════════════════════════════════════════════════
def get_token():
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    r.raise_for_status()
    print("[Token] Obtenido ✓")
    return r.json()["access_token"]

# ══════════════════════════════════════════════════════════
# CALCULAR RECORD CODE DEL DÍA
# ══════════════════════════════════════════════════════════
def get_record_code(location_code):
    """
    Construye el record_code del día actual calculando el timestamp
    Unix del inicio del día en hora Perú (00:00 PE → UTC).
    Ej: 25/02/2026 00:00 PE → 1771995600
    """
    now_peru   = datetime.now(PERU_TZ)
    inicio_dia = now_peru.replace(hour=0, minute=0, second=0, microsecond=0)
    timestamp  = int(inicio_dia.astimezone(timezone.utc).timestamp())
    code = (
        f"alertdata:ai-daily-model:antamina_predictions:"
        f"antamina-daily_model-tft:AlertaPM10_diaria:"
        f"{location_code}:{timestamp}"
    )
    print(f"  Record code: {code}")
    return code

# ══════════════════════════════════════════════════════════
# CONSULTAR SERIE TEMPORAL
# ══════════════════════════════════════════════════════════
def get_timeserie(token, record_code):
    url = f"{API_BASE}/v3/alertdata/{SITE_ID}/topics/{TOPIC}/records/{record_code}/timeserie"
    r = requests.get(url, headers={
        "Accept":        "application/json",
        "Authorization": f"Bearer {token}"
    })
    r.raise_for_status()
    return r.json()["items"]

# ══════════════════════════════════════════════════════════
# PROCESAR
# ══════════════════════════════════════════════════════════
def procesar(items, corte_dt):
    observados, pronostico = [], []
    for item in items:
        t = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
        t = t.astimezone(PERU_TZ).replace(tzinfo=None)
        val = next((v["value"] for v in item.get("values", [])
                    if v["variableId"] == "PM10"), None)
        if val is None:
            continue
        row = {"time": t, "value": round(val, 4)}
        (observados if t <= corte_dt else pronostico).append(row)
    observados.sort(key=lambda x: x["time"])
    pronostico.sort(key=lambda x: x["time"])
    return observados, pronostico

def get_color(val):
    if val > 100: return "#ef4444", "MUY ALTO",  "🔴"
    if val > 50:  return "#f97316", "ALTO",       "🟠"
    if val > 20:  return "#eab308", "MODERADO",   "🟡"
    return             "#22c55e",  "BAJO",        "🟢"

# ══════════════════════════════════════════════════════════
# MAPA FOLIUM
# ══════════════════════════════════════════════════════════
def generar_mapa(resultados):
    lat_c = sum(e["lat"] for e in ESTACIONES) / len(ESTACIONES)
    lng_c = sum(e["lng"] for e in ESTACIONES) / len(ESTACIONES)
    m = folium.Map(
        location=[lat_c, lng_c],
        zoom_start=13,
        tiles="CartoDB dark_matter",
        zoom_control=True
    )

    for est in resultados:
        color, categoria, emoji = get_color(est["max_val"])
        km = est["buffer_m"] / 1000

        folium.Circle(
            location=[est["lat"], est["lng"]],
            radius=est["buffer_m"],
            color=color, fill=True, fill_color=color,
            fill_opacity=0.22, weight=2,
            tooltip=f"{est['nombre']} · {est['max_val']:.2f} μg/m³ · {emoji} {categoria}"
        ).add_to(m)

        folium.CircleMarker(
            location=[est["lat"], est["lng"]],
            radius=6,
            color="#ffffff", fill=True, fill_color=color,
            fill_opacity=1, weight=2,
            popup=folium.Popup(f"""
                <div style='font-family:monospace;min-width:190px;padding:4px'>
                <b>📍 {est['nombre']}</b>
                <hr style='margin:4px 0'>
                PM10 Máx: <b>{est['max_val']:.2f} μg/m³</b><br>
                Categoría: <b style='color:{color}'>{emoji} {categoria}</b><br>
                Hora máx: <b>{est['max_time'].strftime('%H:%M') if est['max_time'] else '—'}</b><br>
                Buffer: <b>{km:.0f} km</b>
                </div>""", max_width=220),
            tooltip=f"{est['nombre']} · {est['max_val']:.2f} μg/m³"
        ).add_to(m)

    return m.get_root().render()

# ══════════════════════════════════════════════════════════
# CHART DATA
# ══════════════════════════════════════════════════════════
def preparar_chart_data(resultados):
    eje_x = [f"{h:02d}:00" for h in range(24)]
    charts = []
    for est in resultados:
        color, _, _ = get_color(est["max_val"])
        obs  = [{"x": r["time"].strftime("%H:%M"), "y": r["value"]} for r in est["observados"]]
        pron = [{"x": r["time"].strftime("%H:%M"), "y": r["value"]} for r in est["pronostico"]]
        pron_continuo = ([obs[-1]] + pron) if obs and pron else pron
        charts.append({
            "nombre":   est["nombre"],
            "color":    color,
            "obs":      obs,
            "pron":     pron_continuo,
            "max_val":  est["max_val"],
            "max_time": est["max_time"].strftime("%H:%M") if est["max_time"] else None,
            "eje_x":    eje_x,
        })
    return json.dumps(charts, ensure_ascii=False)

# ══════════════════════════════════════════════════════════
# HTML FINAL
# ══════════════════════════════════════════════════════════
def generar_html(resultados, mapa_render, now_peru, hora_corte):
    chart_data = preparar_chart_data(resultados)
    fecha_act  = now_peru.strftime("%d/%m/%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="refresh" content="3600"/>
  <title>Monitor PM10 · Antamina</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;400;600&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --bg:     #0a0e14;
      --panel:  #111820;
      --border: #1e2d3d;
      --accent: #00c8ff;
      --text:   #c9d8e8;
      --muted:  #4a6070;
      --legend: #0d1520;
    }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    html, body {{
      height:100%; background:var(--bg);
      color:var(--text); font-family:'Barlow',sans-serif;
      overflow:hidden;
    }}
    header {{
      height:48px; flex-shrink:0;
      background:var(--panel);
      border-bottom:1px solid var(--border);
      padding:0 20px;
      display:flex; align-items:center; gap:16px;
    }}
    .logo {{
      font-family:'Share Tech Mono',monospace;
      font-size:12px; color:var(--accent); letter-spacing:2px;
    }}
    .hdr-right {{
      margin-left:auto;
      font-family:'Share Tech Mono',monospace;
      font-size:11px; color:var(--muted);
      display:flex; gap:20px;
    }}
    .hdr-right span {{ color:var(--accent); }}
    .body {{
      display:grid;
      grid-template-columns: 40% 60%;
      grid-template-rows: calc(100vh - 84px) 36px;
      height:calc(100vh - 48px);
    }}
    .charts-panel {{
      grid-column:1; grid-row:1;
      display:flex; flex-direction:column;
      overflow:hidden;
      border-right:1px solid var(--border);
      background:var(--bg);
    }}
    .charts-scroll {{
      flex:1; overflow-y:auto;
      padding:8px 10px;
      display:flex; flex-direction:column; gap:6px;
    }}
    .chart-block {{ flex-shrink:0; }}
    .chart-label {{
      font-family:'Share Tech Mono',monospace;
      font-size:9px; color:var(--accent);
      letter-spacing:1px; margin-bottom:2px;
      padding-left:2px;
    }}
    .plotly-div {{ width:100%; height:140px; }}
    .map-panel {{
      grid-column:2; grid-row:1;
      overflow:hidden; position:relative;
    }}
    .map-panel .folium-map {{
      width:100% !important;
      height:100% !important;
    }}
    .legend-charts {{
      grid-column:1; grid-row:2;
      background:var(--legend);
      border-top:1px solid var(--border);
      border-right:1px solid var(--border);
      display:flex; align-items:center;
      justify-content:center;
      padding:0 10px; gap:16px;
      font-family:'Share Tech Mono',monospace;
      font-size:9px; color:var(--muted);
    }}
    .li {{ display:flex; align-items:center; gap:5px; }}
    .line-solid {{ width:20px; height:2px; background:#94a3b8; }}
    .line-pron  {{ width:20px; height:2px; background:#00c8ff; }}
    .line-corte {{ width:2px; height:12px; background:#f59e0b; }}
    .dot-max    {{ width:8px; height:8px; border-radius:50%; background:#ef4444; }}
    .legend-map {{
      grid-column:2; grid-row:2;
      background:var(--legend);
      border-top:1px solid var(--border);
      display:flex; align-items:center;
      justify-content:center;
      padding:0 14px; gap:16px;
      font-family:'Share Tech Mono',monospace;
      font-size:9px; color:var(--muted);
    }}
    .dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
    ::-webkit-scrollbar {{ width:3px; }}
    ::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:2px; }}
  </style>
</head>
<body>

<header>
  <div class="logo">⬡ ANTAMINA · MONITOR PM10 · 4 ESTACIONES</div>
  <div class="hdr-right">
    <div>Corte: <span>{hora_corte}</span></div>
    <div>Actualizado: <span>{fecha_act}</span> (Perú)</div>
    <div>Próx. ~1h</div>
  </div>
</header>

<div class="body">

  <div class="charts-panel">
    <div class="charts-scroll" id="charts-scroll"></div>
  </div>

  <div class="map-panel" id="map-panel">
    {mapa_render}
  </div>

  <div class="legend-charts">
    <div class="li"><div class="line-solid"></div><span>Observado</span></div>
    <div class="li"><div class="line-pron"></div><span>Pronóstico</span></div>
    <div class="li"><div class="line-corte"></div><span>Corte hora actual</span></div>
    <div class="li"><div class="dot-max"></div><span>Máx. pronóstico</span></div>
  </div>

  <div class="legend-map">
    <div class="li"><div class="dot" style="background:#22c55e"></div><span>&lt; 20 μg/m³ Bajo</span></div>
    <div class="li"><div class="dot" style="background:#eab308"></div><span>20–50 μg/m³ Moderado</span></div>
    <div class="li"><div class="dot" style="background:#f97316"></div><span>50–100 μg/m³ Alto</span></div>
    <div class="li"><div class="dot" style="background:#ef4444"></div><span>&gt; 100 μg/m³ Muy Alto</span></div>
    <div class="li">Buffer: Dos Cruces / Tucush / Usupallares = 2km &nbsp;·&nbsp; Quebrada = 1km</div>
  </div>

</div>

<script>
const CHART_DATA = {chart_data};
const HORA_CORTE = "{hora_corte}";
const EJE_X_FIJO = CHART_DATA[0].eje_x;

const LAYOUT_BASE = {{
  paper_bgcolor: '#0a0e14',
  plot_bgcolor:  '#0a0e14',
  font:   {{ family:'Share Tech Mono, monospace', size:9, color:'#c9d8e8' }},
  margin: {{ t:8, r:8, b:38, l:40 }},
  xaxis: {{
    showgrid:true, gridcolor:'#1e2d3d', gridwidth:1,
    tickfont:{{ size:8 }}, color:'#4a6070', tickangle:-45,
    type:'category',
    categoryorder:'array',
    categoryarray: EJE_X_FIJO,
    range: [-0.5, EJE_X_FIJO.length - 0.5],
  }},
  yaxis: {{
    showgrid:true, gridcolor:'#1e2d3d', gridwidth:1,
    tickfont:{{ size:8 }}, color:'#4a6070', rangemode:'tozero',
    title:{{ text:'μg/m³', font:{{ size:8, color:'#4a6070' }} }}
  }},
  showlegend: false,
}};

const scroll = document.getElementById('charts-scroll');

CHART_DATA.forEach((est, i) => {{
  const block = document.createElement('div');
  block.className = 'chart-block';
  const label = document.createElement('div');
  label.className = 'chart-label';
  label.textContent = '📍 ' + est.nombre;
  const div = document.createElement('div');
  div.className = 'plotly-div';
  div.id = 'ch' + i;
  block.appendChild(label);
  block.appendChild(div);
  scroll.appendChild(block);

  const traces = [];

  if (est.obs.length) {{
    traces.push({{
      x: est.obs.map(d => d.x),
      y: est.obs.map(d => d.y),
      type:'scatter', mode:'lines',
      line:{{ color:'#94a3b8', width:1.5 }},
      hovertemplate:'%{{x}}<br>%{{y:.2f}} μg/m³<extra></extra>',
    }});
  }}

  if (est.pron.length) {{
    traces.push({{
      x: est.pron.map(d => d.x),
      y: est.pron.map(d => d.y),
      type:'scatter', mode:'lines',
      line:{{ color:'#00c8ff', width:1.5 }},
      hovertemplate:'%{{x}}<br>%{{y:.2f}} μg/m³<extra></extra>',
    }});
  }}

  if (est.max_time) {{
    traces.push({{
      x:[est.max_time], y:[est.max_val],
      type:'scatter', mode:'markers+text',
      marker:{{ color:'#ef4444', size:8, symbol:'circle',
                line:{{ color:'#fff', width:1 }} }},
      text:[est.max_val.toFixed(2)],
      textposition:'top center',
      textfont:{{ color:'#ef4444', size:9 }},
      hovertemplate:'Máx: %{{y:.2f}} μg/m³<extra></extra>',
    }});
  }}

  const layout = JSON.parse(JSON.stringify(LAYOUT_BASE));
  layout.shapes = [{{
    type:'line',
    x0:HORA_CORTE, x1:HORA_CORTE,
    y0:0, y1:1, yref:'paper',
    line:{{ color:'#f59e0b', width:1.5, dash:'dash' }}
  }}];
  layout.annotations = [{{
    x:HORA_CORTE, y:0.97, yref:'paper',
    text:HORA_CORTE, showarrow:false,
    font:{{ color:'#f59e0b', size:8 }},
    xanchor:'left', yanchor:'top',
    bgcolor:'rgba(245,158,11,0.12)',
    bordercolor:'#f59e0b', borderwidth:1, borderpad:2
  }}];

  Plotly.newPlot('ch'+i, traces, layout, {{
    responsive:true, displayModeBar:false
  }});
}});

setTimeout(function() {{
  if (window.L) {{
    Object.keys(window).forEach(function(k) {{
      if (k.startsWith('map_') && window[k] && window[k].invalidateSize) {{
        try {{ window[k].invalidateSize(); }} catch(e) {{}}
      }}
    }});
  }}
}}, 500);
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    now_peru   = datetime.now(PERU_TZ).replace(tzinfo=None)
    corte_dt   = now_peru.replace(minute=0, second=0, microsecond=0)
    hora_corte = corte_dt.strftime("%H:%M")

    print("=" * 55)
    print("  PM10 Monitor · Antamina · 4 Estaciones")
    print(f"  {now_peru.strftime('%d/%m/%Y %H:%M:%S')} (Hora Perú)")
    print(f"  Corte: {hora_corte}")
    print("=" * 55)

    token      = get_token()
    resultados = []

    for est in ESTACIONES:
        print(f"\n[{est['nombre']}] Calculando record del día...")
        try:
            record_code = get_record_code(est["location_code"])
            items       = get_timeserie(token, record_code)
            obs, pron   = procesar(items, corte_dt)
            max_item    = max(pron, key=lambda x: x["value"]) if pron else None
            max_val     = max_item["value"] if max_item else 0
            max_time    = max_item["time"]  if max_item else None
            _, cat, emoji = get_color(max_val)
            print(f"  Obs:{len(obs)} Pron:{len(pron)} Máx:{max_val:.2f} μg/m³ {emoji} {cat}")

            resultados.append({
                "nombre":     est["nombre"],
                "lat":        est["lat"],
                "lng":        est["lng"],
                "buffer_m":   est["buffer_m"],
                "max_val":    max_val,
                "max_time":   max_time,
                "n_obs":      len(obs),
                "n_pron":     len(pron),
                "observados": obs,
                "pronostico": pron,
            })
        except Exception as e:
            print(f"  ❌ Error: {e}")
            resultados.append({
                "nombre":est["nombre"], "lat":est["lat"], "lng":est["lng"],
                "buffer_m":est["buffer_m"], "max_val":0, "max_time":None,
                "n_obs":0, "n_pron":0, "observados":[], "pronostico":[],
            })

    mapa_render = generar_mapa(resultados)
    html        = generar_html(resultados, mapa_render, now_peru, hora_corte)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[✓] index.html generado. Corte: {hora_corte}")
