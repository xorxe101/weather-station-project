import time
import json
import os
import sys
from datetime import datetime, timedelta

# Import τον κώδικα των αισθητήρων σου
try:
    from sensor_reader import sensor_reader
except ImportError:
    print("❌ Error: sensor_reader.py not found!")
    sys.exit(1)

# --- ΡΥΘΜΙΣΕΙΣ ---
READING_INTERVAL_MINUTES = 5
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sensor_history.json')
HOURS_TO_STORE = 24
MAX_HISTORY = (HOURS_TO_STORE * 60) // READING_INTERVAL_MINUTES

def load_history():
    """Φορτώνει το υπάρχον ιστορικό για να μην το χάσουμε στο restart"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    """Αποθηκεύει τα δεδομένα με ασφάλεια (Atomic Write)"""
    try:
        temp_file = HISTORY_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(history, f)
        os.replace(temp_file, HISTORY_FILE)
        print(f"✅ Data saved at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"❌ Error saving history: {e}")

def get_seconds_until_next_interval():
    """Υπολογίζει πόσα δευτερόλεπτα πρέπει να περιμένουμε μέχρι το επόμενο 'στρογγυλό' λεπτο"""
    now = datetime.now()
    
    # Βρίσκουμε πόσα λεπτά πρέπει να προσθέσουμε για να φτάσουμε στο επόμενο διάστημα
    # Π.χ. αν είναι 14:03 και το interval είναι 5, το υπόλοιπο είναι 3. Άρα θέλουμε 5-3 = 2 λεπτά ακόμα.
    minutes_to_add = READING_INTERVAL_MINUTES - (now.minute % READING_INTERVAL_MINUTES)
    
    # Φτιάχνουμε τον χρόνο-στόχο (Target Time)
    # Μηδενίζουμε δευτερόλεπτα και microseconds για απόλυτη ακρίβεια (:00)
    target_time = (now + timedelta(minutes=minutes_to_add)).replace(second=0, microsecond=0)
    
    # Υπολογίζουμε τη διαφορά σε δευτερόλεπτα
    seconds_to_wait = (target_time - now).total_seconds()
    
    return seconds_to_wait, target_time

def main_loop():
    print(f"🌡️ Weather Service Started. Target Interval: Every {READING_INTERVAL_MINUTES} minutes.")
    history = load_history()
    
    while True:
        # --- ΒΗΜΑ 1: ΣΥΓΧΡΟΝΙΣΜΟΣ (ΠΡΙΝ ΤΗ ΜΕΤΡΗΣΗ) ---
        # Υπολογίζουμε πότε πρέπει να ξυπνήσουμε
        sleep_seconds, target_time = get_seconds_until_next_interval()
        
        print(f"⏳ Waiting {int(sleep_seconds)}s until next sync point ({target_time.strftime('%H:%M:%S')})...")
        
        # Κοιμόμαστε μέχρι την ακριβή ώρα
        time.sleep(sleep_seconds)
        
        # --- ΒΗΜΑ 2: ΕΚΤΕΛΕΣΗ ΜΕΤΡΗΣΗΣ (ΜΟΛΙΣ ΞΥΠΝΗΣΟΥΜΕ) ---
        try:
            print(f"⏰ Woke up! Reading sensors at {datetime.now().strftime('%H:%M:%S')}...")
            
            # Διάβασμα Αισθητήρων
            current_data = sensor_reader.read_all_sensors()
            
            # Εξασφαλίζουμε ότι η ώρα που γράφουμε είναι η "σωστή" (στρογγυλοποιημένη) 
            # ή η πραγματική (ανάλογα τι προτιμάς - εδώ βάζω την πραγματική λήψη)
            if 'Time' not in current_data:
                current_data['Time'] = datetime.now().isoformat()

            # Ενημέρωση Ιστορικού
            history.append(current_data)
            
            if len(history) > MAX_HISTORY:
                history = history[-MAX_HISTORY:]
            
            # Αποθήκευση
            save_history(history)
            
        except Exception as e:
            print(f"⚠️ Unexpected Error: {e}")
            # Αν συμβεί λάθος, περιμένουμε λίγο για να μην μπει σε loop σφαλμάτων
            time.sleep(10)

if __name__ == "__main__":
    main_loop()