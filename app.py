from sqlalchemy import text
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
from dotenv import load_dotenv
from threading import Thread # <--- ΠΡΟΣΘΕΣΕ ΑΥΤΟ
from datetime import datetime, timedelta
import pymysql, re, time, threading, json, os, random, psutil, platform, cv2

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
DB_USER = os.environ.get('USER_DB')
DB_PASS = os.environ.get('PASS_DB')
DB_HOST = os.environ.get('HOST_DB')
DB_NAME = os.environ.get('NAME_DB')

# Λίστα με τους Διαχειριστές (Username)
ADMIN_USERS = ['Admin', 'admin'] # <--- ΒΑΛΕ ΤΟ USERNAME ΣΟΥ ΕΔΩ

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

# Helper function to read data from the file generated by weather_service.py
def get_sensor_data():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
                if history:
                    return {
                        "latest": history[-1],
                        "history": history
                    }
    except Exception as e:
        print(f"Error reading sensor file: {e}")
    
    return {"latest": {}, "history": []}

# --- ΡΥΘΜΙΣΕΙΣ ΚΑΜΕΡΑΣ (GLOBAL VARIABLES) ---
outputFrame = None
lock = threading.Lock()
camera_thread = None
CAMERA_ACTIVE = os.environ.get('CAMERA_STATUS').lower() == 'true' # Διαβάζουμε από το .env αν η κάμερα είναι ενεργή ή όχι
FPS = 5  # Καρέ ανά δευτερόλεπτο (μπορείς να το αυξήσεις αν θέλεις πιο ομαλή ροή, αλλά θα ζορίσει το Pi)
FRAME_DELAY = 1 / FPS

# Μετρητής συνδεδεμένων χρηστών
active_clients = 0

# Αυτή η συνάρτηση τρέχει στο παρασκήνιο (Background Thread)
# Ανοίγει την κάμερα ΜΙΑ φορά και ανανεώνει συνεχώς τη μεταβλητή outputFrame
def capture_frames():
    global outputFrame, lock, active_clients
    
    camera = None
    
    while True:
        # ΕΛΕΓΧΟΣ: Υπάρχει κανείς που να βλέπει;
        if active_clients > 0:
            
            # Αν χρειάζεται κάμερα αλλά είναι κλειστή, άνοιξέ την
            if camera is None:
                print("👀 User connected. Starting Camera...")
                camera = cv2.VideoCapture(0)
                # Ρυθμίσεις για να μην ζορίζεται το Pi
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                time.sleep(2.0) # Χρόνος για να ζεσταθεί ο αισθητήρας

            success, frame = camera.read()
            if success:
                ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                with lock:
                    outputFrame = buffer.tobytes()
            else:
                time.sleep(0.1)
            
            # Κανονική ροή, κοιμήσου για λίγο πριν το επόμενο frame
            time.sleep(FRAME_DELAY)

        else:
            # Αν ΔΕΝ υπάρχει κανείς (active_clients == 0)
            if camera is not None:
                print("💤 No users. Stopping Camera to save power...")
                camera.release()
                camera = None # Καθαρίζουμε τη μεταβλητή
            
            # Κοιμήσου για 1 δευτερόλεπτο και ξαναέλεγξε
            time.sleep(1.0)

# Αυτή η συνάρτηση ξεκινά το thread ΜΟΝΟ αν δεν τρέχει ήδη
def start_camera_thread():
    global camera_thread, CAMERA_ACTIVE
    # 1. Πρώτα ελέγχουμε αν επιτρέπεται η κάμερα
    if not CAMERA_ACTIVE:
        print("🔕 Camera is disabled in config. Thread NOT started.")
        return # Σταματάμε εδώ, δεν δημιουργούμε καν το thread

    # 2. Αν επιτρέπεται, τότε το ξεκινάμε
    if camera_thread is None:
        camera_thread = threading.Thread(target=capture_frames)
        camera_thread.daemon = True
        camera_thread.start()
        print("📸 Camera Background Thread Started!")

# Καλλούμε την εκκίνηση του thread
# (Σημείωση: Στο Flask μπορεί να κληθεί 2 φορές στο reload, δεν πειράζει λόγω του ελέγχου if)
start_camera_thread()

