# app_main.py
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY_2
import uasyncio as asyncio
import gc
import time
import network
from machine import Pin, I2C, PWM
from collections import deque
import onewire, ds18x20
import secret # inställningar
import task_handler
import time_handler
import web_server
import ota
import uping

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# === Temperaturgränser ===
TEMP_OFF_THRESHOLD_9 = secret.LOW_TEMP_MIN
TEMP_ON_THRESHOLD_9 = secret.LOW_TEMP_MAX
TEMP_OFF_THRESHOLD_10 = secret.HIGH_TEMP_MIN
TEMP_ON_THRESHOLD_10 = secret.HIGH_TEMP_MAX
TEMP_ALARM_THRESHOLD = secret.LARM_TEMP

# === Display setup ===
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY_2, rotate=0)
WHITE = display.create_pen(255, 255, 255)
BLACK = display.create_pen(0, 0, 0)
RED = display.create_pen(255, 0, 0)
GREEN = display.create_pen(0, 255, 0)
BLUE = display.create_pen(0, 0, 255)
LIGHTBLUE = display.create_pen(173, 216, 230)
LIGHTGREEN = display.create_pen(144, 238, 144)

# === DS18B20 sensor på GPIO 11 ===
ow_pin = Pin(11)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ow_pin))
roms = ds_sensor.scan()
temperature_c = None
temp_history = []
temp_24h_min = None
temp_24h_max = None

# === GPIO-styrningar ===
control_pin_9 = Pin(9, Pin.OUT)
control_pin_10 = Pin(10, Pin.OUT)

backlight_pin_20 = Pin(20, Pin.OUT) # Tända och släcka skärmen
backlight_pin_20.value(1)

led_red = PWM(Pin(6)) # Tända och släcka skärmen
led_red.freq(1000)
led_red.duty_u16(65535)
led_green = PWM(Pin(7)) # Tända och släcka skärmen
led_green.freq(1000)
led_green.duty_u16(65535)
led_blue = PWM(Pin(8)) # Tända och släcka skärmen
led_blue.freq(1000)
led_blue.duty_u16(65535)


trigger_pin_12 = Pin(12, Pin.IN, Pin.PULL_UP)  # Pull-up, triggas vid låg (0)
trigger_pin_13 = Pin(13, Pin.IN, Pin.PULL_UP)
trigger_pin_14 = Pin(14, Pin.IN, Pin.PULL_UP)
trigger_pin_15 = Pin(15, Pin.IN, Pin.PULL_UP)


control_output_state_9 = False
control_output_state_10 = False
use_gpio_10 = False
alarm_visible = True

DISPLAY_DATA = {
    "temperature": None,
    "temp_min": None,
    "temp_max": None,
    "temp_min_2h": None,
    "temp_max_2h": None,
    "comp_status": "Okänd",
    "voltage": None,
    "current": None,
    "power": None,
    "mem_free_kb": None,
    "mem_used_kb": None,
    "time_str": "",
}



# === INA260 setup (I2C på GP4/GP5) ===
i2c = I2C(1, scl=Pin(27), sda=Pin(26), freq=400000)
INA260_ADDR = 0x40

def read_ina260_register(reg):
    data = i2c.readfrom_mem(INA260_ADDR, reg, 2)
    return (data[0] << 8) | data[1]

def read_voltage():
    raw = read_ina260_register(0x02)
    return raw * 1.25 / 1000.0

def read_current():
    raw = read_ina260_register(0x01)
    return raw * 1.25 / 1000.0

def read_power():
    raw = read_ina260_register(0x03)
    return raw * 10 / 1000.0


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
            await time_handler.sync_time()
        else:
            print("❌ Kunde inte ansluta till WiFi.")
    else:
        print("Redan ansluten:", wlan.ifconfig()[0])
        await time_handler.sync_time()

async def monitor_wifi():
    """Kontrollerar regelbundet WiFi-status och återansluter vid behov."""
    while True:
        if not wlan.isconnected():
            print("⚠️  WiFi tappat! Försöker återansluta...")
            wlan.disconnect()
            await asyncio.sleep(1)
            await wifi_connect(secret.WIFI_SSID, secret.WIFI_PASSWORD)
            
        task_handler.feed_health("app_main.monitor_wifi")
        gc.collect()
        await asyncio.sleep(secret.CHECK_INTERVAL_WIFI)


async def update_temp_history(current_temp):
    global temp_history, temp_24h_min, temp_24h_max, led_green

    temp_history.append(current_temp)
    if len(temp_history) > secret.MAXLEN:
        temp_history.pop(0)
        gc.collect()
        led_green.duty_u16(20000)

# Beräkna min och max om listan inte är tom
    if temp_history != None:
        temp_24h_min = min(temp_history)
        temp_24h_max = max(temp_history)
        

