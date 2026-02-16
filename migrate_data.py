import json
import os
from datetime import datetime
from app import app, db, SensorReading # Κάνουμε import τη νέα κλάση

# Διαδρομή του JSON
HISTORY_FILE = 'sensor_history.json'

def migrate():
    if not os.path.exists(HISTORY_FILE):
        print("❌ Δεν βρέθηκε το αρχείο sensor_history.json")
        return

    print("🔄 Διαβάζω το JSON...")
    with open(HISTORY_FILE, 'r') as f:
        data = json.load(f)

    print(f"📊 Βρέθηκαν {len(data)} εγγραφές. Έναρξη μεταφοράς στη βάση...")

    count = 0
    with app.app_context():
        # Προαιρετικά: Καθαρισμός πίνακα αν θες να ξεκινάς καθαρά
        # SensorReading.query.delete()
        
        for entry in data:
            try:
                # Μετατροπή string time σε python datetime
                # Το JSON σου έχει format "2026-02-14T14:15:01.697675"
                dt = datetime.fromisoformat(entry['Time'])
                
                reading = SensorReading(
                    timestamp=dt,
                    air_temp=entry.get('Air Temperature'),
                    soil_temp=entry.get('Soil Temperature'),
                    humidity=entry.get('Humidity'),
                    wind_speed=entry.get('WindSpeed'),
                    wind_direction=entry.get('WindDirection'),
                    rainfall=entry.get('RainFall'),
                    rain_rate=entry.get('RainRate'),
                    dew_point=entry.get('DewPoint'),
                    pressure=entry.get('Pressure')
                )
                db.session.add(reading)
                count += 1
            except Exception as e:
                print(f"⚠️ Σφάλμα σε εγγραφή: {e}")

        db.session.commit()
        print(f"✅ Επιτυχία! Μεταφέρθηκαν {count} εγγραφές στη MariaDB.")

if __name__ == '__main__':
    migrate()