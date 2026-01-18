# app_main.py
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY_2
import uasyncio as asyncio
import gc
import time
import network
from machine import Pin, I2C, PWM
from collections import deque
import onewire, ds18x20
import secret  # inställningar
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

backlight_pin_20 = Pin(20, Pin.OUT)  # Tända och släcka skärmen
backlight_pin_20.value(1)

led_red = PWM(Pin(6))
led_red.freq(1000)
led_red.duty_u16(65535)
led_green = PWM(Pin(7))
led_green.freq(1000)
led_green.duty_u16(65535)
led_blue = PWM(Pin(8))
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

    # Total
    "charge_ah": 0,
    "energy_wh": 0,
    "avg_current_a": 0,
    "avg_power_w": 0,
    "elapsed_h": 0,

    # Dygn / igår
    "daily_ah": 0,
    "daily_wh": 0,
    "yesterday_ah": 0,
    "yesterday_wh": 0,
    "yesterday_date": None,

    "mem_free_kb": 0,
    "mem_used_kb": 0,
    "time_str": "",
}

# === INA260 setup (I2C på GP26/GP27) ===
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


# === Energi / laddning (robust långtid) ===
energy_Wh = 0.0
charge_Ah = 0.0

energy_seconds = 0               # total tid i sekunder
last_energy_ts = time.time()     # epoch-sekunder

# === Dygnsförbrukning ===
daily_Ah = 0.0
daily_Wh = 0.0
current_day_key = None           # (YYYY,MM,DD) i svensk tid

DAILY_HISTORY_DAYS = 7
daily_history = []               # {"day": (Y,M,D), "Ah": x, "Wh": y}


def roll_daily_if_needed():
    """Byter dygn baserat på svensk tid och nollställer daily_Ah/Wh."""
    global current_day_key, daily_Ah, daily_Wh, daily_history

    t = time_handler.get_swedish_time_tuple()
    day_key = (t[0], t[1], t[2])  # (YYYY,MM,DD)

    if current_day_key is None:
        current_day_key = day_key
        return

    if day_key != current_day_key:
        # Spara gårdagens dygnsvärden
        daily_history.append({
            "day": current_day_key,
            "Ah": daily_Ah,
            "Wh": daily_Wh
        })

        with open(f"data\{current_day_key}.txt", "w") as f:
            f.write(f"{current_day_key}\n")
            f.write(f"Förbrukat {daily_Ah} Ah\n")
            f.write(f"Förbrukat {daily_Wh} Wh\n")
            f.write(f"Snitt {daily_Ah}/24 Ah\n")
            f.write(f"Snitt {daily_Wh}/24 Wh\n")

        if len(daily_history) > DAILY_HISTORY_DAYS:
            daily_history.pop(0)

        # Nollställ för ny dag
        daily_Ah = 0.0
        daily_Wh = 0.0
        current_day_key = day_key


def get_yesterday_values():
    """Returnerar (date_str, Ah, Wh) för senaste sparade dygn, annars (None, 0, 0)."""
    if not daily_history:
        return None, 0.0, 0.0
    d = daily_history[-1]
    y, m, day = d["day"]
    return f"{y:04d}-{m:02d}-{day:02d}", d["Ah"], d["Wh"]


def update_energy_accumulators(current_A, power_W):
    """
    Robust långtid:
    - Tid i sekunder (int)
    - Ah och Wh integreras korrekt
    - Dygnsförbrukning (svensk dag) uppdateras
    """
    global charge_Ah, energy_Wh, energy_seconds, last_energy_ts
    global daily_Ah, daily_Wh

    # Byt dygn om datum ändrats (svensk tid)
    roll_daily_if_needed()

    now = time.time()
    dt = now - last_energy_ts
    last_energy_ts = now

    # Skydd mot tids-hopp (t.ex. NTP sync) och konstiga dt
    if dt <= 0 or dt > 10:
        elapsed_h = energy_seconds / 3600.0 if energy_seconds > 0 else 0.0
        avg_A = charge_Ah / elapsed_h if elapsed_h > 0 else 0.0
        avg_W = energy_Wh  / elapsed_h if elapsed_h > 0 else 0.0
        return elapsed_h, avg_A, avg_W

    energy_seconds += dt

    add_Ah = current_A * (dt / 3600.0)
    add_Wh = power_W   * (dt / 3600.0)

    charge_Ah += add_Ah
    energy_Wh  += add_Wh

    daily_Ah += add_Ah
    daily_Wh += add_Wh

    elapsed_h = energy_seconds / 3600.0
    avg_A = charge_Ah / elapsed_h if elapsed_h > 0 else 0.0
    avg_W = energy_Wh  / elapsed_h if elapsed_h > 0 else 0.0

    return elapsed_h, avg_A, avg_W


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
        if secret.MAX_BLINK:
            led_green.duty_u16(20000)

    if temp_history is not None:
        temp_24h_min = min(temp_history)
        temp_24h_max = max(temp_history)


