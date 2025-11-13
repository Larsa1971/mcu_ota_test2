import uasyncio as asyncio
import network
import time
import task_handler
import app_main
import ota

start_time = time.ticks_ms()

def get_uptime():
    return "{:.1f} sek".format(time.ticks_diff(time.ticks_ms(), start_time) / 1000)

def get_tasks_status():
    """Returnerar taskstatus som lista av dictar."""
    now = time.ticks_ms()
    status_list = []
    for name, task in task_handler.TASKS.items():
        last_health = task_handler.HEALTH.get(name, 0)
        stale = time.ticks_diff(now, last_health)
        status = "Klar" if task.done() else "Körs"
        status_list.append({
            "name": name,
            "status": status,
            "stale_ms": stale
        })
    return status_list

def get_status_json():
    import ujson
    wlan = network.WLAN(network.STA_IF)
    ip = wlan.ifconfig()[0] if wlan.isconnected() else "Ej ansluten"
    data = {
        "ip": ip,
        "uptime": get_uptime(),
        "tasks": get_tasks_status(),
        "display": app_main.DISPLAY_DATA
    }
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" +
        ujson.dumps(data)
    )

def get_status_html():
    wlan = network.WLAN(network.STA_IF)
    ip = wlan.ifconfig()[0] if wlan.isconnected() else "Ej ansluten"
    uptime = get_uptime()
    d = app_main.DISPLAY_DATA

    html_content = f"""\
<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8" />
<title>Pico W Status</title>
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
    }}
    .red-button {{ background:#d9534f; }}
</style>
</head>
<body>
    <h1>Pico W Status</h1>
    <p><strong>IP-adress:</strong> {ip}</p>
    <p><strong>Uptime:</strong> <span id="uptime">{uptime}</span></p>

    <a href="/ota" class="button">Starta OTA-uppdatering</a>
    <a href="/reboot" class="button red-button">Starta om</a>

    <h2>Displaydata</h2>
    <table id="display-table">
        <tbody>
            <tr><td class="label">Tid</td><td class="value" id="d_time">{d['time_str']}</td></tr>
            <tr><td class="label">Temperatur</td><td class="value" id="d_temp">{d['temperature']} °C</td></tr>
            <tr><td class="label">Kompressor</td><td class="value" id="d_comp">{d['comp_status']}</td></tr>
            <tr><td class="label">Min (Styr)</td><td class="value" id="d_min">{d['temp_min']} °C</td></tr>
            <tr><td class="label">Max (Styr)</td><td class="value" id="d_max">{d['temp_max']} °C</td></tr>
            <tr><td class="label">Min (2h)</td><td class="value" id="d_min_2h">{d['temp_min_2h']} °C</td></tr>
            <tr><td class="label">Max (2h)</td><td class="value" id="d_max_2h">{d['temp_max_2h']} °C</td></tr>
            <tr><td class="label">Spänning</td><td class="value" id="d_v">{d['voltage']} V</td></tr>
            <tr><td class="label">Ström</td><td class="value" id="d_i">{d['current']} A</td></tr>
            <tr><td class="label">Effekt</td><td class="value" id="d_p">{d['power']} W</td></tr>
            <tr><td class="label">Minne</td><td class="value" id="d_mem">{d['mem_free_kb']} KB / {d['mem_used_kb']} KB</td></tr>
        </tbody>
    </table>

    <h2>Tasks</h2>
    <table id="task-table">
        <thead><tr><th>Namn</th><th>Status</th><th>Health (ms)</th></tr></thead>
        <tbody id="task-body"><tr><td colspan="3">Laddar...</td></tr></tbody>
    </table>

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
                    document.getElementById('d_comp').innerText = d.comp_status || '--';
                    document.getElementById('d_min').innerText = (d.temp_min?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_max').innerText = (d.temp_max?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_min_2h').innerText = (d.temp_min_2h?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_max_2h').innerText = (d.temp_max_2h?.toFixed(2) || '--') + ' °C';
                    document.getElementById('d_v').innerText = (d.voltage?.toFixed(2) || '--') + ' V';
                    document.getElementById('d_i').innerText = (d.current?.toFixed(2) || '--') + ' A';
                    document.getElementById('d_p').innerText = (d.power?.toFixed(2) || '--') + ' W';
                    document.getElementById('d_mem').innerText = `${{d.mem_free_kb}} KB / ${{d.mem_used_kb}} KB`;
                }}
                const tbody = document.getElementById('task-body');
                tbody.innerHTML = '';
                data.tasks.forEach(t => {{
                    tbody.insertAdjacentHTML('beforeend',
                        `<tr><td>${{t.name}}</td><td>${{t.status}}</td><td>${{t.stale_ms}}</td></tr>`);
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
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" +
        html_content
    )

async def handle_client(reader, writer, ota_callback=None):
    try:
        request_line = await reader.readline()
        if not request_line:
            await writer.aclose()
            return

        request = request_line.decode('utf-8').strip()
        while True:
            header = await reader.readline()
            if not header or header == b'\r\n':
                break

        if "GET /status.json" in request:
            response = get_status_json()
        elif "GET /ota" in request:
            response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\nOTA startad..."
            await writer.awrite(response)
            await writer.drain()
            await asyncio.sleep(1)
            await ota.ota_check()
            await writer.aclose()
            return
        elif "GET /reboot" in request:
            response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\nStartar om..."
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

    except Exception as e:
        print("Fel i hantering av klient:", e)
        try:
            await writer.aclose()
        except:
            pass


async def start_web_server(ota_callback=None, host='0.0.0.0', port=80):
    print(f"🌐 Startar asynkron webbserver på {host}:{port}")
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, ota_callback), host, port)

    while True:
        task_handler.feed_health("web_server.start_web_server")
        await asyncio.sleep(5)

