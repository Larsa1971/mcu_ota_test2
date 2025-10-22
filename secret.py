# WiFi
WIFI_SSID = "DIN_SSID"
WIFI_PASSWORD = "DITT_LÖSENORD"

# Wifi och tidsynk
CHECK_INTERVAL_WIFI = 60 # hur många sekunder mellan wifi koll
TIME_SYNC_REPEAT = 24 # Efter hur länge tiden i timmar ska tiden syncks igen

#Temp styrning
LARM_TEMP = 29
LOW_TEMP_MIN = 27
LOW_TEMP_MAX = 28
HIGH_TEMP_MIN = 26.5
HIGH_TEMP_MAX = 27.5

# GitHub
GITHUB_TOKEN = "ghp_xxxDIN_TOKENxxx"
USER = "dittgithubnamn"
REPO = "dittrepo"
BRANCH = "main"
FILE_PATH = "app_main.py"   # filen vi vill hålla uppdaterad
CHECK_INTERVAL_OTA = 86400 # 1800 = 30 min 43 200 = 12 tim tiden i sekunder för verifiering om ny version kommit
