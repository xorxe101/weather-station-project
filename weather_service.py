import time
import sys
import math
from datetime import datetime, timedelta

# Import τον κώδικα των αισθητήρων σου
try:
    from sensor_reader import sensor_reader
except ImportError:
    print("❌ Error: sensor_reader.py not found!")
    sys.exit(1)

# Import τη Βάση Δεδομένων από το Flask app
# Προσοχή: Το app.py πρέπει να είναι στον ίδιο φάκελο
try:
    from app import app, db, SensorReading
except ImportError:
    print("❌ Error: Could not import DB models from app.py")
    sys.exit(1)

# --- ΡΥΘΜΙΣΕΙΣ ---
READING_INTERVAL_MINUTES = 5
HOURS_TO_STORE = 24
MAX_HISTORY = (HOURS_TO_STORE * 60) // READING_INTERVAL_MINUTES

def get_seconds_until_next_interval():
    """Υπολογίζει πόσα δευτερόλεπτα πρέπει να περιμένουμε μέχρι το επόμενο 'στρογγυλό' λεπτο"""
    now = datetime.now()
    minutes_to_add = READING_INTERVAL_MINUTES - (now.minute % READING_INTERVAL_MINUTES)
    target_time = (now + timedelta(minutes=minutes_to_add)).replace(second=0, microsecond=0)
    seconds_to_wait = (target_time - now).total_seconds()
    return seconds_to_wait, target_time

def save_to_db(data):
    """Αποθηκεύει τα δεδομένα και κρατάει ΜΟΝΟ τις τελευταίες 288 εγγραφές"""
    
    def clean_val(value):
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    with app.app_context():
        try:
            # 1. Δημιουργία της νέας εγγραφής
            new_reading = SensorReading(
                timestamp=datetime.now(),
                air_temp=clean_val(data.get('Air Temperature')),
                soil_temp=clean_val(data.get('Soil Temperature')),
                humidity=clean_val(data.get('Humidity')),
                wind_speed=clean_val(data.get('WindSpeed')),
                wind_direction=clean_val(data.get('WindDirection')),
                rainfall=clean_val(data.get('RainFall')),
                rain_rate=clean_val(data.get('RainRate')),
                dew_point=clean_val(data.get('DewPoint')),
                pressure=clean_val(data.get('Pressure'))
            )

            db.session.add(new_reading)
            
            # 2. ΕΛΕΓΧΟΣ & ΚΑΘΑΡΙΣΜΟΣ (Το σημείο που ζήτησες)
            # Βρίσκουμε όλες τις εγγραφές ταξινομημένες από την πιο παλιά στην πιο καινούργια
            # Σημείωση: Αυτό είναι πολύ γρήγορο για 300 εγγραφές, αλλά όχι για εκατομμύρια.
            all_records = SensorReading.query.order_by(SensorReading.timestamp.asc()).all()
            
            # Υπολογίζουμε πόσες έχουμε τώρα (μαζί με τη νέα που μόλις βάλαμε στο session)
            # Προσοχή: Το len(all_records) μετράει αυτές που υπάρχουν ήδη στη βάση.
            # Ας κάνουμε πρώτα commit τη νέα για να είμαστε σίγουροι.
            db.session.commit()

            # Ξανα-μετράμε μετά το commit
            count = SensorReading.query.count()
            
            limit = MAX_HISTORY
            
            if count > limit:
                excess = count - limit
                # Βρίσκουμε τις 'excess' παλαιότερες εγγραφές
                oldest_records = SensorReading.query.order_by(SensorReading.timestamp.asc()).limit(excess).all()
                
                for record in oldest_records:
                    db.session.delete(record)
                    print(f"♻️ Deleted old record ID: {record.id} (Time: {record.timestamp})")
                
                # Κάνουμε commit τις διαγραφές
                db.session.commit()

            print(f"✅ Data saved. Total records in DB: {SensorReading.query.count()}")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Database Error: {e}")

def main_loop():
    print(f"🌡️ Weather Service Started (DB Mode). Target Interval: Every {READING_INTERVAL_MINUTES} minutes.")
    
    while True:
        # --- ΒΗΜΑ 1: ΣΥΓΧΡΟΝΙΣΜΟΣ ---
        sleep_seconds, target_time = get_seconds_until_next_interval()
        print(f"⏳ Waiting {int(sleep_seconds)}s until next sync point ({target_time.strftime('%H:%M:%S')})...")
        
        time.sleep(sleep_seconds)
        
        # --- ΒΗΜΑ 2: ΜΕΤΡΗΣΗ & ΑΠΟΘΗΚΕΥΣΗ ---
        try:
            print(f"⏰ Woke up! Reading sensors at {datetime.now().strftime('%H:%M:%S')}...")
            
            # Διάβασμα Αισθητήρων
            current_data = sensor_reader.read_all_sensors()
            
            # Εκτύπωση για debugging
            print(f"📊 Read Data: {current_data}")

            # Αποθήκευση στη Βάση
            save_to_db(current_data)
            
        except Exception as e:
            print(f"⚠️ Unexpected Service Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()