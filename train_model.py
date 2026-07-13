import pandas as pd
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
import joblib

# ==========================================
# ⚙️ ΒΑΣΙΚΕΣ ΡΥΘΜΙΣΕΙΣ (ΠΙΝΑΚΑΣ ΕΛΕΓΧΟΥ)
# ==========================================

# 1. Ρυθμίσεις Χρόνου & Μοντέλου
DATA_INTERVAL_MINUTES = 5        # Κάθε πόσα λεπτά παίρνει μέτρηση ο σταθμός; (π.χ. 5)
PREDICTION_HORIZON_MINUTES = 60  # Πόσα λεπτά στο μέλλον θέλεις να προβλέψεις; (π.χ. 60)

# 2. Δεδομένα (Τι διαβάζει και τι μαντεύει)
FEATURES = ['air_temp', 'humidity', 'pressure']         # Οι στήλες που χρησιμοποιεί για να σκεφτεί
TARGET_COLUMN = 'air_temp'                              # Η στήλη που προσπαθεί να μαντέψει

# 3. Στοιχεία Σύνδεσης MariaDB
DB_USER = "weather"
DB_PASS = "station"
DB_HOST = "localhost"
DB_NAME = "Accounts"
TABLE_NAME = "sensor_readings"

# 4. Όνομα Αρχείου Αποθήκευσης
MODEL_FILENAME = 'weather_brain.pkl'

# ==========================================
# 🚀 ΚΥΡΙΩΣ ΚΩΔΙΚΑΣ (Η ΛΟΓΙΚΗ ΤΟΥ ΜΗΧΑΝΙΣΜΟΥ)
# ==========================================

def train_weather_model():
    print("Σύνδεση στη MariaDB και φόρτωση δεδομένων...")

    try:
        # Δημιουργία σύνδεσης με τη βάση
        engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}")

        # Φέρνουμε δυναμικά μόνο τις στήλες που χρειαζόμαστε
        columns_to_fetch = ['timestamp'] + FEATURES
        if TARGET_COLUMN not in FEATURES:
            columns_to_fetch.append(TARGET_COLUMN)

        columns_str = ", ".join([f"`{col}`" for col in columns_to_fetch])
        query = f"SELECT {columns_str} FROM {TABLE_NAME} ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, engine)
        print(f"Βρέθηκαν {len(df)} εγγραφές.")

        # --- Ο ΔΥΝΑΜΙΚΟΣ ΥΠΟΛΟΓΙΣΜΟΣ ΧΡΟΝΟΥ ---
        # Πόσες γραμμές (rows) κάτω πρέπει να κοιτάξει για να βρει το μέλλον;
        shift_rows = int(PREDICTION_HORIZON_MINUTES / DATA_INTERVAL_MINUTES)
        print(f"Στόχος: Πρόβλεψη σε {PREDICTION_HORIZON_MINUTES} λεπτά (μετατόπιση κατά {shift_rows} γραμμές).")

        # Δημιουργία της στήλης στόχου
        target_col_name = f'Target_{TARGET_COLUMN}_{PREDICTION_HORIZON_MINUTES}m'
        df[target_col_name] = df[TARGET_COLUMN].shift(-shift_rows)

        # Καθαρισμός γραμμών στο τέλος του πίνακα που δεν έχουν ακόμα "μέλλον"
        df = df.dropna()

        # Διαχωρισμός σε X (δεδομένα εισόδου) και y (επιθυμητός στόχος)
        X = df[FEATURES]
        y = df[target_col_name]

        print(f"Εκπαίδευση του Random Forest μοντέλου με {len(X)} έγκυρα σετ δεδομένων...")
        model = RandomForestRegressor(n_estimators=50, random_state=42)
        model.fit(X, y)

        # Αποθήκευση του "εγκεφάλου"
        joblib.dump(model, MODEL_FILENAME)
        print(f"✅ Το μοντέλο αποθηκεύτηκε επιτυχώς στο '{MODEL_FILENAME}'!")

    except Exception as e:
        print(f"❌ Προέκυψε σφάλμα: {e}")

if __name__ == "__main__":
    train_weather_model()