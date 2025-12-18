import uasyncio as asyncio
import network
import time
import task_handler
import time_handler
import app_main
import ota
import gc
import secret

# ÄNDRING: använd time.time() i stället för ticks_ms()
start_time = time.localtime()

def get_uptime():
    # ÄNDRING: uptime beräknas i sekunder -> dagar
    elapsed_seconds = time.time() - time_handler.start_time_s
    return "{:.3f} days".format(elapsed_seconds / 86400)

def get_start_time_str():
    """
    Returnerar starttiden i formatet 'YYYY-MM-DD HH:MM:SS'.
    Försöker använda time_handler.start_time_s, annars fallback till local start_time.
    """
    try:
        utc = time.localtime(time_handler.start_time_s)
    except AttributeError:
        utc = start_time
    
    offset = 2 if time_handler.is_summer_time(*utc[:3]) else 1
    t = time.localtime(time.mktime(utc) + offset * 3600)

    return "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])

def get_tasks_status():
    """Returnerar taskstatus som lista av dictar."""
    now_ms = time.ticks_ms()
    now_s = time.time()

    status_list = []
    for name, task in sorted(task_handler.TASKS.items(), key=lambda x: x[0]):
        last_health = task_handler.HEALTH.get(name, 0)
        stale = time.ticks_diff(now_ms, last_health)

        status = "Klar" if task.done() else "Körs"

        start_s = task_handler.HEALTH_START.get(name, None)
        if start_s is None or start_s == 0:
            uptime = "0.000"
        else:
            uptime = "{:.3f}".format((now_s - start_s) / 86400)

        status_list.append({
            "name": name,
            "status": status,
            "stale_ms": stale,
            "Upptid": uptime
        })
    gc.collect()
    return status_list

def get_status_json():
    import ujson
    # Vi skickar nu starttid istället för IP
    start_str = get_start_time_str()
    data = {
        "start_time": start_str,
        "uptime": get_uptime(),
        "tasks": get_tasks_status(),
        "display": app_main.DISPLAY_DATA
    }
    gc.collect()
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" +
        ujson.dumps(data)
    )

def get_status_html():
    # IP används inte längre för visning, men behålls om du vill använda senare
    wlan = network.WLAN(network.STA_IF)
    ip = wlan.ifconfig()[0] if wlan.isconnected() else "Ej ansluten"

    uptime = get_uptime()
    start_str = get_start_time_str()
    d = app_main.DISPLAY_DATA

    html_content = f"""\
<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8" />
<title>Kylskåpet Status</title>
<style>
    body {{ font-family: sans-serif; padding: 20px; background:#f0f0f0; }}
    h1, h2 {{ color: #333; }}
    table {{
        background:#fff;
        border:1px solid #ccc;
        border-collapse:collapse;
        width: auto;
        min-width: 260px;
        margin-bottom:20px;
    }}
    th {{
        background:#eee;
        text-align:left;
    }}
    td, th {{
        padding:4px 8px;
        text-align:left;
        vertical-align:middle;
    }}
    td.label {{
        text-align:left;
        font-weight:bold;
        width: 120px;
        white-space: nowrap;
    }}
    td.value {{
        text-align:left;
    }}
    .button {{
        display:inline-block;
        padding:10px 20px;
        margin:5px;
        background:#007aff;
        color:#fff;
        text-decoration:none;
        border-radius:6px;
        font-weight:bold;
        border:none;
        cursor:pointer;
    }}
    .red-button {{ background:#d9534f; }}
    .admin-box {{
        margin-top:40px;
        padding:15px;
        background:#fff;
        border:1px solid #ccc;
        border-radius:6px;
        max-width: 380px;
        display: inline-block;
    }}
    /* Lösenordsfältet rad */
    .admin-row {{
        margin-bottom: 12px;
    }}

    /* Knappar under lösenordet */
    .admin-buttons {{
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}

    .password-input {{
        padding:6px 8px;
        margin-top:4px;
        width: 100%;
        box-sizing: border-box;
    }}
</style>
</head>
<body>
    <h1>Kylskåpet Status</h1>
    <p><strong>Startad:</strong> {start_str}</p>
    <p><strong>Uptime:</strong> <span id="uptime">{uptime}</span></p>

    <h2>Displaydata</h2>
    <table id="display-table">
        <tbody>
            <tr><td class="label">Tid</td><td class="value" id="d_time">{d['time_str']}</td></tr>
            <tr><td class="label">Temperatur</td><td class="value" id="d_temp">{d['temperature']} °C</td></tr>
            <tr><td class="label">Min (Styr)</td><td class="value" id="d_min">{d['temp_min']} °C</td></tr>
            <tr><td class="label">Max (Styr)</td><td class="value" id="d_max">{d['temp_max']} °C</td></tr>
            <tr><td class="label">Min (2h)</td><td class="value" id="d_min_2h">{d['temp_min_2h']} °C</td></tr>
            <tr><td class="label">Max (2h)</td><td class="value" id="d_max_2h">{d['temp_max_2h']} °C</td></tr>
            <tr><td class="label">Kompressor</td><td class="value" id="d_comp">{d['comp_status']}</td></tr>
            <tr><td class="label">Spänning</td><td class="value" id="d_v">{d['voltage']} V</td></tr>
            <tr><td class="label">Ström</td><td class="value" id="d_i">{d['current']} A</td></tr>
            <tr><td class="label">Effekt</td><td class="value" id="d_p">{d['power']} W</td></tr>
            <tr><td class="label">Minne</td><td class="value" id="d_mem">{d['mem_free_kb']} KB / {d['mem_used_kb']} KB</td></tr>
        </tbody>
    </table>

    <h2>Tasks</h2>
    <table id="task-table">
        <thead><tr><th>Name</th><th>Status</th><th>Health (ms)</th><th>Uptime (days)</th></tr></thead>
        <tbody id="task-body"><tr><td colspan="4">Laddar...</td></tr></tbody>
    </table>

    <!-- ADMIN-RUTAN MED NY LAYOUT -->
    <div class="admin-box">
        <h2>Administration</h2>

        <form method="GET" class="admin-form">

            <div class="admin-row">
                <label>
                    Lösenord:
                    <input type="password" name="pwd" class="password-input" />
                </label>
            </div>

            <div class="admin-buttons">
                <button type="submit" class="button" formaction="/ota">Starta OTA-uppdatering</button>
                <button type="submit" class="button red-button" formaction="/reboot">Starta om</button>
            </div>

        </form>
    </div>

    <script>
        async function updateStatus() {{
            try {{
                const res = await fetch('/status.json');
                const data = await res.json();
                document.getElementById('uptime').innerText = data.uptime;
                const d = data.display;
                if (d) {{
                    document.getElementById('d_time').innerText = d.time_str || '';
                    document.getElementById('d_temp').innerText = (d.temperature?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_min').innerText = (d.temp_min?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_max').innerText = (d.temp_max?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_min_2h').innerText = (d.temp_min_2h?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_max_2h').innerText = (d.temp_max_2h?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_comp').innerText = d.comp_status || '--';
                    document.getElementById('d_v').innerText = (d.voltage?.toFixed(2) || '--') + ' V';
                    document.getElementById('d_i').innerText = (d.current?.toFixed(2) || '--') + ' A';
                    document.getElementById('d_p').innerText = (d.power?.toFixed(2) || '--') + ' W';
                    document.getElementById('d_mem').innerText = `${{d.mem_free_kb}} KB / ${{d.mem_used_kb}} KB`;
                }}
                const tbody = document.getElementById('task-body');
                tbody.innerHTML = '';
                data.tasks.forEach(t => {{
                    tbody.insertAdjacentHTML('beforeend',
                        `<tr><td>${{t.name}}</td><td>${{t.status}}</td><td>${{t.stale_ms}}</td><td>${{t.Upptid}}</td></tr>`);
                }});
            }} catch (e) {{
                console.log("Fel vid statusuppdatering:", e);
            }}
        }}
        setInterval(updateStatus, 5000);
        updateStatus();
    </script>
</body>
</html>
"""
    gc.collect()
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" +
        html_content
    )

