from sqlalchemy import text
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session, Response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
from dotenv import load_dotenv
from threading import Thread # <--- ΠΡΟΣΘΕΣΕ ΑΥΤΟ
from datetime import datetime, timedelta
import pymysql, re, time, threading, json, os, random, psutil, platform, socket, requests

# --- FIX: FORCE IPv4 FOR GMAIL (ΛΥΣΗ ΓΙΑ ΤΗΝ ΚΑΘΥΣΤΕΡΗΣΗ) ---
# Το Raspberry Pi συχνά κολλάει προσπαθώντας να βρει το Gmail μέσω IPv6.
# Αυτό αναγκάζει το πρόγραμμα να χρησιμοποιεί μόνο IPv4.
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        family = socket.AF_INET # Force IPv4
    return orig_getaddrinfo(host, port, family, type, proto, flags)

# Εφαρμογή του Fix μόνο αν χρησιμοποιούμε Gmail
if 'gmail.com' in os.environ.get('EMAIL_USER', '') or 'smtp.gmail.com' in 'smtp.gmail.com':
    socket.getaddrinfo = getaddrinfo_ipv4

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
    profile_icon = db.Column(db.String(50), default='user.png') # Νέο πεδίο για το εικονίδιο προφίλ

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

# Πρόσθεσέ το κάτω από την class SavedMoment(db.Model):

class SensorReading(db.Model):
    __tablename__ = 'sensor_readings'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True) # Index για γρήγορη αναζήτηση με βάση το χρόνο
    
    # Τα πεδία όπως φαίνονται στο JSON σου
    air_temp = db.Column(db.Float)
    soil_temp = db.Column(db.Float)
    humidity = db.Column(db.Float)
    wind_speed = db.Column(db.Float)
    wind_direction = db.Column(db.Float)
    rainfall = db.Column(db.Float)
    rain_rate = db.Column(db.Float)
    dew_point = db.Column(db.Float)
    pressure = db.Column(db.Float)

    def to_dict(self):
        """Βοηθητική συνάρτηση για να μετατρέπουμε την εγγραφή σε μορφή που καταλαβαίνει το JavaScript"""
        return {
            "Time": self.timestamp.isoformat(),
            "Air Temperature": self.air_temp,
            "Soil Temperature": self.soil_temp,
            "Humidity": self.humidity,
            "WindSpeed": self.wind_speed,
            "WindDirection": self.wind_direction,
            "RainFall": self.rainfall,
            "RainRate": self.rain_rate,
            "DewPoint": self.dew_point,
            "Pressure": self.pressure
        }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# SENSOR LOGIC (DB VERSION)
# ==========================================

def get_sensor_data():
    try:
        # 1. Παίρνουμε την τελευταία εγγραφή (Latest)
        latest_reading = SensorReading.query.order_by(SensorReading.timestamp.desc()).first()
        
        # 2. Παίρνουμε το ιστορικό (π.χ. τελευταίες 288 εγγραφές = 24 ώρες αν μετράς κάθε 5 λεπτά)
        # Μπορείς να αλλάξεις το όριο ανάλογα πόσο ιστορικό θες στα γραφήματα
        history_query = SensorReading.query.order_by(SensorReading.timestamp.asc()).limit(288).all()

        if latest_reading:
            return {
                "latest": latest_reading.to_dict(),
                "history": [r.to_dict() for r in history_query] # Μετατροπή σε λίστα για JSON
            }
            
    except Exception as e:
        print(f"Database Read Error: {e}")
    
    # Fallback αν η βάση είναι άδεια
    return {"latest": {}, "history": []}

# --- ΒΑΣΙΚΕΣ ΡΥΘΜΙΣΕΙΣ ΚΑΜΕΡΑΣ ΓΙΑ ΤΟ FRONTEND ---
CAMERA_ACTIVE = os.environ.get('CAMERA_STATUS', 'False').lower() == 'true'
CAMERA_WIDTH = int(os.environ.get('WIDTH_CAMERA'))
CAMERA_HEIGHT = int(os.environ.get('HEIGHT_CAMERA'))

