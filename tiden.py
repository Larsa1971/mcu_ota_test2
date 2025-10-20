import time

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
        return True
    return False

def get_swedish_time_tuple():
    """Returnerar en lokal svensk tidstuple (år, mån, dag, tim, min, sek)."""
    utc = time.localtime()
    offset = 2 if is_summer_time(*utc[:3]) else 1
    t = time.localtime(time.mktime(utc) + offset * 3600)
    return t

