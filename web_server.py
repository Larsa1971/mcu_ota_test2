import uasyncio as asyncio
import time
import task_handler
import time_handler
import app_main
import ota
import gc
import secret
import os

start_time = time.localtime()

DATA_DIR = "/data"

# -------------------------
# Helpers
# -------------------------

def html_escape(v):
    try:
        s = "" if v is None else str(v)
    except Exception:
        s = ""
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#39;")
    return s


async def _write_all(writer, data, chunk_size=1024):
    if isinstance(data, str):
        data = data.encode("utf-8")

    n = len(data)
    i = 0
    while i < n:
        await writer.awrite(data[i:i + chunk_size])
        i += chunk_size
    await writer.drain()


def _http_response_bytes(body_bytes, content_type):
    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
        "Pragma: no-cache\r\n"
        "Expires: 0\r\n"
        "Connection: close\r\n\r\n"
    ) % (content_type, len(body_bytes))
    return headers.encode("utf-8") + body_bytes


def _http_response_bytes_extra(body_bytes, content_type, status_line="200 OK", extra_headers=None):
    if extra_headers is None:
        extra_headers = []
    hdr = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
    ) % (status_line, content_type, len(body_bytes))
    for h in extra_headers:
        hdr += h + "\r\n"
    hdr += "\r\n"
    return hdr.encode("utf-8") + body_bytes


def _http_error_html(status_code, body_html):
    reason = "Forbidden" if status_code == 403 else "Error"
    body_bytes = body_html.encode("utf-8")
    headers = (
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: %d\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
        "Pragma: no-cache\r\n"
        "Expires: 0\r\n"
        "Connection: close\r\n\r\n"
    ) % (status_code, reason, len(body_bytes))
    return headers.encode("utf-8") + body_bytes


# -------------------------
# File listing helpers
# -------------------------

def url_decode(s: str) -> str:
    out = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == '+':
            out += ' '
            i += 1
        elif c == '%' and i + 2 < len(s):
            try:
                out += chr(int(s[i+1:i+3], 16))
                i += 3
            except:
                out += c
                i += 1
        else:
            out += c
            i += 1
    return out


def safe_join_data(filename: str) -> str:
    filename = filename.replace("\\", "/")
    if "/" in filename or ".." in filename or filename == "":
        raise ValueError("Invalid filename")
    return DATA_DIR.rstrip("/") + "/" + filename


def list_data_files():
    try:
        files = os.listdir(DATA_DIR)
    except OSError:
        return []
    out = []
    for f in files:
        if f in (".", ".."):
            continue
        try:
            st = os.stat(DATA_DIR + "/" + f)
            if (st[0] & 0x4000) == 0:
                out.append(f)
        except:
            out.append(f)
    out.sort()
    return out


# -------------------------
# Status data
# -------------------------

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


def get_status_json_bytes():
    import ujson
    payload = {
        "start_time": get_start_time_str(),
        "uptime": get_uptime(),
        "tasks": get_tasks_status(),
        "display": app_main.DISPLAY_DATA
    }
    body = ujson.dumps(payload).encode("utf-8")
    return _http_response_bytes(body, "application/json; charset=utf-8")


def get_display_json_bytes():
    import ujson
    payload = {
        "start_time": get_start_time_str(),
        "uptime": get_uptime(),
        "display": app_main.DISPLAY_DATA
    }
    body = ujson.dumps(payload).encode("utf-8")
    return _http_response_bytes(body, "application/json; charset=utf-8")


def get_tasks_json_bytes():
    import ujson
    payload = {"tasks": get_tasks_status()}
    body = ujson.dumps(payload).encode("utf-8")
    return _http_response_bytes(body, "application/json; charset=utf-8")


# -------------------------
# HTML page
# -------------------------