# === Display-uppdatering ===
async def update_display():
    global alarm_visible, use_gpio_10, control_output_state_9, control_output_state_10, trigger_pin_12, trigger_pin_13, trigger_pin_14, trigger_pin_15, backlight_pin_20
    global temperature_c, temp_24h_min, temp_24h_max, led_red, led_green, led_blue, DISPLAY_DATA
    display.set_font("bitmap8")

    temperature_c = 0
    min_th = 0
    max_th = 0
    temp_24h_min = 0
    temp_24h_max = 0
    comp_str = "Okänd"
    voltage = 0
    current = 0
    power = 0
    mem_free = 0
    mem_alloc = 0
    time_str = ""
    
    local_ver = None
    github_ver = None
        
    while True:

        if trigger_pin_14.value() == 0 and backlight_pin_20.value() == 1:
            print("\n\n\nTrigger GPIO14 och backlight tänd, släcket\n\n\n")
            backlight_pin_20.value(0)
            await asyncio.sleep(0.5)
        elif trigger_pin_14.value() == 0 and backlight_pin_20.value() == 0:
            print("\n\n\nTrigger GPIO14 och backlight släckt, tänder\n\n\n")
            backlight_pin_20.value(1)
            await asyncio.sleep(0.5)

        display.set_pen(BLACK)
        display.clear()

        # Tid
        t = time_handler.get_swedish_time_tuple()
        time_str = ("{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
        display.set_pen(WHITE)
        x = (320 - display.measure_text(time_str, scale=3)) // 2
        display.text(time_str, x, 1, scale=3)
        

        # Temperatur
        if temperature_c is not None:
            min_th = TEMP_OFF_THRESHOLD_10 if use_gpio_10 else TEMP_OFF_THRESHOLD_9
            max_th = TEMP_ON_THRESHOLD_10 if use_gpio_10 else TEMP_ON_THRESHOLD_9

            if temperature_c <= min_th:
                temp_pen = LIGHTBLUE
            elif temperature_c >= max_th:
                temp_pen = RED
            else:
                temp_pen = GREEN

            temp_str = "Temp: {:.2f}°C".format(temperature_c)
            x = (320 - display.measure_text(temp_str, scale=3)) // 2
            display.set_pen(temp_pen)
            display.text(temp_str, x, 30, scale=3)

            # Kompressorstatus
            comp_str = (
                "Komp: High" if use_gpio_10 and control_output_state_10 else
                "Komp: Off!!" if use_gpio_10 else
                "Komp: Low" if control_output_state_9 else
                "Komp: Off"
            )
            x = (320 - display.measure_text(comp_str, scale=3)) // 2
            
            if comp_str == "Komp: High":
                display.set_pen(BLUE)
                led_red.duty_u16(20000)
                led_green.duty_u16(65535)
                led_blue.duty_u16(65535)
            elif comp_str == "Komp: Low":
                display.set_pen(LIGHTBLUE)
                led_red.duty_u16(65535)
                led_green.duty_u16(65535)
                led_blue.duty_u16(20000)
            elif comp_str == "Komp: Off":
                display.set_pen(LIGHTGREEN)
                led_red.duty_u16(65535)
                led_green.duty_u16(65535)
                led_blue.duty_u16(65535)

            display.text(comp_str, x, 60, scale=3)

            if trigger_pin_15.value() == 1: # Visa status knappen
                # Styr Min
                minmax_str = f"Styr Min: {min_th:.2f}°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 90, scale=2)
                
                # Styr Max
                minmax_str = f"Styr Max: {max_th:.2f}°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 110, scale=2)

                # 24h Min
                if temp_24h_min is not None:
                    minmax_str = f"2h Min: {temp_24h_min:.2f}°C"
                else:
                    minmax_str = "2h Min: --°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 130, scale=2)
                
                # 24h Max
                if temp_24h_max is not None:
                    minmax_str = f"2h Max: {temp_24h_max:.2f}°C"
                else:
                    minmax_str = "2h Max: --°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 150, scale=2)
                
                if local_ver != None:
                    local_ver = None

                if github_ver != None:
                    github_ver = None

            else: #Visar status i stället

                # Uptiden
                uptime_str = web_server.get_uptime() + " " + wlan.ifconfig()[0]
                x = (320 - display.measure_text(uptime_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(uptime_str, x, 90, scale=2)
                
                # Tasks
                tasks_str = f"{task_handler.running_tasks()} körs, omstart {task_handler.restarted_nr}"
                x = (320 - display.measure_text(tasks_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(tasks_str, x, 110, scale=2)

                # Local ver
                if local_ver == None:
                    local_ver = "Local : " + ota.get_local_version()
                x = (320 - display.measure_text(local_ver, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(local_ver, x, 130, scale=2)
                
                # Git ver
                if github_ver == None:
                    if uping.ping("1.1.1.1"):
                        github_ver = "Github : " + ota.get_remote_version_status()
                    else:
                        github_ver = "Github : inget internet!!!"
                x = (320 - display.measure_text(github_ver, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(github_ver, x, 150, scale=2)

            # Larm 
            if temperature_c >= TEMP_ALARM_THRESHOLD and alarm_visible:
                alarm_str = f"LARM TEMP OVER : {TEMP_ALARM_THRESHOLD:.0f}°C"
                x = (320 - display.measure_text(alarm_str, scale=2)) // 2
                display.set_pen(RED)
                display.text(alarm_str, x, 174, scale=2)

        # INA260
        try:
            voltage = read_voltage()
            current = read_current()
            power = read_power()
            ina_text = f"V:{voltage:.2f}V I:{current:.2f}A P:{power:.2f}W"
        except Exception as e:
            print("INA260-fel:", e)
            ina_text = "INA260 error"
        x = (320 - display.measure_text(ina_text, scale=2)) // 2
        display.set_pen(WHITE)
        display.text(ina_text, x, 200, scale=2)

        # Minnesinfo
        gc.collect()
        mem_free = gc.mem_free()
        mem_alloc = gc.mem_alloc()
        mem_text = f"Free: {mem_free//1024}KB Used: {mem_alloc//1024}KB"
        x = (320 - display.measure_text(mem_text, scale=2)) // 2
        display.set_pen(WHITE)
        display.text(mem_text, x, 225, scale=2)

        # Knapparna
        display.set_pen(WHITE)
        display.text("Kyla", 0, 55, scale=2)
        display.text("Lyse", 280, 55, scale=2)
        display.text("Uppd", 0, 182, scale=2)
        display.text("Stat", 280, 182, scale=2)

        display.update()
        alarm_visible = not alarm_visible

        DISPLAY_DATA.update({
            "temperature": temperature_c,
            "temp_min": min_th,
            "temp_max": max_th,
            "temp_min_2h": temp_24h_min,
            "temp_max_2h": temp_24h_max,
            "comp_status": comp_str,
            "voltage": voltage,
            "current": current,
            "power": power,
            "mem_free_kb": mem_free // 1024,
            "mem_used_kb": mem_alloc // 1024,
            "time_str": time_str,
        })
        
        task_handler.feed_health("app_main.update_display")
        gc.collect()
        await asyncio.sleep(0.2)

# === Temperaturmätning (endast trigger 12) ===
async def read_temperature():
    global temperature_c, control_output_state_9, control_output_state_10, use_gpio_10, trigger_pin_12, trigger_pin_13, trigger_pin_14, trigger_pin_15, backlight_pin_20, temp_24h_min, temp_24h_max

    # Init GPIO vid start
    control_pin_9.value(0)
    control_pin_10.value(0)
    control_output_state_9 = False
    control_output_state_10 = False

    # Initial temperaturmätning
    if roms:
        ds_sensor.convert_temp()
        await asyncio.sleep(0.75)
        try:
            temperature_c = ds_sensor.read_temp(roms[0])
            await update_temp_history(temperature_c)
            print("Init temp: {:.2f}°C".format(temperature_c))
        except Exception as e:
            print("Init-temp fel:", e)

    while True:
        try:
            ds_sensor.convert_temp()
            await asyncio.sleep(0.75)
            if roms:
                temperature_c = ds_sensor.read_temp(roms[0])
                await update_temp_history(temperature_c)
                
                if trigger_pin_12.value() == 0 and control_output_state_9:
                    print("\n\n\nTrigger GPIO12 och GPIO9 är ON ⇒ byter till GPIO10\n\n\n")
                    control_pin_9.value(0)
                    control_output_state_9 = False
                    use_gpio_10 = True

                if use_gpio_10:
                    if temperature_c >= TEMP_ON_THRESHOLD_10 and not control_output_state_10:
                        control_pin_10.value(1)
                        control_output_state_10 = True
                    elif temperature_c <= TEMP_OFF_THRESHOLD_10 and control_output_state_10:
                        control_pin_10.value(0)
                        control_output_state_10 = False

                    if temperature_c <= TEMP_OFF_THRESHOLD_10:
                        use_gpio_10 = False
                        print("Återgår till GPIO9")
                        if temperature_c >= TEMP_ON_THRESHOLD_9 and not control_output_state_9:
                            control_pin_9.value(1)
                            control_output_state_9 = True
                        elif temperature_c <= TEMP_OFF_THRESHOLD_9 and control_output_state_9:
                            control_pin_9.value(0)
                            control_output_state_9 = False
                else:
                    if temperature_c >= TEMP_ON_THRESHOLD_9 and not control_output_state_9:
                        control_pin_9.value(1)
                        control_output_state_9 = True
                    elif temperature_c <= TEMP_OFF_THRESHOLD_9 and control_output_state_9:
                        control_pin_9.value(0)
                        control_output_state_9 = False

        except Exception as e:
            print("Temp‑fel:", e)
            
        task_handler.feed_health("app_main.read_temperature")
        gc.collect()
        await asyncio.sleep(1.25)

# === Main ===
async def main():
    task_handler.create_managed_task(read_temperature(), "app_main.read_temperature")
    task_handler.create_managed_task(update_display(), "app_main.update_display")
    

    while True:
        task_handler.feed_health("app_main.main")
        gc.collect()
        await asyncio.sleep(5)