# ===== NYTT: enkel parser för path + query =====

def parse_path_and_query(request_line_str):
    """
    Ex: 'GET /ota?pwd=xxx HTTP/1.1' -> ('/ota', {'pwd':'xxx'})
    """
    try:
        parts = request_line_str.split()
        if len(parts) < 2:
            return "/", {}
        full_path = parts[1]
        if "?" not in full_path:
            return full_path, {}
        path, qs = full_path.split("?", 1)
        params = {}
        for pair in qs.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v
        return path, params
    except:
        return "/", {}


async def handle_client(reader, writer, ota_callback=None):
    try:
        request_line = await reader.readline()
        if not request_line:
            await writer.aclose()
            return

        request_str = request_line.decode('utf-8').strip()
        path, params = parse_path_and_query(request_str)
        pwd = params.get("pwd", "")

        # Läs/ignorera resten av headers
        while True:
            header = await reader.readline()
            if not header or header == b'\r\n':
                break

        # Routing
        if path == "/status.json":
            response = get_status_json()

        elif path == "/ota":
            if pwd != secret.WEB_PASSWORD:
                response = (
                    "HTTP/1.1 403 Forbidden\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    "Connection: close\r\n\r\n"
                    "<h1>Fel lösenord</h1><p>OTA avbruten.</p>"
                )
                await writer.awrite(response)
                await writer.drain()
                await writer.aclose()
                return

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Connection: close\r\n\r\n"
                "OTA startad..."
            )
            await writer.awrite(response)
            await writer.drain()
            await asyncio.sleep(1)
            await writer.aclose()
            await ota.ota_check()
            return

        elif path == "/reboot":
            if pwd != secret.WEB_PASSWORD:
                response = (
                    "HTTP/1.1 403 Forbidden\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    "Connection: close\r\n\r\n"
                    "<h1>Fel lösenord</h1><p>Omstart avbruten.</p>"
                )
                await writer.awrite(response)
                await writer.drain()
                await writer.aclose()
                return

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Connection: close\r\n\r\n"
                "Startar om..."
            )
            await writer.awrite(response)
            await writer.drain()
            await writer.aclose()
            await task_handler.graceful_restart()
            return

        else:
            response = get_status_html()

        await writer.awrite(response)
        await writer.drain()
        await writer.aclose()
        gc.collect()

    except Exception as e:
        print("Fel i hantering av klient:", e)
        gc.collect()
        try:
            await writer.aclose()
            gc.collect()
        except:
            pass

async def start_web_server(ota_callback=None, host='0.0.0.0', port=80):
    print(f"🌐 Startar asynkron webbserver på {host}:{port}")
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, ota_callback), host, port)

    while True:
        task_handler.feed_health("web_server.start_web_server")
        gc.collect()
        await asyncio.sleep(5)