def get_status_html_bytes():
    uptime = get_uptime()
    start_str = get_start_time_str()
    d = app_main.DISPLAY_DATA
    tasks = get_tasks_status()

    if tasks:
        rows = []
        for t in tasks:
            rows.append(
                "<tr>"
                "<td>%s</td>"
                "<td>%s</td>"
                "<td>%s</td>"
                "<td>%s</td>"
                "</tr>" % (
                    html_escape(t.get("name", "")),
                    html_escape(t.get("status", "")),
                    html_escape(t.get("stale_ms", "")),
                    html_escape(t.get("Upptid", "")),
                )
            )
        tasks_rows = "".join(rows)
    else:
        tasks_rows = "<tr><td colspan='4'>Inga tasks</td></tr>"

    files = list_data_files()
    if files:
        file_items = []
        for f in files:
            ef = html_escape(f)
            file_items.append(
                "<li>"
                "<a href=\"#\" onclick=\"openFile('%s');return false;\">%s</a> "
                "<a class=\"dl\" href=\"/download?name=%s\">[ladda ner]</a>"
                "</li>" % (ef, ef, ef)
            )
        files_items_html = "".join(file_items)
    else:
        files_items_html = "<li>(Inga filer i %s)</li>" % html_escape(DATA_DIR)

    web_bredd = int(getattr(secret, "WEB_BREDD", 700))

    values = {
        "web_name": html_escape(secret.WEB_NAME),
        "web_bredd": web_bredd,

        "time_str": html_escape(d.get("time_str", "")),
        "start_str": html_escape(start_str),
        "uptime": html_escape(uptime),

        "temperature": html_escape(d.get("temperature", "--")),
        "temp_min": html_escape(d.get("temp_min", "--")),
        "temp_max": html_escape(d.get("temp_max", "--")),
        "temp_min_2h": html_escape(d.get("temp_min_2h", "--")),
        "temp_max_2h": html_escape(d.get("temp_max_2h", "--")),
        "comp_status": html_escape(d.get("comp_status", "--")),

        "voltage": html_escape(d.get("voltage", "--")),
        "current": html_escape(d.get("current", "--")),
        "power": html_escape(d.get("power", "--")),

        "charge_ah": html_escape(d.get("charge_ah", "--")),
        "energy_wh": html_escape(d.get("energy_wh", "--")),
        "avg_current_a": html_escape(d.get("avg_current_a", "--")),
        "avg_power_w": html_escape(d.get("avg_power_w", "--")),
        "elapsed_h": html_escape(d.get("elapsed_h", "--")),

        "daily_ah": html_escape(d.get("daily_ah", "--")),
        "daily_wh": html_escape(d.get("daily_wh", "--")),

        "yesterday_date": html_escape(d.get("yesterday_date", "--")),
        "yesterday_ah": html_escape(d.get("yesterday_ah", "--")),
        "yesterday_wh": html_escape(d.get("yesterday_wh", "--")),

        "mem_free_kb": html_escape(d.get("mem_free_kb", "--")),
        "mem_used_kb": html_escape(d.get("mem_used_kb", "--")),

        "tasks_rows": tasks_rows,
        "data_dir": html_escape(DATA_DIR),
        "files_items": files_items_html,
    }

    html_template = """\
<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%(web_name)s</title>
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0" />
<meta http-equiv="Pragma" content="no-cache" />
<meta http-equiv="Expires" content="0" />
<style>
    body { font-family: sans-serif; padding: 0; margin: 0; background:#f0f0f0; }
    h1, h2 { color: #333; }

    /* Vänsterjusterat. På mobil fyller den skärmen. */
    .page {
        max-width: %(web_bredd)spx;
        width: 100%%;
        margin: 0;
        padding: 12px;
        box-sizing: border-box;
    }

    table {
        background:#fff;
        border:1px solid #ccc;
        border-collapse:collapse;
        width: 100%%;
        margin-bottom:20px;
        box-sizing: border-box;
    }
    th { background:#eee; text-align:left; }
    td, th { border:1px solid #ccc; padding:4px 8px; text-align:left; vertical-align:middle; }
    td.label { font-weight:bold; width: 140px; white-space: nowrap; }

    /* --- Tasks: fasta kolumnbredder --- */
    #task-table { table-layout: fixed; }
    #task-table th, #task-table td {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    /* valfritt: lite mindre font i task-tabellen */
    /* #task-table { font-size: 0.95em; } */

    .button {
        display:inline-block; padding:10px 20px; margin:5px;
        background:#007aff; color:#fff; border-radius:6px; font-weight:bold;
        border:none; cursor:pointer;
    }
    .red-button { background:#d9534f; }

    .file-box, .admin-box {
        padding:15px; background:#fff; border:1px solid #ccc;
        border-radius:6px;
        width: 100%%;
        box-sizing: border-box;
        display:block;
    }
    .file-box { margin: 0 0 20px 0; }
    .admin-box { clear: both; margin-top: 0; }

    .admin-row { margin-bottom: 12px; }
    .admin-buttons { display:flex; flex-direction:column; gap:8px; }
    .password-input { padding:6px 8px; margin-top:4px; width:100%%; box-sizing:border-box; }
    .js-status { font-size: 12px; color:#555; margin: 8px 0 16px 0; }

    .file-box ul { padding-left: 18px; margin: 0; }
    .file-box li { margin: 6px 0; }
    .file-box a.dl { color: #666; font-size: 0.9em; text-decoration: none; }

    .modal { display:none; position:fixed; z-index:999; left:0; top:0; width:100%%; height:100%%;
             background: rgba(0,0,0,0.55); }

    .modal-content {
        background:#fff;
        margin:10vh 0 0 0;
        padding:16px;
        width: 100%%;
        max-width: %(web_bredd)spx;
        border-radius:10px;
        box-shadow:0 10px 30px rgba(0,0,0,0.35);
        box-sizing: border-box;
    }
    .row { display:flex; justify-content:space-between; gap:10px; align-items:center; }
    pre {
        white-space: pre-wrap;
        word-break: break-word;
        background:#f6f6f6;
        padding:12px;
        border-radius:8px;
        max-height: 60vh;
        overflow:auto;
        width:100%%;
        box-sizing:border-box;
    }
    .file-close-btn { padding:8px 12px; border-radius:8px; border:1px solid #ccc; background:#fafafa; }
</style>
</head>
<body>
<div class="page">
    <h1>%(web_name)s</h1>

    <div class="js-status" id="js_status">JS: laddar...</div>

    <h2>Displaydata</h2>
    <table id="display-table">
        <tbody>
            <tr><td class="label">Tid</td><td class="value" id="time_str">%(time_str)s</td></tr>
            <tr><td class="label">Startad</td><td class="value" id="start_time">%(start_str)s</td></tr>
            <tr><td class="label">Uptid</td><td class="value" id="uptime">%(uptime)s</td></tr>

            <tr><td class="label">Temperatur</td><td class="value" id="temperature">%(temperature)s °C</td></tr>
            <tr><td class="label">Min (Styr)</td><td class="value" id="temp_min">%(temp_min)s °C</td></tr>
            <tr><td class="label">Max (Styr)</td><td class="value" id="temp_max">%(temp_max)s °C</td></tr>
            <tr><td class="label">Min (6h)</td><td class="value" id="temp_min_2h">%(temp_min_2h)s °C</td></tr>
            <tr><td class="label">Max (6h)</td><td class="value" id="temp_max_2h">%(temp_max_2h)s °C</td></tr>
            <tr><td class="label">Kompressor</td><td class="value" id="comp_status">%(comp_status)s</td></tr>

            <tr><td class="label">Spänning</td><td class="value" id="voltage">%(voltage)s V</td></tr>
            <tr><td class="label">Ström</td><td class="value" id="current">%(current)s A</td></tr>
            <tr><td class="label">Effekt</td><td class="value" id="power">%(power)s W</td></tr>

            <tr><td class="label">Total Ström</td><td class="value" id="charge_ah">%(charge_ah)s Ah</td></tr>
            <tr><td class="label">Total Effekt</td><td class="value" id="energy_wh">%(energy_wh)s Wh</td></tr>
            <tr><td class="label">Snitt Ström</td><td class="value" id="avg_current_a">%(avg_current_a)s A</td></tr>
            <tr><td class="label">Snitt Effekt</td><td class="value" id="avg_power_w">%(avg_power_w)s W</td></tr>
            <tr><td class="label">Under timmar</td><td class="value" id="elapsed_h">%(elapsed_h)s h</td></tr>

            <tr><td class="label">Dygn Ström</td><td class="value" id="daily_ah">%(daily_ah)s Ah</td></tr>
            <tr><td class="label">Dygn Effekt</td><td class="value" id="daily_wh">%(daily_wh)s Wh</td></tr>

            <tr><td class="label">Igår Datum</td><td class="value" id="yesterday_date">%(yesterday_date)s</td></tr>
            <tr><td class="label">Igår Ström</td><td class="value" id="yesterday_ah">%(yesterday_ah)s Ah</td></tr>
            <tr><td class="label">Igår Effekt</td><td class="value" id="yesterday_wh">%(yesterday_wh)s Wh</td></tr>

            <tr><td class="label">Minne ledigt/använt</td><td class="value" id="mem">%(mem_free_kb)s KB / %(mem_used_kb)s KB</td></tr>
        </tbody>
    </table>

    <h2>Tasks</h2>
    <table id="task-table">
        <colgroup>
            <col style="width:44%%" />
            <col style="width:16%%" />
            <col style="width:20%%" />
            <col style="width:20%%" />
        </colgroup>
        <thead><tr><th>Name</th><th>Status</th><th>Health (ms)</th><th>Uptime (days)</th></tr></thead>
        <tbody id="task-tbody">
            %(tasks_rows)s
        </tbody>
    </table>

    <div class="file-box">
        <h2>Daglig statistik</h2>
        <ul>%(files_items)s</ul>
    </div>

    <div id="modal" class="modal" onclick="hideModal()">
      <div class="modal-content" onclick="event.stopPropagation()">
        <div class="row">
          <h2 id="file_title" style="margin:0;font-size:1.1rem;"></h2>
          <div>
            <a id="downloadLink" href="#" style="margin-right:10px;">Ladda ner</a>
            <button class="file-close-btn" onclick="hideModal()">Stäng</button>
          </div>
        </div>
        <pre id="file_content">(laddar...)</pre>
      </div>
    </div>

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
    (function () {
      function byId(id) { return document.getElementById(id); }

      function valOrDash(v) {
        return (v === undefined || v === null) ? "--" : v;
      }

      function setText(id, v, suffix) {
        var el = byId(id);
        if (!el) return;
        v = valOrDash(v);
        el.textContent = suffix ? (v + suffix) : v;
      }

      function setJsStatus(txt) {
        var el = byId("js_status");
        if (el) el.textContent = "JS: " + txt;
      }

      window.onerror = function (msg, url, line, col, err) {
        setJsStatus("JS-fel: " + msg + " (" + line + ":" + col + ")");
        return false;
      };

      function httpGetJson(url, cb) {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", url, true);
        xhr.timeout = 4000;

        xhr.onreadystatechange = function () {
          if (xhr.readyState !== 4) return;

          if (xhr.status !== 200) {
            cb(null, "HTTP " + xhr.status);
            return;
          }

          try {
            cb(JSON.parse(xhr.responseText), null);
          } catch (e) {
            cb(null, "JSON parse error");
          }
        };

        xhr.onerror = function () { cb(null, "XHR onerror"); };
        xhr.ontimeout = function () { cb(null, "XHR timeout"); };

        xhr.send(null);
      }

      function updateDisplay(done) {
        httpGetJson("/display.json?ts=" + (new Date().getTime()), function (j, err) {
          if (err || !j) { done(err || "no data"); return; }
          var d = j.display || {};

          setText("start_time", j.start_time);
          setText("uptime", j.uptime);

          setText("time_str", d.time_str);

          setText("temperature", d.temperature, " °C");
          setText("temp_min", d.temp_min, " °C");
          setText("temp_max", d.temp_max, " °C");
          setText("temp_min_2h", d.temp_min_2h, " °C");
          setText("temp_max_2h", d.temp_max_2h, " °C");
          setText("comp_status", d.comp_status);

          setText("voltage", d.voltage, " V");
          setText("current", d.current, " A");
          setText("power", d.power, " W");

          setText("charge_ah", d.charge_ah, " Ah");
          setText("energy_wh", d.energy_wh, " Wh");
          setText("avg_current_a", d.avg_current_a, " A");
          setText("avg_power_w", d.avg_power_w, " W");
          setText("elapsed_h", d.elapsed_h, " h");

          setText("daily_ah", d.daily_ah, " Ah");
          setText("daily_wh", d.daily_wh, " Wh");

          setText("yesterday_date", d.yesterday_date);
          setText("yesterday_ah", d.yesterday_ah, " Ah");
          setText("yesterday_wh", d.yesterday_wh, " Wh");

          var memEl = byId("mem");
          if (memEl) {
            var free = valOrDash(d.mem_free_kb);
            var used = valOrDash(d.mem_used_kb);
            memEl.textContent = free + " KB / " + used + " KB";
          }

          done(null);
        });
      }

      function updateTasks(done) {
        httpGetJson("/tasks.json?ts=" + (new Date().getTime()), function (j, err) {
          if (err || !j) { done(err || "no data"); return; }

          var tasks = j.tasks || [];
          var tbody = byId("task-tbody");
          if (!tbody) { done("missing task-tbody"); return; }

          if (!tasks.length) {
            tbody.innerHTML = "<tr><td colspan='4'>Inga tasks</td></tr>";
            done(null);
            return;
          }

          var html = "";
          for (var i = 0; i < tasks.length; i++) {
            var t = tasks[i] || {};
            var name = (t.name === undefined || t.name === null) ? "" : t.name;
            var status = (t.status === undefined || t.status === null) ? "" : t.status;
            var stale = (t.stale_ms === undefined || t.stale_ms === null) ? "" : t.stale_ms;
            var up = (t.Upptid === undefined || t.Upptid === null) ? "" : t.Upptid;

            html += "<tr>"
                 +  "<td>" + name + "</td>"
                 +  "<td>" + status + "</td>"
                 +  "<td>" + stale + "</td>"
                 +  "<td>" + up + "</td>"
                 + "</tr>";
          }
          tbody.innerHTML = html;
          done(null);
        });
      }

      function tick() {
        updateDisplay(function (e) {
          if (e) { setJsStatus("display fel: " + e); return; }
        });

        updateTasks(function (e) {
          if (e) { setJsStatus("tasks fel: " + e); return; }
        });

        setJsStatus("uppdaterad " + (new Date()).toLocaleTimeString());
      }

      window.openFile = async function(name) {
        byId('file_title').textContent = name;
        byId('file_content').textContent = '(laddar...)';
        byId('downloadLink').href = '/download?name=' + encodeURIComponent(name);
        byId('modal').style.display = 'block';

        try {
          const r = await fetch('/file?name=' + encodeURIComponent(name));
          if(!r.ok) throw new Error('HTTP ' + r.status);
          byId('file_content').textContent = await r.text();
        } catch(e) {
          byId('file_content').textContent = 'Fel: ' + e;
        }
      };

      window.hideModal = function() {
        byId('modal').style.display = 'none';
      };

      setJsStatus("startar...");
      tick();
      setInterval(tick, 5000);
    })();
    </script>

</div>
</body>
</html>
"""
    html_content = html_template % values
    body_bytes = html_content.encode("utf-8")
    return _http_response_bytes(body_bytes, "text/html; charset=utf-8")


