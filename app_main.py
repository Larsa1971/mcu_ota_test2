import uasyncio as asyncio
import machine

led = machine.Pin("LED", machine.Pin.OUT)

async def blink_task():
    while True:
        led.value(1)
        await asyncio.sleep(0.5)
        led.value(0)
        await asyncio.sleep(0.5)

async def run():
    asyncio.create_task(blink_task())
    while True:
        await asyncio.sleep(3600)
