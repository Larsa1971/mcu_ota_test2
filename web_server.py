import uasyncio as asyncio
import time
import task_handler
import time_handler
import app_main
import ota
import gc
import secret

start_time = time.localtime()

def get_uptime():
    elapsed_seconds = time.time() - time_handler.start_time_s
    return "{:.3f} days".format(elapsed_seconds / 86400)

def get_start_time_str():
    try:
        utc = time.localtime(time_handler.start_time_s)
    except AttributeError:
        utc = start_time

    offset = 2 if time_handler.is_summer_time(*utc[:3]) else 1
    t = time.localtime(time.mktime(utc) + offset * 3600)
    return "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])

def get_tasks_status():
    now_ms = time.ticks_ms()
    now_s = time.time()

    status_list = []
    for name in sorted(task_handler.TASKS.keys()):
        task = task_handler.TASKS[name]
        last_health = task_handler.HEALTH.get(name, 0)
        stale = time.ticks_diff(now_ms, last_health)
        status = "Klar" if task.done() else "Körs"

        start_s = task_handler.HEALTH_START.get(name, 0) or 0
        uptime = "0.000" if start_s == 0 else "{:.3f}".format((now_s - start_s) / 86400)

        status_list.append({
            "name": name,
            "status": status,
            "stale_ms": stale,
            "Upptid": uptime
        })
    return status_list

def _json_response(payload):
    import ujson
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" +
        ujson.dumps(payload)
    )

def get_status_json():
    return _json_response({
        "start_time": get_start_time_str(),
        "uptime": get_uptime(),
        "tasks": get_tasks_status(),
        "display": app_main.DISPLAY_DATA
    })

def get_display_json():
    return _json_response({
        "start_time": get_start_time_str(),
        "uptime": get_uptime(),
        "display": app_main.DISPLAY_DATA
    })

def get_tasks_json():
    return _json_response({
        "tasks": get_tasks_status()
    })

