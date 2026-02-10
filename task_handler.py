import network
import uasyncio as asyncio
import machine
import gc
import time

import app_main
import time_handler
import web_server

import secret

# Håll koll på tasks
TASKS = {}  # {name: task}
HEALTH = {}  # {name: senaste tidpunkt}
HEALTH_START = {}  # {name: startad}
WATCHDOG_LAST_FEED = time.ticks_ms()
WATCHDOG_TIMEOUT_MS = 30000  # 30 sek standard

restarted_nr = 0

wlan = network.WLAN(network.STA_IF)
wlan.active(True)


async def graceful_restart():
    global TASKS
    global HEALTH
    global HEALTH_START
    
    with open(f"/log/{app_main.current_day_key}_graceful_restart.txt", "w") as f:
        f.write(f"{app_main.current_day_key}\n")
        f.write(f"graceful_restart\n")
    
    """Stoppa alla tasks och starta om maskinen."""
    print("🧹 Stoppar alla tasks...")
    for name, task in list(TASKS.items()):
#    for task in TASKS:
        task.cancel()
        await asyncio.sleep(0)  # låt tasks rensa upp
    await asyncio.sleep(0)  # låt tasks rensa upp

    print("🔌 Kopplar ner WiFi...")
    wlan.disconnect()
    wlan.active(False)

    gc.collect()

    print("♻️ Startar om maskinen...")
    await asyncio.sleep(1)
    machine.reset()


def register_task(task, name):
    global TASKS
    global HEALTH
    global HEALTH_START
    """Registrera nya tasks så att de kan stoppas vid restart."""
    now = time.ticks_ms()
    TASKS[name] = task
    HEALTH[name] = now            # senaste health-feed
#    HEALTH_START[name] = time.time() # starttid i s    
    if time_handler.start_time_s != 0:
        HEALTH_START[name] = time.time()
    else:
        HEALTH_START[name] = 0
    gc.collect()


def create_managed_task(coro, name = None):
    task = asyncio.create_task(coro)
    register_task(task, name)
    gc.collect()
    return task


# === Hälsokontroll ===
def feed_health(task_name):
    global HEALTH
    """Mata health för en task."""
    HEALTH[task_name] = time.ticks_ms()
    gc.collect()


async def monitor_health(interval=10, max_stale_time=120000):
    global restarted_nr
    global TASKS
    global HEALTH
    global HEALTH_START
    """Kontrollerar om tasks inte matat health på länge."""
    while True:
        now = time.ticks_ms()
        for name, last in HEALTH.items():
            delta = time.ticks_diff(now, last)
            
            if name == "task_handler.monitor_tasks" and delta > max_stale_time:
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), restarting task...")

                task = TASKS.get(name)
                if task:
                    task.cancel()
                    await asyncio.sleep(0)  # låt tasks rensa upp

                del TASKS[name]
                del HEALTH[name]
                del HEALTH_START[name]
                gc.collect()
                
                create_managed_task(monitor_tasks(interval=15), name="task_handler.monitor_tasks")
                restarted_nr += 1
                
                with open(f"/log/{app_main.current_day_key}_{name}.txt", "w") as f:
                    f.write(f"{app_main.current_day_key}\n")
                    f.write(f"{name}\n")


            elif name != "time_handler.periodic_time_sync" and delta > max_stale_time:
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), killing task...")
                task = TASKS.get(name)
                if task:
                    task.cancel()

                    
            elif name == "time_handler.periodic_time_sync" and delta > (secret.TIME_SYNC_REPEAT * 60 * 60 * 1000):
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), Killing task...")
                task = TASKS.get(name)
                if task:
                    task.cancel()

        feed_health("task_handler.monitor_health")
        gc.collect()
        await asyncio.sleep(interval)


# === Watchdog ===
def feed_watchdog():
    global WATCHDOG_LAST_FEED
    WATCHDOG_LAST_FEED = time.ticks_ms()
    gc.collect()

async def monitor_watchdog(interval=5):
    global WATCHDOG_LAST_FEED
    """Kontrollerar programvaru-watchdog."""
    while True:
        delta = time.ticks_diff(time.ticks_ms(), WATCHDOG_LAST_FEED)
        if delta > WATCHDOG_TIMEOUT_MS:
            print(f"⚠️ Watchdog timeout ({delta} ms) - startar om maskinen!")
            await graceful_restart()
        feed_health("task_handler.monitor_watchdog")
        gc.collect()
        await asyncio.sleep(interval)



# === Task-övervakning ===
async def monitor_tasks(interval=15):
    global restarted_nr
    global TASKS
    global HEALTH
    global HEALTH_START
    """Övervakar att tasks fortfarande körs och startar om om de kraschar."""
    while True:
        for name, task in list(TASKS.items()):
            if task.done():
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Task '{name}' är klar/kraschat - tas bort från TASKS, Startar upp den igen!")
                del TASKS[name]
                del HEALTH[name]
                del HEALTH_START[name]
                gc.collect()
                
                if name == "app_main.main":
                    create_managed_task(app_main.main(), "app_main.main")
                    restarted_nr += 1
                    
                elif name == "app_main.monitor_wifi":
                    create_managed_task(app_main.monitor_wifi(), "app_main.monitor_wifi")
                    restarted_nr += 1

                elif name == "app_main.read_temperature":
                    create_managed_task(app_main.read_temperature(), "app_main.read_temperature")
                    restarted_nr += 1

                elif name == "app_main.update_display":
                    create_managed_task(app_main.update_display(), "app_main.update_display")
                    restarted_nr += 1

                elif name == "task_handler.monitor_health":
                    create_managed_task(monitor_health(interval=10, max_stale_time=60000), "task_handler.monitor_health")
                    restarted_nr += 1

                elif name == "task_handler.monitor_watchdog":
                    create_managed_task(task_handler.monitor_watchdog(interval=5), name="task_handler.monitor_watchdog")
                    restarted_nr += 1

                elif name == "time_handler.periodic_time_sync":
                    create_managed_task(time_handler.periodic_time_sync(hours=secret.TIME_SYNC_REPEAT), "time_handler.periodic_time_sync")
                    restarted_nr += 1
                    
                elif name == "web_server.start_web_server":
                    create_managed_task(web_server.start_web_server(), "web_server.start_web_server")
                    restarted_nr += 1

                elif name == "web_server_files.start":
                    create_managed_task(web_server_files.start(host="0.0.0.0", port=81), "web_server_files.start")
                    restarted_nr += 1

                with open(f"/log/{app_main.current_day_key}_{name}.txt", "w") as f:
                    f.write(f"{app_main.current_day_key}\n")
                    f.write(f"{name}\n")

            else:
                if HEALTH_START[name] == 0 and time_handler.start_time_s != 0:
                    HEALTH_START[name] = time.time()

        feed_health("task_handler.monitor_tasks")
        gc.collect()
        await asyncio.sleep(interval)

def running_tasks():
    running = 0
    total = 0
    for _, task in list(TASKS.items()):
        if not task.done():
            running += 1
        total += 1
    gc.collect()
    return f"{running} av {total}"
