import sys
import os

# Λέμε στον Apache πού είναι τα αρχεία μας
sys.path.insert(0, '/var/www/weather_app')

# Αλλάζουμε φάκελο εργασίας για να βρίσκει τη βάση δεδομένων
os.chdir('/var/www/weather_app')

# Εισάγουμε την εφαρμογή Flask
from app import app as application