def get_status_html():
    uptime = get_uptime()
    start_str = get_start_time_str()
    d = app_main.DISPLAY_DATA
    tasks = get_tasks_status()

    # Bygg tasks-rader på serversidan (så hela sidan alltid är "färdig" vid reload)
    tasks_rows = ""
    if tasks:
        for t in tasks:
            tasks_rows += (
                "<tr>"
                f"<td>{t.get('name','')}</td>"
                f"<td>{t.get('status','')}</td>"
                f"<td>{t.get('stale_ms','')}</td>"
                f"<td>{t.get('Upptid','')}</td>"
                "</tr>"
            )
    else:
        tasks_rows = "<tr><td colspan='4'>Inga tasks</td></tr>"

    html_content = f"""\
<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8" />
<title>{secret.WEB_NAME}</title>
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0" />
<meta http-equiv="Pragma" content="no-cache" />
<meta http-equiv="Expires" content="0" />
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
    th {{ background:#eee; text-align:left; }}
    td, th {{ border:1px solid #ccc; padding:4px 8px; text-align:left; vertical-align:middle; }}
    td.label {{ font-weight:bold; width: 140px; white-space: nowrap; }}
    .button {{
        display:inline-block; padding:10px 20px; margin:5px;
        background:#007aff; color:#fff; border-radius:6px; font-weight:bold;
        border:none; cursor:pointer;
    }}
    .red-button {{ background:#d9534f; }}
    .admin-box {{
        margin-top:40px; padding:15px; background:#fff; border:1px solid #ccc;
        border-radius:6px; max-width: 380px; display: inline-block;
    }}
    .admin-row {{ margin-bottom: 12px; }}
    .admin-buttons {{ display:flex; flex-direction:column; gap:8px; }}
    .password-input {{ padding:6px 8px; margin-top:4px; width:100%; box-sizing:border-box; }}
</style>
</head>
<body>
    <h1>{secret.WEB_NAME}</h1>

    <h2>Displaydata</h2>
    <table id="display-table">
        <tbody>
            <tr><td class="label">Tid</td><td class="value">{d.get('time_str','')}</td></tr>

            <tr><td class="label">Startad</td><td class="value">{start_str}</td></tr>
            <tr><td class="label">Uptid</td><td class="value">{uptime}</td></tr>


            <tr><td class="label">Temperatur</td><td class="value">{d.get('temperature','--')} °C</td></tr>
            <tr><td class="label">Min (Styr)</td><td class="value">{d.get('temp_min','--')} °C</td></tr>
            <tr><td class="label">Max (Styr)</td><td class="value">{d.get('temp_max','--')} °C</td></tr>
            <tr><td class="label">Min (6h)</td><td class="value">{d.get('temp_min_2h','--')} °C</td></tr>
            <tr><td class="label">Max (6h)</td><td class="value">{d.get('temp_max_2h','--')} °C</td></tr>
            <tr><td class="label">Kompressor</td><td class="value">{d.get('comp_status','--')}</td></tr>

            <tr><td class="label">Spänning</td><td class="value">{d.get('voltage','--')} V</td></tr>
            <tr><td class="label">Ström</td><td class="value">{d.get('current','--')} A</td></tr>
            <tr><td class="label">Effekt</td><td class="value">{d.get('power','--')} W</td></tr>

            <tr><td class="label">Total Ström</td><td class="value">{d.get('charge_ah','--')} Ah</td></tr>
            <tr><td class="label">Total Effekt</td><td class="value">{d.get('energy_wh','--')} Wh</td></tr>
            <tr><td class="label">Snitt Ström</td><td class="value">{d.get('avg_current_a','--')} A</td></tr>
            <tr><td class="label">Snitt Effekt</td><td class="value">{d.get('avg_power_w','--')} W</td></tr>
            <tr><td class="label">Under timmar</td><td class="value">{d.get('elapsed_h','--')} h</td></tr>

            <tr><td class="label">Dygn Ström</td><td class="value">{d.get('daily_ah','--')} Ah</td></tr>
            <tr><td class="label">Dygn Effekt</td><td class="value">{d.get('daily_wh','--')} Wh</td></tr>

            <tr><td class="label">Igår Datum</td><td class="value">{d.get('yesterday_date','--')}</td></tr>
            <tr><td class="label">Igår Ström</td><td class="value">{d.get('yesterday_ah','--')} Ah</td></tr>
            <tr><td class="label">Igår Effekt</td><td class="value">{d.get('yesterday_wh','--')} Wh</td></tr>

            <tr><td class="label">Minne ledigt/använt</td><td class="value">{d.get('mem_free_kb','--')} KB / {d.get('mem_used_kb','--')} KB</td></tr>
        </tbody>
    </table>

    <h2>Tasks</h2>
    <table id="task-table">
        <thead><tr><th>Name</th><th>Status</th><th>Health (ms)</th><th>Uptime (days)</th></tr></thead>
        <tbody>
            {tasks_rows}
        </tbody>
    </table>

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

    <!-- Reload hela sidan var 5:e sekund -->
    <script>
        setTimeout(function() {{
            // cache-buster så den verkligen hämtar ny sida
            window.location.replace('/?ts=' + Date.now());
        }}, 5000);
    </script>

</body>
</html>
"""
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
        "Pragma: no-cache\r\n"
        "Expires: 0\r\n"
        "Connection: close\r\n\r\n" +
        html_content
    )

def parse_path_and_query(request_line_str):
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

        while True:
            header = await reader.readline()
            if not header or header == b'\r\n':
                break

        if path == "/status.json":
            response = get_status_json()
        elif path == "/display.json":
            response = get_display_json()
        elif path == "/tasks.json":
            response = get_tasks_json()

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
        await writer.awrite(b"")
        await writer.aclose()
        gc.collect()

    except Exception as e:
        print("Fel i hantering av klient:", e)
        try:
            await writer.aclose()
        except:
            pass
        gc.collect()

async def start_web_server(ota_callback=None, host='0.0.0.0', port=80):
    print(f"🌐 Startar asynkron webbserver på {host}:{port}")
    await asyncio.start_server(lambda r, w: handle_client(r, w, ota_callback), host, port)

    while True:
        task_handler.feed_health("web_server.start_web_server")
        await asyncio.sleep(5)