# === Display-uppdatering ===
async def update_display():
    global alarm_visible, use_gpio_10, control_output_state_9, control_output_state_10
    global trigger_pin_12, trigger_pin_13, trigger_pin_14, trigger_pin_15, backlight_pin_20
    global temperature_c, temp_24h_min, temp_24h_max, led_red, led_green, led_blue, DISPLAY_DATA
    global charge_Ah, energy_Wh, daily_Ah, daily_Wh

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
            backlight_pin_20.value(0)
            await asyncio.sleep(0.5)
        elif trigger_pin_14.value() == 0 and backlight_pin_20.value() == 0:
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

            if trigger_pin_15.value() == 1 and trigger_pin_13.value() == 1:  # Visa vanliga infon
                minmax_str = f"Styr Min: {min_th:.2f}°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 90, scale=2)

                minmax_str = f"Styr Max: {max_th:.2f}°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 110, scale=2)

                if temp_24h_min is not None:
                    minmax_str = f"{secret.MAX_TIME} Min: {temp_24h_min:.2f}°C"
                else:
                    minmax_str = f"{secret.MAX_TIME} Min: --°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 130, scale=2)

                if temp_24h_max is not None:
                    minmax_str = f"{secret.MAX_TIME} Max: {temp_24h_max:.2f}°C"
                else:
                    minmax_str = f"{secret.MAX_TIME} Max: --°C"
                x = (320 - display.measure_text(minmax_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(minmax_str, x, 150, scale=2)

                if local_ver is not None:
                    local_ver = None
                if github_ver is not None:
                    github_ver = None

            if trigger_pin_13.value() == 0:  # Visa status1 i stället
                energy_text = f"Tot Ah:{charge_Ah:.3f} Wh:{energy_Wh:.2f}"
                x = (320 - display.measure_text(energy_text, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(energy_text, x, 90, scale=2)

                energy_text2 = f"Snitt A:{avg_A:.2f} W:{avg_W:.1f}"
                x = (320 - display.measure_text(energy_text2, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(energy_text2, x, 110, scale=2)


                daily_text = f"Dygn Ah:{daily_Ah:.3f} Wh:{daily_Wh:.2f}"
                x = (320 - display.measure_text(daily_text, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(daily_text, x, 130, scale=2)


                if y_date is None:
                    y_text = "Igår: --"
                else:
                    y_text = f"{y_date} Ah:{y_Ah:.3f} Wh:{y_Wh:.2f}"
                x = (320 - display.measure_text(y_text, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(y_text, x, 150, scale=2)
            
            if trigger_pin_15.value() == 0:  # Visa status2 i stället
                uptime_str = web_server.get_uptime() + " " + wlan.ifconfig()[0]
                x = (320 - display.measure_text(uptime_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(uptime_str, x, 90, scale=2)

                tasks_str = f"{task_handler.running_tasks()} körs, omstart {task_handler.restarted_nr}"
                x = (320 - display.measure_text(tasks_str, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(tasks_str, x, 110, scale=2)

                if local_ver is None:
                    local_ver = "Local : " + ota.get_local_version()
                x = (320 - display.measure_text(local_ver, scale=2)) // 2
                display.set_pen(WHITE)
                display.text(local_ver, x, 130, scale=2)

                if github_ver is None:
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

        # INA260 + Energi/Ah/Wh + Dygn + Igår
        elapsed_h = 0.0
        avg_A = 0.0
        avg_W = 0.0
        y_date, y_Ah, y_Wh = get_yesterday_values()

        try:
            voltage = read_voltage()
            current = read_current()
            power = read_power()

            elapsed_h, avg_A, avg_W = update_energy_accumulators(current, power)
            y_date, y_Ah, y_Wh = get_yesterday_values()

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
        display.text(mem_text, x, 225, scale=2)

        # Knapparna
        display.set_pen(WHITE)
        display.text("Kyla", 0, 55, scale=2)
        display.text("Lyse", 280, 55, scale=2)
        display.text("Stat1", 0, 182, scale=2)
        display.text("Stat2", 270, 182, scale=2)

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

            "charge_ah": charge_Ah,
            "energy_wh": energy_Wh,
            "avg_current_a": avg_A,
            "avg_power_w": avg_W,
            "elapsed_h": elapsed_h,

            "daily_ah": daily_Ah,
            "daily_wh": daily_Wh,
            "yesterday_ah": y_Ah,
            "yesterday_wh": y_Wh,
            "yesterday_date": y_date,

            "mem_free_kb": mem_free // 1024,
            "mem_used_kb": mem_alloc // 1024,
            "time_str": time_str,
        })

        task_handler.feed_health("app_main.update_display")
        gc.collect()
        await asyncio.sleep(0.2)


# === Temperaturmätning (endast trigger 12) ===
async def read_temperature():
    global temperature_c, control_output_state_9, control_output_state_10, use_gpio_10
    global trigger_pin_12, trigger_pin_13, trigger_pin_14, trigger_pin_15, backlight_pin_20
    global temp_24h_min, temp_24h_max

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
            print("Temp-fel:", e)

        task_handler.feed_health("app_main.read_temperature")
        gc.collect()
        await asyncio.sleep(1.25)


# === Main ===
async def main():
    # Checka om app_main.main startats om, starta tasks om det inte körs
    task1 = True
    task2 = True

    for name, _ in list(task_handler.TASKS.items()):
        if name == "app_main.read_temperature":
            task1 = False
        elif name == "app_main.update_display":
            task2 = False

    if task1:
        task_handler.create_managed_task(read_temperature(), "app_main.read_temperature")
    if task2:
        task_handler.create_managed_task(update_display(), "app_main.update_display")

    while True:
        task_handler.feed_health("app_main.main")
        task_handler.feed_watchdog()
        gc.collect()
        await asyncio.sleep(5)
