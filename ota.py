import gc
import uasyncio as asyncio
import machine, os, urequests, ubinascii, secret
import task_handler


# ============
# GitHub helpers
# ============

def _github_headers():
    headers = {"User-Agent": "micropython-pico"}
    if getattr(secret, "GITHUB_TOKEN", None):
        headers["Authorization"] = "token %s" % secret.GITHUB_TOKEN
    return headers

def github_get_json(url):
    """Används bara om du verkligen behöver GitHub API som JSON."""
    r = urequests.get(url, headers=_github_headers())
    if r.status_code != 200:
        txt = r.text
        r.close()
        raise RuntimeError("HTTP %s: %s" % (r.status_code, txt))
    data = r.json()
    r.close()
    gc.collect()
    return data

def download_small_file_from_github(filepath):
    """
    Ladda ner en liten fil (som version.py) i ett svep.
    Returnerar bytes.
    """
    url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        secret.USER, secret.REPO, secret.BRANCH, filepath
    )
    r = urequests.get(url, headers=_github_headers())
    if r.status_code != 200:
        txt = r.text
        r.close()
        raise RuntimeError("HTTP %s: %s" % (r.status_code, txt))
    # r.text är str → gör om till bytes
    data = r.text.encode()
    r.close()
    gc.collect()
    return data

def download_file_from_github_chunked(filepath, local_filename, chunk_size=512):
    """
    Ladda ner en (potentiellt stor) fil i delar och skriv direkt till disk.
    Ingen stor buffer i RAM.
    """
    url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        secret.USER, secret.REPO, secret.BRANCH, filepath
    )
    r = urequests.get(url, headers=_github_headers(), stream=True)
    if r.status_code != 200:
        txt = r.text
        r.close()
        raise RuntimeError("HTTP %s: %s" % (r.status_code, txt))

    try:
        with open(local_filename, "wb") as f:
            while True:
                chunk = r.raw.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
    finally:
        r.close()
        gc.collect()


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
    """
    Hämtar version.py (liten fil) i ett svep,
    extraherar VERSION samt returnerar både VERSION och rå bytes.
    """
    raw = download_small_file_from_github("version.py")
    ns = {}
    exec(raw.decode(), ns)
    gc.collect()
    return ns.get("VERSION", None), raw

def get_remote_version_status():
    raw = download_small_file_from_github("version.py")
    ns = {}
    exec(raw.decode(), ns)
    gc.collect()
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

            # Ladda ner ny app_main.py i delar till app_main_new.py
            download_file_from_github_chunked("app_main.py", "app_main_new.py")

            # (valfritt) testa syntax – läs från fil istället för från nätet
            try:
                with open("app_main_new.py", "r") as f:
                    new_app_source = f.read()

                compile(new_app_source, "app_main_new.py", "exec")
                print("Koden OK vid kompilering:")

                # Byt namn på nya filen
                if "app_main_new.py" in os.listdir():
                    if "app_main.py" in os.listdir():
                        os.rename("app_main.py", "app_main_old.py")
                    os.rename("app_main_new.py", "app_main.py")

                    # Skriv ner nya version.py (den är liten)
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
                # misslyckad uppdatering → ta bort new-fil om den finns
                if "app_main_new.py" in os.listdir():
                    os.remove("app_main_new.py")
                gc.collect()

            except Exception as e:
                print("Kodfel vid kompilering:", e)
                if "app_main_new.py" in os.listdir():
                    os.remove("app_main_new.py")
                gc.collect()
                return False

        else:
            print("Ingen ny version")
            gc.collect()
    except Exception as e:
        print("OTA error:", e)
        gc.collect()

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
    gc.collect()
