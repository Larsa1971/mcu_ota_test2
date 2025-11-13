import network
import uasyncio as asyncio
import machine
import gc
import time

import app_main
import tiden
import web_server

import secret

# Håll koll på tasks
TASKS = {}  # {name: task}
HEALTH = {}  # {name: senaste tidpunkt}
WATCHDOG_LAST_FEED = time.ticks_ms()
WATCHDOG_TIMEOUT_MS = 30000  # 30 sek standard


wlan = network.WLAN(network.STA_IF)
wlan.active(True)

async def graceful_restart():
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
    """Registrera nya tasks så att de kan stoppas vid restart."""
    TASKS[name] = task
    HEALTH[name] = task

def create_managed_task(coro, name = None):
    task = asyncio.create_task(coro)
    register_task(task, name)
    return task

# === Hälsokontroll ===
def feed_health(task_name):
    """Mata health för en task."""
    HEALTH[task_name] = time.ticks_ms()





async def monitor_health(interval=10, max_stale_time=120000):
    """Kontrollerar om tasks inte matat health på länge."""
    while True:
        now = time.ticks_ms()
        for name, last in HEALTH.items():
            delta = time.ticks_diff(now, last)
            
            if name == "task_handler.monitor_tasks" and delta > max_stale_time:
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), restarting task...")

                task = HEALTH.get(name)
                if task:
                    task.cancel()
                    await asyncio.sleep(0)  # låt tasks rensa upp

                del TASKS[name]
                del HEALTH[name]
                gc.collect()
                
                create_managed_task(monitor_tasks(interval=15), name="task_handler.monitor_tasks")


            elif name != "tiden.periodic_time_sync" and delta > max_stale_time:
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), killing task...")
                task = TASKS.get(name)
                if task:
                    task.cancel()

                    
            elif name == "tiden.periodic_time_sync" and delta > (secret.TIME_SYNC_REPEAT * 60 * 60 * 1000):
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Health stale för task '{name}' ({delta} ms), Killing task...")
                task = TASKS.get(name)
                if task:
                    task.cancel()

        feed_health("task_handler.monitor_health")
        await asyncio.sleep(interval)


# === Watchdog ===
def feed_watchdog():
    global WATCHDOG_LAST_FEED
    WATCHDOG_LAST_FEED = time.ticks_ms()

async def watchdog_monitor(interval=5):
    """Kontrollerar programvaru-watchdog."""
    while True:
        delta = time.ticks_diff(time.ticks_ms(), WATCHDOG_LAST_FEED)
        if delta > WATCHDOG_TIMEOUT_MS:
            print(f"⚠️ Watchdog timeout ({delta} ms) - startar om maskinen!")
            await graceful_restart()
        feed_health("task_handler.watchdog_monitor")
        await asyncio.sleep(interval)



# === Task-övervakning ===
async def monitor_tasks(interval=15):
    """Övervakar att tasks fortfarande körs och startar om om de kraschar."""
    while True:
#        print("")
        for name, task in list(TASKS.items()):
            if task.done():
                print(f"⚠️ [{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] Task '{name}' är klar/kraschat - tas bort från TASKS, Startar upp den igen!")
                del TASKS[name]
                del HEALTH[name]
                gc.collect()
                
                if name == "app_main.monitor_wifi":
                    create_managed_task(app_main.monitor_wifi(), "app_main.monitor_wifi")

                elif name == "web_server.start_web_server":
                    create_managed_task(web_server.start_web_server(), "web_server.start_web_server")
                    
                elif name == "tiden.periodic_time_sync":
                    create_managed_task(tiden.periodic_time_sync(hours=secret.TIME_SYNC_REPEAT), "tiden.periodic_time_sync")
                    
                elif name == "app_main.update_display":
                    create_managed_task(app_main.update_display(), "app_main.update_display")

                elif name == "app_main.read_temperature":
                    create_managed_task(app_main.read_temperature(), "app_main.read_temperature")

                elif name == "task_handler.monitor_health":
                    create_managed_task(monitor_health(interval=10, max_stale_time=60000), "task_handler.monitor_health")



#            print("Task ", name, "lever")    
                
                
        feed_health("task_handler.monitor_tasks")                
        await asyncio.sleep(interval)


