import machine
import time
import os

print("boot.py körs")
time.sleep(1)

    
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
        machine.reset()

print("boot.py klar, inga dubbla filer!!!")
