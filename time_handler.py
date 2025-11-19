import gc
import ntptime
import time
import uasyncio as asyncio
import task_handler

start_time = time.ticks_ms()

def get_uptime():
    return "{:.2f} dygn".format(time.ticks_diff(time.ticks_ms(), start_time) / (1000 * 86400))


# ------------------------------
# Svensk tidszonslogik (CET/CEST)
# ------------------------------
def is_summer_time(year, month, day):
    """Returnerar True om det är sommartid (CEST), annars False."""
    # Hitta sista söndag i mars
    last_sunday_march = max(
        day for day in range(31, 24, -1)
        if time.localtime(time.mktime((year, 3, day, 2, 0, 0, 0, 0)))[6] == 6
    )
    # Hitta sista söndag i oktober
    last_sunday_october = max(
        day for day in range(31, 24, -1)
        if time.localtime(time.mktime((year, 10, day, 2, 0, 0, 0, 0)))[6] == 6
    )
    if (month > 3 and month < 10) or \
       (month == 3 and day >= last_sunday_march) or \
       (month == 10 and day < last_sunday_october):
        gc.collect()
        return True
    gc.collect()
    return False

def get_swedish_time_tuple():
    """Returnerar en lokal svensk tidstuple (år, mån, dag, tim, min, sek)."""
    utc = time.localtime()
    offset = 2 if is_summer_time(*utc[:3]) else 1
    t = time.localtime(time.mktime(utc) + offset * 3600)
    gc.collect()
    return t

async def sync_time(retries=5, interval=5):
    for attempt in range(1, retries + 1):
        try:
            print(f"🌐 Synkar tid (försök {attempt}/{retries})...")
            ntptime.settime()  # ställer in UTC
            t = get_swedish_time_tuple()
            print("✅ Svensk tid:", "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
            gc.collect()
            return True
        except Exception as e:
            print("❌ Misslyckades:", e)
            await asyncio.sleep(interval)
    print("⚠️ Kunde inte synka tiden efter flera försök.")
    gc.collect()
    return False

async def periodic_time_sync(hours=6):
    """Synka tid var X timmar."""
    
    print("Starta automatisk uppdatering av tiden.")

    while True:
#        print("Väntar sekunder :", hours * 3600, "skunder innan nästa koll")

        task_handler.feed_health("tiden.periodic_time_sync")
        gc.collect()
        await asyncio.sleep(hours * 3600)
        task_handler.feed_health("tiden.periodic_time_sync")
        gc.collect()
        await sync_time()

