import network
import uasyncio as asyncio
import machine

# Håll koll på tasks
TASKS = []
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

async def graceful_restart():
    """Stoppa alla tasks och starta om maskinen."""
    print("🧹 Stoppar alla tasks...")
    for task in TASKS:
        task.cancel()
    await asyncio.sleep(0)  # låt tasks rensa upp

    print("🔌 Kopplar ner WiFi...")
    wlan.disconnect()
    wlan.active(False)

    print("♻️ Startar om maskinen...")
    await asyncio.sleep(1)
    machine.reset()

def register_task(task):
    """Registrera nya tasks så att de kan stoppas vid restart."""
    TASKS.append(task)

def create_managed_task(coro):
    task = asyncio.create_task(coro)
    register_task(task)
    return task