# Αυτή η συνάρτηση στέλνει την εικόνα στον Browser
def generate():
    global active_clients, outputFrame, lock
    
    # 1. Νέος πελάτης συνδέθηκε -> Αυξάνουμε τον μετρητή
    with lock:
        active_clients += 1
    
    try:
        while True:
            with lock:
                if outputFrame is None:
                    continue
                current_frame = outputFrame
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + current_frame + b'\r\n')
            time.sleep(FRAME_DELAY)
            
    except GeneratorExit:
        # Αυτό συμβαίνει όταν ο πελάτης κλείνει το tab
        pass
        
    finally:
        # 2. Ο πελάτης έφυγε -> Μειώνουμε τον μετρητή
        # Το 'finally' τρέχει ΠΑΝΤΑ, είτε βγει κανονικά είτε πέσει η σύνδεση
        with lock:
            active_clients -= 1
            # Ασφάλεια: Να μην πάει αρνητικό
            if active_clients < 0: active_clients = 0

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

def send_verification_email(email, otp):
    msg = Message('Weather Station - Email Verification', recipients=[email])
    msg.body = f'''Welcome to Weather Station!

To complete your registration, please enter the following code:

{otp}

If you did not request this code, please ignore this email.
'''
    # Στέλνουμε το email ασύγχρονα (όπως και πριν)
    Thread(target=send_async_email, args=(app, msg)).start()

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html', current_user=current_user, camera_active=CAMERA_ACTIVE)

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
        email = request.form.get('email') # Πλέον είναι υποχρεωτικό

        # 1. ΕΛΕΓΧΟΣ: Το email είναι υποχρεωτικό
        if not email or email.strip() == "":
            flash('Email is required for verification', 'danger')
            return redirect(url_for('signup'))

        # 2. ΕΛΕΓΧΟΣ: Υπάρχει ήδη το Username ή το Email;
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('signup'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('signup'))

        # 3. ΔΗΜΙΟΥΡΓΙΑ OTP ΚΑΙ ΠΡΟΣΩΡΙΝΗ ΑΠΟΘΗΚΕΥΣΗ (SESSION)
        otp = random.randint(100000, 999999) # 6ψήφιος κωδικός

        # Αποθηκεύουμε τα στοιχεία στο session (όχι στη βάση ακόμα!)
        session['temp_user'] = {
            'username': username,
            'email': email,
            'password_hash': generate_password_hash(password, method='sha256'), # Κρυπτογραφούμε από τώρα
            'otp': otp
        }

        # 4. ΑΠΟΣΤΟΛΗ EMAIL
        send_verification_email(email, otp)

        flash('A verification code has been sent to your email', 'info')
        return redirect(url_for('verify_email'))

    return render_template('signup.html')