# --- GLOBAL ΜΕΤΑΒΛΗΤΗ ΓΙΑ ΤΟ KILL SWITCH ΤΗΣ ΚΑΜΕΡΑΣ ---
active_proxies = {}

# --- ΝΕΑ ΑΣΥΓΧΡΟΝΗ ΑΠΟΣΤΟΛΗ EMAIL ---

# 1. Η συνάρτηση που τρέχει στο παρασκήνιο
def send_async_email(app, msg):
    with app.app_context():
        print(f"📧 [Thread] Trying to connect to Gmail ({app.config['MAIL_SERVER']})...")
        try:
            start_time = time.time()
            mail.send(msg)
            duration = round(time.time() - start_time, 2)
            print(f"✅ [Thread] Email sent successfully in {duration} seconds!")
        except Exception as e:
            print(f"❌ [Thread] FAILED to send email: {e}")
            # Αν αποτύχει, δοκίμασε να τυπώσεις τι φταίει
            if "Connection unexpectedly closed" in str(e):
                print("💡 Hint: Ελέγξτε το App Password ή αν το Firewall μπλοκάρει την πόρτα 587.")

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

def check_password_strength(password):
    """
    Ελέγχει αν ο κωδικός πληροί τα σύγχρονα πρότυπα ασφαλείας.
    Επιστρέφει (True, "") αν είναι ασφαλής, ή (False, "Μήνυμα Λάθους") αν δεν είναι.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter (A-Z)"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter (a-z)"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number (0-9)"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character (e.g., !@#$%^&*)"
    
    return True, ""

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html', current_user=current_user, camera_active=CAMERA_ACTIVE, cam_width=CAMERA_WIDTH, cam_height=CAMERA_HEIGHT)

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js')

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
        
        # --- ΝΕΟ: ΕΛΕΓΧΟΣ ΙΣΧΥΟΣ ΚΩΔΙΚΟΥ ---
        is_strong, error_msg = check_password_strength(password)
        if not is_strong:
            flash(error_msg, 'danger')
            return redirect(url_for('reset_token', token=token))

        hashed_pw = generate_password_hash(password, method='sha256')
        user.password = hashed_pw
        db.session.commit()
        
        flash('Your password has been updated. You are now able to log in', 'success')
        return render_template('reset_token.html', success=True)
        
    return render_template('reset_token.html', success=False)

# --- ΡΥΘΜΙΣΗ ΧΡΟΝΟΥ OTP (Στην αρχή του αρχείου ή μαζί με τα configs) ---
OTP_VALIDITY_SECONDS = 300  # 5 Λεπτά

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')

        if not email or email.strip() == "":
            flash('Email is required for verification', 'danger')
            return render_template('signup.html', username=username, email=email)

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return render_template('signup.html', username=username, email=email)

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return render_template('signup.html', username=username, email=email)
        
        # --- ΝΕΟ: ΕΛΕΓΧΟΣ ΙΣΧΥΟΣ ΚΩΔΙΚΟΥ ---
        is_strong, error_msg = check_password_strength(password)
        if not is_strong:
            flash(error_msg, 'danger')
            return render_template('signup.html', username=username, email=email)

        # ΔΗΜΙΟΥΡΓΙΑ OTP
        otp = random.randint(100000, 999999)

        # Αποθηκεύουμε στο session ΚΑΙ την ώρα δημιουργίας (time.time())
        session['temp_user'] = {
            'username': username,
            'email': email,
            'password_hash': generate_password_hash(password, method='sha256'),
            'otp': otp,
            'otp_timestamp': time.time()  # <--- ΣΗΜΑΝΤΙΚΟ: Αποθήκευση ώρας
        }

        send_verification_email(email, otp)

        flash('A verification code has been sent to your email', 'info')
        return redirect(url_for('verify_email'))

    return render_template('signup.html')

@app.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    if 'temp_user' not in session:
        return redirect(url_for('signup'))

    # ΥΠΟΛΟΓΙΣΜΟΣ ΥΠΟΛΕΙΠΟΜΕΝΟΥ ΧΡΟΝΟΥ (Για το Frontend)
    current_time = time.time()
    start_time = session['temp_user'].get('otp_timestamp', 0)
    elapsed_time = current_time - start_time
    remaining_seconds = max(0, OTP_VALIDITY_SECONDS - int(elapsed_time))

    if request.method == 'POST':
        # 1. ΕΛΕΓΧΟΣ ΧΡΟΝΟΥ (Backend Security)
        if elapsed_time > OTP_VALIDITY_SECONDS:
            flash('Verification code expired. Please request a new one.', 'danger')
            # session.pop('temp_user', None) # Καθαρισμός
            return redirect(url_for('verify_email')) # Απλά κάνε refresh για να δει το κουμπί Resend

        user_otp = request.form.get('otp')
        stored_otp = str(session['temp_user']['otp'])

        if user_otp == stored_otp:
            data = session['temp_user']
            new_user = User(
                username=data['username'],
                email=data['email'],
                password=data['password_hash']
            )
            db.session.add(new_user)
            db.session.commit()
            session.pop('temp_user', None)
            flash('Account created successfully! You can now login', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid verification code. Please try again', 'danger')

    # Περνάμε το remaining_seconds στο HTML
    return render_template('verify_email.html', remaining_seconds=remaining_seconds)

@app.route('/resend_verification_code')
def resend_verification_code():
    if 'temp_user' not in session:
        flash('Session expired. Please register again.', 'danger')
        return redirect(url_for('signup'))
    
    # 1. Δημιουργία ΝΕΟΥ κωδικού
    new_otp = random.randint(100000, 999999)
    
    # 2. Ενημέρωση του Session (κρατάμε τα στοιχεία, αλλάζουμε OTP και ώρα)
    session['temp_user']['otp'] = new_otp
    session['temp_user']['otp_timestamp'] = time.time()
    session.modified = True # Σημαντικό για να καταλάβει το Flask ότι άλλαξε το dict
    
    # 3. Αποστολή Email
    email = session['temp_user']['email']
    send_verification_email(email, new_otp)
    
    flash('A new verification code has been sent!', 'success')
    return redirect(url_for('verify_email'))

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
                return render_template('login.html', username=username)

            login_user(user, remember=True)
            if request.is_json: return jsonify({"success": True})
            return redirect(url_for('index'))
        else:
            if request.is_json: return jsonify({"success": False, "error": "Invalid credentials"}), 401
            flash('Invalid username or password')
            return render_template('login.html', username=username)

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
        
        # --- ΝΕΟ: ΕΛΕΓΧΟΣ ΙΣΧΥΟΣ ΚΩΔΙΚΟΥ ---
        is_strong, error_msg = check_password_strength(new_pw)
        if not is_strong:
            flash(error_msg, 'error')
            return redirect(url_for('profile'))
        
        # 3. ΕΠΙΤΥΧΙΑ: Αλλαγή κωδικού
        current_user.password = generate_password_hash(new_pw, method='sha256')
        db.session.commit()
        flash('Password updated successfully', 'success')
        return redirect(url_for('profile'))
    
    # --- ΑΛΓΟΡΙΘΜΟΣ ΑΥΤΟΜΑΤΗΣ ΑΝΑΓΝΩΣΗΣ ΕΙΚΟΝΙΔΙΩΝ (GET) ---
    icon_folder = os.path.join(app.static_folder, 'img_icon', 'profile_img') # Ο φάκελος με τα εικονίδια
    
    # Διαβάζει όλα τα αρχεία εικόνων από τον φάκελο
    avatars = []
    if os.path.exists(icon_folder):
        avatars = [f for f in os.listdir(icon_folder) if f.lower().endswith(('.png'))]
        avatars.sort() # Αλφαβητική ταξινόμηση
    
    return render_template('profile.html', current_user=current_user, avatars=avatars)

@app.route('/api/request_email_change', methods=['POST'])
@login_required
def request_email_change():
    # --- ΠΡΟΣΤΑΣΙΑ ADMIN ---
    if current_user.username in ['Admin', 'admin']:
        return jsonify({"success": False, "error": "Administrator email cannot be changed"}), 403
    
    data = request.json
    new_email = data.get('new_email')

    if not new_email:
        return jsonify({"success": False, "error": "Please enter an email address"}), 400

    if new_email == current_user.email:
         return jsonify({"success": False, "error": "This is already your email address"}), 400

    # Ελέγχουμε αν το νέο email υπάρχει ήδη σε άλλον χρήστη
    if User.query.filter_by(email=new_email).first():
        return jsonify({"success": False, "error": "This email is already registered to another account"}), 400

    # Δημιουργούμε το 6-ψήφιο OTP
    otp = random.randint(100000, 999999)
    
    # Το αποθηκεύουμε προσωρινά στο session
    session['email_change'] = {
        'new_email': new_email,
        'otp': str(otp),
        'timestamp': time.time()
    }

    # Στέλνουμε το OTP χρησιμοποιώντας τη συνάρτηση που ήδη έχεις!
    send_verification_email(new_email, otp)

    return jsonify({"success": True, "message": "OTP sent successfully"})

@app.route('/api/verify_email_change', methods=['POST'])
@login_required
def verify_email_change():
    data = request.json
    user_otp = data.get('otp')

    if 'email_change' not in session:
        return jsonify({"success": False, "error": "No pending email change request"}), 400

    session_data = session['email_change']

    # Ελέγχουμε αν το OTP έχει λήξει (π.χ. μετά από 5 λεπτά = 300 δευτερόλεπτα)
    if time.time() - session_data['timestamp'] > 300:
        session.pop('email_change', None)
        return jsonify({"success": False, "error": "OTP has expired. Please try again"}), 400

    # Ελέγχουμε αν το OTP είναι σωστό
    if user_otp != session_data['otp']:
        return jsonify({"success": False, "error": "Invalid verification code"}), 400

    # ΑΝ ΕΙΝΑΙ ΟΛΑ ΣΩΣΤΑ: Ενημερώνουμε το email στη Βάση Δεδομένων!
    current_user.email = session_data['new_email']
    db.session.commit()
    
    # Καθαρίζουμε το session
    session.pop('email_change', None)

    return jsonify({"success": True, "message": "Email updated successfully!"})

@app.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    new_icon = request.form.get('profile_icon')
    if new_icon:
        current_user.profile_icon = new_icon
        db.session.commit()
        flash('Profile picture updated successfully!', 'success')
    return redirect(url_for('profile'))

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
    
@app.route('/video_feed')
def video_feed():
    if not CAMERA_ACTIVE:
        return "Camera is OFF", 404
        
    client_id = request.args.get('client_id')
    active_proxies[client_id] = True
        
    try:
        req = requests.get('http://127.0.0.1:8081/stream', stream=True, timeout=10)
        
        def generate_and_close():
            try:
                for chunk in req.iter_content(chunk_size=4096):
                    # ΕΔΩ ΕΙΝΑΙ Η ΜΑΓΕΙΑ: Αν η JS έστειλε εντολή Stop, σπάμε το loop με το ζόρι!
                    if client_id and not active_proxies.get(client_id, True):
                        break
                        
                    if chunk:
                        yield chunk
            finally:
                req.close() # Κλείνει η σύνδεση με το ustreamer
                active_proxies.pop(client_id, None)

        return Response(generate_and_close(), content_type=req.headers.get('Content-Type'))
    except Exception as e:
        print(f"Ustreamer Proxy Error: {e}")
        return "Camera Proxy Error", 500

@app.route('/api/stop_camera', methods=['POST'])
def stop_camera_api():
    data = request.get_json()
    client_id = data.get('client_id') if data else None
    
    # Τραβάμε την πρίζα! Λέμε στον proxy να σταματήσει να διαβάζει.
    if client_id in active_proxies:
        active_proxies[client_id] = False 
        
    return jsonify({"success": True})

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