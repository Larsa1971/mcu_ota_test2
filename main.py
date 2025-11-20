import secret
import time
import time_handler
import gc
import ota
import uasyncio as asyncio
import web_server
import task_handler
import app_main

print("main.py körs")
time.sleep(1)
gc.collect()
gc.enable()


async def main():
    # Återställer föregående om fel.
    await ota.rollback_if_broken()
    
    # kopplar upp wifi
    await app_main.wifi_connect(secret.WIFI_SSID, secret.WIFI_PASSWORD)

    # ota check vid start
    await ota.ota_check()
    
    task_handler.create_managed_task(app_main.main(), "app_main.main")
    task_handler.create_managed_task(app_main.monitor_wifi(), "app_main.monitor_wifi")
    task_handler.create_managed_task(task_handler.monitor_health(interval=10, max_stale_time=120000), name="task_handler.monitor_health")
    task_handler.create_managed_task(task_handler.monitor_tasks(interval=15), name="task_handler.monitor_tasks")
    task_handler.create_managed_task(task_handler.monitor_watchdog(interval=5), name="task_handler.monitor_watchdog")
    task_handler.create_managed_task(time_handler.periodic_time_sync(hours=secret.TIME_SYNC_REPEAT), "time_handler.periodic_time_sync")
    task_handler.create_managed_task(web_server.start_web_server(), "web_server.start_web_server")

    while True:
        task_handler.feed_watchdog()
        gc.collect()
        await asyncio.sleep(5)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