@app.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    # Αν δεν υπάρχουν προσωρινά στοιχεία, διώξε τον χρήστη
    if 'temp_user' not in session:
        return redirect(url_for('signup'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        stored_otp = str(session['temp_user']['otp'])

        # ΕΛΕΓΧΟΣ ΚΩΔΙΚΟΥ
        if user_otp == stored_otp:
            # ΕΠΙΤΥΧΙΑ! Τώρα γράφουμε στη βάση δεδομένων
            data = session['temp_user']

            new_user = User(
                username=data['username'],
                email=data['email'],
                password=data['password_hash'] # Είναι ήδη hashed
            )

            db.session.add(new_user)
            db.session.commit()

            # Καθαρίζουμε το session
            session.pop('temp_user', None)

            flash('Account created successfully! You can now login', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid verification code. Please try again', 'danger')

    return render_template('verify_email.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username') # ΧΩΡΙΣ .lower()
            password = data.get('password')
        else:
            username = request.form.get('username') # ΧΩΡΙΣ .lower()
            password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        
        # --- ΑΥΣΤΗΡΟΣ ΕΛΕΓΧΟΣ ---
        # 1. Βρήκαμε χρήστη;
        # 2. Είναι ο κωδικός σωστός;
        # 3. Είναι το username ΑΚΡΙΒΩΣ ίδιο; (π.χ. "Admin" == "Admin")
        if user and check_password_hash(user.password, password):
            # Εξτρά έλεγχος Python γιατί η SQL μερικές φορές μπερδεύει τα κεφαλαία
            if user.username != username:
                flash('Invalid username or password')
                return render_template('login.html')

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
    
@app.route('/video_feed') # <-- Για πειραματικό σκοπό, δε θα βάλω login_required εδώ, αλλά μπορείς αν θέλεις
def video_feed():
    if not CAMERA_ACTIVE:
        # Αν η κάμερα είναι κλειστή, στείλε μια κενή απάντηση ή μια εικόνα placeholder
        # Εδώ στέλνουμε μια απλή εικόνα placeholder (προαιρετικά)
        return "Camera is OFF", 404

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- Saved Moments Routes ---

# Στο save_moment πρέπει επίσης να διαβάζουμε φρέσκα δεδομένα
@app.route('/api/save_moment', methods=['POST'])
@login_required
def save_moment():
    data = request.json
    note = data.get('note', 'My Saved Moment')
    
    # Διαβάζουμε φρέσκα δεδομένα από το αρχείο
    sensor_data = get_sensor_data()
    current_data = sensor_data['latest']
    history = sensor_data['history']

    snapshot = {
        "current": current_data,
        "history": history 
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
    data = get_sensor_data()
    return jsonify(data['latest'])

@app.route('/api/history/last/<int:hours>hours')
def get_history_hours(hours):
    data = get_sensor_data()
    history = data['history']
    
    cutoff_time = datetime.now() - timedelta(hours=hours)
    filtered_history = [
        reading for reading in history 
        if reading.get('Time') and datetime.fromisoformat(reading['Time']) >= cutoff_time
    ]
    return jsonify(filtered_history)

@app.route('/api/config')
def get_config():
    return jsonify({'reading_interval_minutes': READING_INTERVAL_MINUTES})

@app.route('/api/system_health')
@login_required
def system_health():
    # SECURITY CHECK: Μόνο οι Admins βλέπουν αυτά τα data
    if current_user.username not in ADMIN_USERS:
        return jsonify({'error': 'Unauthorized'}), 403

    # 1. CPU Usage
    cpu = psutil.cpu_percent(interval=None)

    # 2. RAM Usage
    ram = psutil.virtual_memory()

    # 3. Disk Usage
    disk = psutil.disk_usage('/')

    # 4. SWAP Memory
    swap = psutil.swap_memory()
    
    # 5. Αριθμός Διεργασιών (Processes)
    process_count = len(psutil.pids())
    
    # 6. Network Traffic (Συνολικά MB από το boot)
    net = psutil.net_io_counters()
    sent_mb = round(net.bytes_sent / (1024 * 1024), 1) # Convert to MB
    recv_mb = round(net.bytes_recv / (1024 * 1024), 1) # Convert to MB

    # 7. Temperature (Μόνο για Raspberry Pi Linux)
    temp = "N/A"
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = round(int(f.read()) / 1000, 1)
    except:
        temp = 0 # Σε Windows ή αν αποτύχει

    # 2. Database Size (MB) - SQL Query για MySQL/MariaDB
    db_size = 0
    try:
        query = text("""
            SELECT table_schema AS "Database", 
            ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS "Size" 
            FROM information_schema.TABLES 
            WHERE table_schema = :dbname 
            GROUP BY table_schema
        """)
        # Αντικατέστησε το 'weather_db' με το όνομα της βάσης σου αν διαφέρει
        result = db.session.execute(query, {'dbname': DB_NAME}).fetchone()
        if result:
            db_size = result[1] # Παίρνουμε το μέγεθος
    except Exception as e:
        print(f"DB Size Error: {e}")
        db_size = "N/A"

    # 8. Uptime
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    uptime_str = str(uptime).split('.')[0] # "5 days, 10:20:30"

    return jsonify({
        'cpu': cpu,
        'ram_percent': ram.percent,
        'ram_used': round(ram.used / (1024**3), 2), # GB
        'ram_total': round(ram.total / (1024**3), 2), # GB
        'disk_percent': disk.percent,
        'temp': temp,
        'uptime': uptime_str,
        'swap_percent': swap.percent,
        'processes': process_count,
        'net_sent': sent_mb,
        'net_recv': recv_mb,
        'db_size': db_size
    })


# ---------------------------------------------------------
# AUTO-START SENSOR THREAD (ΓΙΑ APACHE)
# ---------------------------------------------------------

try:
    # Προσπάθεια σύνδεσης και δημιουργίας πινάκων (αν δεν υπάρχουν)
    with app.app_context():
        db.create_all()
except Exception as e:
    print(f"Error starting system: {e}")

# ---------------------------------------------------------
# MAIN EXECUTION (Μόνο για manual run)
# ---------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)