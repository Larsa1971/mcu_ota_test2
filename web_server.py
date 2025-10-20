import uasyncio as asyncio
import machine
import network
import time
import task_handler

start_time = time.ticks_ms()

def get_uptime():
    return "{:.1f} sek".format(time.ticks_diff(time.ticks_ms(), start_time) / 1000)

def get_status_html():
    wlan = network.WLAN(network.STA_IF)
    ip = wlan.ifconfig()[0] if wlan.isconnected() else "Ej ansluten"
    uptime = get_uptime()

    html_content = f"""\
<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="utf-8" />
    <title>Pico W Status</title>
    <style>
        body {{ font-family: sans-serif; padding: 20px; background:#f0f0f0; }}
        h1 {{ color: #333; }}
        a.button {{
            display: inline-block;
            padding: 10px 20px;
            margin: 10px 5px;
            background: #007aff;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
        }}
        a.button:hover {{ background: #005bb5; }}
        a.red-button {{ background: #d9534f; }}
        a.red-button:hover {{ background: #b52b24; }}
    </style>
</head>
<body>
    <h1>Pico W Status</h1>
    <p><strong>IP-adress:</strong> {ip}</p>
    <p><strong>Uptime:</strong> {uptime}</p>
    <a href="/ota" class="button">Starta OTA-uppdatering</a>
    <a href="/reboot" class="button red-button">Starta om enheten</a>
</body>
</html>
"""
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n"
        "\r\n" +
        html_content
    )
    return response

def get_simple_response(message="OK"):
    html_content = f"<html><body><h1>{message}</h1></body></html>"
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n"
        "\r\n" +
        html_content
    )
    return response

async def handle_client(reader, writer, ota_callback=None):
    try:
        request_line = await reader.readline()
        if not request_line:
            await writer.aclose()
            return

        request = request_line.decode('utf-8').strip()
        print("HTTP-request:", request)

        # Läs och ignorerar övriga headers
        while True:
            header = await reader.readline()
            if not header or header == b'\r\n':
                break

        if "GET /ota" in request:
            response = get_simple_response("OTA startad...")
            writer.write(response.encode('utf-8'))
            await writer.drain()
            await writer.aclose()
            if ota_callback:
                # Starta OTA efter en kort delay för att hinna skicka svar
                asyncio.get_event_loop().call_later(0.1, ota_callback)

        elif "GET /reboot" in request:
            response = get_simple_response("Startar om enheten...")
            writer.write(response.encode('utf-8'))
            await writer.drain()
            await writer.aclose()
            await task_handler.graceful_restart()

        elif "GET /" in request:
            response = get_status_html()
            writer.write(response.encode('utf-8'))
            await writer.drain()
            await writer.aclose()
        else:
            response = get_status_html()
            writer.write(response.encode('utf-8'))
            await writer.drain()
            await writer.aclose()

    except Exception as e:
        print("Fel i hantering av klient:", e)
        try:
            await writer.aclose()
        except:
            pass

import uasyncio as asyncio

async def start_web_server(ota_callback=None, host='0.0.0.0', port=80):
    print(f"Startar asynkron webbserver på {host}:{port}")
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, ota_callback), host, port)
    
    # Kör servern “för evigt” genom att låta en loop som sover hålla event-loopen aktiv
    while True:
        await asyncio.sleep(3600)  # sover 1 timme och loopar sedan

