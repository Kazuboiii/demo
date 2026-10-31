import time
import sys

# Wait for network interfaces to be fully ready
time.sleep(3)

# Now start the actual discovery
sys.path.insert(0, "C:/Users/Kazuboiii/Desktop/HOMS/scripts")
exec(open("C:/Users/Kazuboiii/Desktop/HOMS/scripts/lan_discovery.py").read())
