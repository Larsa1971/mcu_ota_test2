import gc
import uasyncio as asyncio
import machine, os, urequests, ubinascii, secret
import task_handler


# ============
# GitHub helpers
# ============
def github_get(url):
    headers = {"User-Agent": "micropython-pico"}
    if getattr(secret, "GITHUB_TOKEN", None):
        headers["Authorization"] = f"token {secret.GITHUB_TOKEN}"
    r = urequests.get(url, headers=headers)
    if r.status_code != 200:
        txt = r.text
        r.close()
        raise RuntimeError("HTTP %s: %s" % (r.status_code, txt))
    data = r.json()
    r.close()
    return data

def download_file_from_github(filepath):
    url = f"https://api.github.com/repos/{secret.USER}/{secret.REPO}/contents/{filepath}?ref={secret.BRANCH}"
    data = github_get(url)
    if "content" not in data:
        raise RuntimeError("Ingen 'content' i svar för " + filepath)
    return ubinascii.a2b_base64(data["content"])

# ============
# Version helpers
# ============
def get_local_version():
    try:
        import version
        return version.VERSION
    except Exception:
        return None

def get_remote_version():
    raw = download_file_from_github("version.py")
    ns = {}
    exec(raw.decode(), ns)
    return ns.get("VERSION", None), raw

def get_remote_version_status():
    raw = download_file_from_github("version.py")
    ns = {}
    exec(raw.decode(), ns)
    return ns.get("VERSION", None)
# ============
# OTA logic
# ============
async def ota_check():
    try:
        gc.collect()
        local_ver = get_local_version()
        remote_ver, remote_version_py = get_remote_version()
        print("Lokal version:", local_ver, "Remote version:", remote_ver)

        if local_ver != remote_ver and remote_ver is not None:
            print("Ny version hittad → uppdaterar...")

            # Ladda ner ny app_main.py (din riktiga app)
            new_app = download_file_from_github("app_main.py")
            with open("app_main_new.py", "wb") as f:
                f.write(new_app)

            # (valfritt) testa syntax – rudimentärt test
            try:
                compile(new_app, "app_main_new.py", "exec")
                print("Koden OK vid kompilering:")

                # Byt namn på nya filen
                if "app_main_new.py" in os.listdir():
                    if "app_main.py" in os.listdir():
                        os.rename("app_main.py", "app_main_old.py")
                        os.rename("app_main_new.py", "app_main.py")
                        # Ladda ner ny version.py
                        with open("version.py", "wb") as f:
                            f.write(remote_version_py)
                        print("✅ Uppdatering klar – startar om")
                        await task_handler.graceful_restart()


            except SyntaxError as e:
                print("Syntaxfel i ny app:")
                if hasattr(e, "args") and len(e.args) > 0:
                    print("Detaljer:", e.args)
                else:
                    print("Felmeddelande:", e)

            except Exception as e:
                print("Kodfel vid kompilering:", e)
                if "app_main_new.py" in os.listdir():
                    os.remove("app_main_new.py")
                return False

        else:
            print("Ingen ny version")
    except Exception as e:
        print("OTA error:", e)

async def rollback_if_broken():
    print("Kollar om det finns app_main_old.py kvar")
    if "app_main_old.py" in os.listdir() and "app_main.py" in os.listdir():
        try:
            with open("app_main.py") as f:
                compile(f.read(), "app_main.py", "exec")
            print("app_main.py – OK")
            os.remove("app_main_old.py")
            print("app_main_old.py – Deletad")
        except Exception as e:
            print("⚠️ Fel i app_main.py – gör rollback", e)
            os.remove("app_main.py")
            os.rename("app_main_old.py", "app_main.py")
            await task_handler.graceful_restart()
    else:
        print("Ingen app_main_old.py finns!")
