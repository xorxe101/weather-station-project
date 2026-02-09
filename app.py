from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import time, threading, json, os
import pymysql, re

# Import your existing sensor reader
from sensor_reader import sensor_reader

app = Flask(__name__)

# ==========================================
# CONFIGURATION
# ==========================================

app.config['SECRET_KEY'] = 'weather-station-secret-key-98765'

# ---------------------------------------------------------
# [CHANGE THIS] DATABASE CONFIGURATION FOR MARIADB
# ---------------------------------------------------------
# Format: mysql+pymysql://USERNAME:PASSWORD@HOST:PORT/DATABASE_NAME
# Example: root user, no password, localhost, db named 'maria'
# If you have a password, it would look like: 'root:mypassword@localhost/maria'

# ---------------------------------------------------------
# DATABASE CONFIGURATION (MariaDB)
# ---------------------------------------------------------
# Αντικαταστήστε αυτά με τα σωστά στοιχεία της MariaDB σας
DB_USER = 'weather'      
DB_PASS = 'station'      
DB_HOST = 'localhost' 
DB_NAME = 'Accounts'     

basedir = os.path.abspath(os.path.dirname(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ---------------------------------------------------------

# Initialize Extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Weather Station Config
READING_INTERVAL_MINUTES = 5
HOURS_TO_STORE = 24
MAX_HISTORY = (HOURS_TO_STORE * 60) // READING_INTERVAL_MINUTES

# Global variables
latest_sensor_data = {}
sensor_history = []

# File paths (for history backup)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, 'sensor_history.json')

# ==========================================
# DATABASE MODELS
# ==========================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    moments = db.relationship('SavedMoment', backref='user', lazy=True)

class SavedMoment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Use lambda to avoid SQLAlchemy context errors
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now())
    note = db.Column(db.String(200))
    snapshot_data = db.Column(db.Text, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# SENSOR LOGIC
# ==========================================

def load_history():
    global sensor_history, latest_sensor_data # <--- ΠΡΟΣΘΗΚΗ ΤΟΥ latest_sensor_data
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                saved_history = json.load(f)
                sensor_history = saved_history[-MAX_HISTORY:]
                
                # --- Η ΔΙΟΡΘΩΣΗ ΕΔΩ ---
                # Αν υπάρχει ιστορικό, βάλε την τελευταία εγγραφή ως "Τωρινή"
                # Έτσι, με το που ανοίξει ο server θα δείχνει την παλιά τιμή (π.χ. 12:45)
                # και όχι κενό, μέχρι να έρθει το 12:50.
                if sensor_history:
                    latest_sensor_data = sensor_history[-1]
                    print(f"Loaded {len(sensor_history)} records. Latest data restored from: {latest_sensor_data.get('Time')}")
                    
    except Exception as e:
        print(f"Error loading history: {e}")

def save_history():
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(sensor_history, f)
    except Exception as e:
        print(f"Error saving history: {e}")

def read_sensors():
    global latest_sensor_data, sensor_history
    sensor_data = sensor_reader.read_all_sensors()
    if sensor_data:
        latest_sensor_data = sensor_data
        sensor_history.append(sensor_data)
        if len(sensor_history) > MAX_HISTORY:
            sensor_history.pop(0)
        save_history()
        return True
    return False

def exact_interval_loop():
    print(f"Waiting for next exact {READING_INTERVAL_MINUTES}-minute interval...")
    now = datetime.now()
    current_minute = now.minute
    minutes_to_wait = READING_INTERVAL_MINUTES - (current_minute % READING_INTERVAL_MINUTES)
    next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_wait)
    seconds_to_wait = (next_time - now).total_seconds()
    
    if seconds_to_wait > 0:
        time.sleep(seconds_to_wait)
    
    while True:
        read_sensors()
        now = datetime.now()
        current_minute = now.minute
        minutes_to_wait = READING_INTERVAL_MINUTES - (current_minute % READING_INTERVAL_MINUTES)
        next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_wait)
        seconds_to_wait = (next_time - now).total_seconds()
        if seconds_to_wait <= 0: seconds_to_wait = 60
        time.sleep(seconds_to_wait)

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html', current_user=current_user)

