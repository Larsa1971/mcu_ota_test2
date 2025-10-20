import network
import ntptime
import secret
import time
import tiden
import ota
import uasyncio as asyncio
import web_server
import task_handler
import app_main


print("main.py körs")
time.sleep(1)

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

async def wifi_connect(ssid, password, timeout=20):
    if not wlan.isconnected():
        print("Ansluter till WiFi...")
        wlan.connect(ssid, password)
        for _ in range(timeout):
            if wlan.isconnected():
                break
            await asyncio.sleep(1)
        if wlan.isconnected():
            print("✅ Ansluten till WiFi!")
            print("IP-adress:", wlan.ifconfig()[0])
            await sync_time()
        else:
            print("❌ Kunde inte ansluta till WiFi.")
    else:
        print("Redan ansluten:", wlan.ifconfig()[0])
        await sync_time()

async def monitor_wifi():
    """Kontrollerar regelbundet WiFi-status och återansluter vid behov."""
    while True:
        if not wlan.isconnected():
            print("⚠️  WiFi tappat! Försöker återansluta...")
            wlan.disconnect()
            await asyncio.sleep(1)
            await wifi_connect(secret.WIFI_SSID, secret.WIFI_PASSWORD)
        else:
            print(f"[{time.localtime()[3]:02d}:{time.localtime()[4]:02d}:{time.localtime()[5]:02d}] WiFi OK")
        print("Väntar", secret.CHECK_INTERVAL_WIFI, "sekunder innan nästa wifi koll")
        await asyncio.sleep(secret.CHECK_INTERVAL_WIFI)

async def sync_time(retries=5, interval=5):
    for attempt in range(1, retries + 1):
        try:
            print(f"🌐 Synkar tid (försök {attempt}/{retries})...")
            ntptime.settime()  # ställer in UTC
            t = tiden.get_swedish_time_tuple()
            print("✅ Svensk tid:", "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
            return True
        except Exception as e:
            print("❌ Misslyckades:", e)
            await asyncio.sleep(interval)
    print("⚠️ Kunde inte synka tiden efter flera försök.")
    return False

async def periodic_time_sync(hours=6):
    """Synka tid var X timmar."""
    while True:
        print("Starta automatisk uppdatering av tiden.")
        print("Väntar sekunder :", hours * 3600, "skunder innan nästa koll")
        await asyncio.sleep(hours * 3600)
        await sync_time()




async def main():
    # Återställer föregående om fel.
    await ota.rollback_if_broken()
    
    # kopplar upp wifi
    await wifi_connect(secret.WIFI_SSID, secret.WIFI_PASSWORD)

    task_handler.create_managed_task(monitor_wifi())
    task_handler.create_managed_task(ota.ota_worker())
    task_handler.create_managed_task(web_server.start_web_server())
    task_handler.create_managed_task(periodic_time_sync(hours=secret.TIME_SYNC_REPEAT))
    task_handler.create_managed_task(app_main.main())


    while True:
        await asyncio.sleep(3600)

try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
    
