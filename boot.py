import machine
import network
import secret
import time
import os

print("boot.py körs")
time.sleep(1)

def wifi_connect(ssid, password, timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
        start = time.time()
        while not wlan.isconnected():
            if time.time() - start > timeout:
                return False
            time.sleep(0.5)
    return wlan.ifconfig()

try:
    ifconfig = wifi_connect(secret.WIFI_SSID, secret.WIFI_PASSWORD)
    print("WiFi ansluten:", ifconfig)
    
    if "app_main_old.py" in os.listdir() and "app_main.py" in os.listdir():
        try:
            with open("app_main.py") as f:
                compile(f.read(), "app_main.py", "exec")
            print("Fungerande app_main.py!")
            if "app_main_old.py" in os.listdir():
                os.remove("app_main_old.py")

        except Exception as e2:
            print("Fel i app_main.py – gör rollback")
            os.remove("app_main.py")
            os.rename("app_main_old.py", "app_main.py")
            time.sleep(1)
#            machine.reset()
            # Trigger watchdog reset som ofta är "hårdare"
            wdt = machine.WDT(timeout=500)
            while True:
                pass  # Låt WDT trigga omstart
    
except Exception as e:
    print("WiFi-anslutning misslyckades:", e)