# --- Authentication Routes ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Έλεγχος: Μόνο αγγλικά γράμματα (κεφαλαία ή μικρά)
        # ^ = αρχή, [a-zA-Z] = αγγλικοί χαρακτήρες, + = ένας ή περισσότεροι, $ = τέλος
        if not re.match(r'^[a-zA-Z]+$', username):
            flash('Το όνομα χρήστη πρέπει να περιέχει μόνο Αγγλικούς χαρακτήρες (A-Z).', 'error')
            return redirect(url_for('signup'))

        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('signup'))
        
        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('index'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            if request.is_json: return jsonify({"success": True})
            return redirect(url_for('index'))
        else:
            if request.is_json: return jsonify({"success": False, "error": "Invalid credentials"}), 401
            flash('Invalid username or password')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_pw = request.form.get('current_password')
        new_pw = request.form.get('new_password')
        
        # 1. ΕΛΕΓΧΟΣ: Αν ο νέος κωδικός είναι ίδιος με τον παλιό
        if current_pw == new_pw:
            flash('New password cannot be the same as the old password', 'error')
            return redirect(url_for('profile'))

        # 2. ΕΛΕΓΧΟΣ: Αν ο τωρινός κωδικός είναι λάθος
        if not check_password_hash(current_user.password, current_pw):
            flash('Incorrect current password', 'error')
            return redirect(url_for('profile'))
        
        # 3. ΕΠΙΤΥΧΙΑ: Αλλαγή κωδικού
        current_user.password = generate_password_hash(new_pw, method='sha256')
        db.session.commit()
        flash('Password updated successfully', 'success')
        return redirect(url_for('profile'))
        
    return render_template('profile.html', current_user=current_user)

@app.route('/api/delete_account', methods=['DELETE'])
@login_required
def delete_account():
    try:
        SavedMoment.query.filter_by(user_id=current_user.id).delete()
        user = User.query.get(current_user.id)
        db.session.delete(user)
        db.session.commit()
        logout_user()
        return jsonify({'success': True, 'message': 'Account deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# --- Saved Moments Routes ---

@app.route('/api/save_moment', methods=['POST'])
@login_required
def save_moment():
    data = request.json
    note = data.get('note', 'My Saved Moment')
    
    # Logic: If current missing, try history. If history missing, empty dict.
    current_data = latest_sensor_data
    if not current_data and len(sensor_history) > 0:
        current_data = sensor_history[-1]
    elif not current_data:
        current_data = {}

    snapshot = {
        "current": current_data,
        "history": list(sensor_history) 
    }

    new_moment = SavedMoment(
        user_id=current_user.id,
        note=note,
        snapshot_data=json.dumps(snapshot, default=str)
    )
    
    db.session.add(new_moment)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Moment saved successfully!"})

@app.route('/my_moments')
@login_required
def my_moments():
    user_moments = SavedMoment.query.filter_by(user_id=current_user.id).order_by(SavedMoment.timestamp.desc()).all()
    
    processed_moments = []
    for m in user_moments:
        try:
            raw_data = json.loads(m.snapshot_data)
            if 'current' in raw_data:
                weather_current = raw_data['current']
                weather_history = raw_data['history']
            else:
                weather_current = raw_data
                weather_history = []

            processed_moments.append({
                "id": m.id,
                "date": m.timestamp.strftime('%Y-%m-%d %H:%M'),
                "note": m.note,
                "current": weather_current,
                "history": weather_history
            })
        except:
            continue
            
    return render_template('my_moments.html', moments=processed_moments, username=current_user.username)

@app.route('/api/delete_moment/<int:moment_id>', methods=['DELETE'])
@login_required
def delete_moment(moment_id):
    moment = SavedMoment.query.get_or_404(moment_id)
    if moment.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        db.session.delete(moment)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Moment deleted'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- Standard API Routes ---

@app.route('/api/latest')
def get_latest():
    return jsonify(latest_sensor_data if latest_sensor_data else {})

@app.route('/api/history/last/<int:hours>hours')
def get_history_hours(hours):
    cutoff_time = datetime.now() - timedelta(hours=hours)
    filtered_history = [
        reading for reading in sensor_history 
        if reading.get('Time') and datetime.fromisoformat(reading['Time']) >= cutoff_time
    ]
    return jsonify(filtered_history)

@app.route('/api/config')
def get_config():
    return jsonify({'reading_interval_minutes': READING_INTERVAL_MINUTES})


# ---------------------------------------------------------
# AUTO-START SENSOR THREAD (ΓΙΑ APACHE)
# ---------------------------------------------------------
load_history()

def start_background_thread():
    if not any(t.name == 'SensorThread' for t in threading.enumerate()):
        sensor_thread = threading.Thread(target=exact_interval_loop, name='SensorThread', daemon=True)
        sensor_thread.start()
        print("Sensor Thread Started!")

try:
    # Προσπάθεια σύνδεσης και δημιουργίας πινάκων (αν δεν υπάρχουν)
    with app.app_context():
        db.create_all()
        
    start_background_thread()
except Exception as e:
    print(f"Error starting system: {e}")

# ---------------------------------------------------------
# MAIN EXECUTION (Μόνο για manual run)
# ---------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)