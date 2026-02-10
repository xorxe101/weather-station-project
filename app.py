from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
from dotenv import load_dotenv
from threading import Thread # <--- ΠΡΟΣΘΕΣΕ ΑΥΤΟ
from datetime import datetime, timedelta
import time, threading, json, os
import pymysql, re

# Import your existing sensor reader
from sensor_reader import sensor_reader

app = Flask(__name__)

load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')  # <--- ΒΑΛΕ ΕΔΩ ΤΟ ΔΙΚΟ ΣΟΥ ΜΥΣΤΙΚΟ ΚΛΕΙΔΙ (SECRET KEY) ή χρησιμοποίησε το .env για ασφάλεια

# Ρυθμίσεις Gmail (ΠΡΟΣΟΧΗ: Θέλει App Password, όχι τον κανονικό κωδικό σου)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER')  # <--- ΒΑΛΕ ΤΟ EMAIL ΣΟΥ
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS')     # <--- ΒΑΛΕ ΤΟ APP PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('EMAIL_USER')

mail = Mail(app)

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
    email = db.Column(db.String(120), unique=True) # <--- ΝΕΟ ΠΕΔΙΟ
    moments = db.relationship('SavedMoment', backref='user', lazy=True)
    temp_unit = db.Column(db.String(5), default='C')   # 'C' ή 'F'
    wind_unit = db.Column(db.String(5), default='kmh') # 'kmh' ή 'ms'

    # 1. ΔΗΜΙΟΥΡΓΙΑ TOKEN (Που περιέχει και τον κωδικό)
    def get_reset_token(self, expires_sec=1800):
        s = Serializer(app.config['SECRET_KEY']) 
        # Αποθηκεύουμε στο Token το ID αλλά ΚΑΙ τον τωρινό κωδικό (self.password)
        return s.dumps({'user_id': self.id, 'sec': self.password}, salt='password-reset-salt')

    # 2. ΕΠΑΛΗΘΕΥΣΗ TOKEN (Με έξτρα έλεγχο)
    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try:
            # Προσπαθούμε να διαβάσουμε το Token
            data = s.loads(token, salt='password-reset-salt', max_age=1800)
        except:
            return None
        
        # Βρίσκουμε τον χρήστη
        user = User.query.get(data['user_id'])
        
        # --- Ο ΕΞΤΡΑ ΕΛΕΓΧΟΣ ---
        # Αν ο χρήστης δεν υπάρχει Ή αν ο κωδικός του έχει αλλάξει από τότε που βγήκε το Link:
        if user is None or user.password != data['sec']:
            return None # Το Link θεωρείται άκυρο!
            
        return user

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

# --- ΝΕΑ ΑΣΥΓΧΡΟΝΗ ΑΠΟΣΤΟΛΗ EMAIL ---

# 1. Η συνάρτηση που τρέχει στο παρασκήνιο
def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            print("✅ Email sent successfully via Thread!")
        except Exception as e:
            print(f"❌ Error sending email: {e}")

# 2. Η συνάρτηση που καλείς εσύ
def send_reset_email(user):
    token = user.get_reset_token()
    msg = Message('Password Reset Request',
                  recipients=[user.email])
    
    link = url_for('reset_token', token=token, _external=True)
    
    msg.body = f'''To reset your password, visit the following link:
{link}

If you did not make this request then simply ignore this email.
'''
    
    # ΕΔΩ ΕΙΝΑΙ Η ΜΑΓΕΙΑ:
    # Αντί να το στείλουμε απευθείας, ξεκινάμε ένα Thread
    # Περνάμε το 'app' γιατί το Thread δεν ξέρει τις ρυθμίσεις μας (config)
    Thread(target=send_async_email, args=(app, msg)).start()
# -------------------------------------------

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html', current_user=current_user)

# --- Authentication Routes ---

# 1. Φόρμα που ζητάει το Email
@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            send_reset_email(user)
            flash('Email sent! Check your inbox for the reset link', 'info')
        else:
            flash('No account found with that email', 'danger')
            
        # Είτε πετύχει είτε αποτύχει, γυρνάμε στο Login για να δει το μήνυμα
        return redirect(url_for('login'))
            
    # Αν κάποιος προσπαθήσει να μπει με GET (απευθείας link), τον στέλνουμε στο login
    return redirect(url_for('login'))


# 2. Φόρμα που βάζεις τον ΝΕΟ κωδικό (αφού πατήσεις το link)
@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_request'))
        
    if request.method == 'POST':
        # Εδώ χρησιμοποιείς τη logic που έχεις ήδη για hashing (π.χ. sha256 ή werkzeug)
        # Υποθέτω ότι χρησιμοποιείς generate_password_hash όπως στο signup
        from werkzeug.security import generate_password_hash # Βεβαιώσου ότι το έχεις κάνει import
        
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
             flash('Passwords do not match', 'danger')
             return render_template('reset_token.html')

        hashed_pw = generate_password_hash(password, method='sha256')
        user.password = hashed_pw
        db.session.commit()
        
        flash('Your password has been updated. You are now able to log in', 'success')
        return render_template('reset_token.html', success=True)
        
    return render_template('reset_token.html', success=False)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # --- 1. ΕΛΕΓΧΟΣ ΜΟΡΦΗΣ USERNAME ---
        # Επιτρέπονται: a-z, A-Z, 0-9, κάτω παύλα (_), τελεία (.)
        if not re.match(r'^[a-zA-Z0-9_.]+$', username):
            flash('Username can only contain letters, numbers, dots (.), and underscores (_).')
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

@app.route('/api/update_preferences', methods=['POST'])
@login_required
def update_preferences():
    data = request.json
    
    # Ενημέρωση των πεδίων του χρήστη
    if 'temp_unit' in data:
        current_user.temp_unit = data['temp_unit']
    
    if 'wind_unit' in data:
        current_user.wind_unit = data['wind_unit']
        
    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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