# -------------------------
# Routing / server
# -------------------------

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
                params[k] = url_decode(v)
            else:
                params[pair] = ""
        return path, params
    except:
        return "/", {}


async def handle_client(reader, writer, ota_callback=None):
    try:
        request_line = await reader.readline()
        if not request_line:
            await writer.aclose()
            return

        request_str = request_line.decode("utf-8").strip()
        path, params = parse_path_and_query(request_str)
        pwd = params.get("pwd", "")

        while True:
            header = await reader.readline()
            if not header or header == b"\r\n":
                break

        if path == "/status.json":
            response_bytes = get_status_json_bytes()

        elif path == "/display.json":
            response_bytes = get_display_json_bytes()

        elif path == "/tasks.json":
            response_bytes = get_tasks_json_bytes()

        elif path == "/file":
            name = params.get("name", "")
            try:
                full = safe_join_data(name)
                with open(full, "rb") as f:
                    data = f.read()
                response_bytes = _http_response_bytes_extra(
                    data,
                    "text/plain; charset=utf-8",
                    status_line="200 OK"
                )
            except Exception as e:
                msg = ("Kunde inte läsa fil: %s\n%s" % (name, e)).encode("utf-8")
                response_bytes = _http_response_bytes_extra(
                    msg,
                    "text/plain; charset=utf-8",
                    status_line="404 Not Found"
                )

        elif path == "/download":
            name = params.get("name", "")
            try:
                full = safe_join_data(name)
                with open(full, "rb") as f:
                    data = f.read()
                extra = ['Content-Disposition: attachment; filename="%s"' % name]
                response_bytes = _http_response_bytes_extra(
                    data,
                    "application/octet-stream",
                    status_line="200 OK",
                    extra_headers=extra
                )
            except Exception as e:
                msg = ("Kunde inte ladda ner: %s\n%s" % (name, e)).encode("utf-8")
                response_bytes = _http_response_bytes_extra(
                    msg,
                    "text/plain; charset=utf-8",
                    status_line="404 Not Found"
                )

        elif path == "/ota":
            if pwd != secret.WEB_PASSWORD:
                response_bytes = _http_error_html(403, "<h1>Fel lösenord</h1><p>OTA avbruten.</p>")
                await _write_all(writer, response_bytes)
                await writer.aclose()
                return

            response_bytes = _http_response_bytes(b"OTA startad...", "text/plain; charset=utf-8")
            await _write_all(writer, response_bytes)
            await writer.aclose()
            await asyncio.sleep(1)
            await ota.ota_check()
            return

        elif path == "/reboot":
            if pwd != secret.WEB_PASSWORD:
                response_bytes = _http_error_html(403, "<h1>Fel lösenord</h1><p>Omstart avbruten.</p>")
                await _write_all(writer, response_bytes)
                await writer.aclose()
                return

            response_bytes = _http_response_bytes(b"Startar om...", "text/plain; charset=utf-8")
            await _write_all(writer, response_bytes)
            await writer.aclose()
            await task_handler.graceful_restart()
            return

        else:
            response_bytes = get_status_html_bytes()

        await _write_all(writer, response_bytes)
        await writer.aclose()
        gc.collect()

    except Exception as e:
        print("Fel i hantering av klient:", e)
        try:
            await writer.aclose()
        except:
            pass
        gc.collect()


async def start_web_server(ota_callback=None, host="0.0.0.0", port=80):
    try:
        os.mkdir(DATA_DIR)
    except OSError:
        pass

    print("🌐 Startar asynkron webbserver på {}:{}".format(host, port))
    await asyncio.start_server(lambda r, w: handle_client(r, w, ota_callback), host, port)

    while True:
        task_handler.feed_health("web_server.start_web_server")
        await asyncio.sleep(5)
