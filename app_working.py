from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
import time, threading, json, os

from sensor_reader import sensor_reader

app = Flask(__name__)

# Configurable variables - CHANGE THIS TO SET YOUR INTERVAL
READING_INTERVAL_MINUTES = 5  # Set this to 1, 2, 3, 5, 10, 15, 20 or 30

# Global variables - Store everything in memory
latest_sensor_data = {}
sensor_history = []

# Calculate MAX_HISTORY based on interval (24 hours worth of data)
HOURS_TO_STORE = 24
MAX_HISTORY = (HOURS_TO_STORE * 60) // READING_INTERVAL_MINUTES  # Auto-calculate

# Use absolute path for persistence
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, 'sensor_history.json')

def load_history():
    """Load history from file if it exists"""
    global sensor_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                saved_history = json.load(f)
                # Keep only the last MAX_HISTORY entries
                sensor_history = saved_history[-MAX_HISTORY:]
            print(f"Loaded {len(sensor_history)} historical readings from file")
            print(f"Storage capacity: {MAX_HISTORY} readings ({HOURS_TO_STORE} hours at {READING_INTERVAL_MINUTES}-minute intervals)")
            
            # Show progress
            if len(sensor_history) < MAX_HISTORY:
                print(f"Need {MAX_HISTORY - len(sensor_history)} more readings to reach full history")
    except Exception as e:
        print(f"Error loading history: {e}")

def save_history():
    """Save history to file for persistence across restarts"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(sensor_history, f)
        print(f"Saved {len(sensor_history)} readings to file")
    except Exception as e:
        print(f"Error saving history: {e}")

def read_sensors():
    """Read sensors and update memory storage"""
    global latest_sensor_data, sensor_history
    
    sensor_data = sensor_reader.read_all_sensors()
    if sensor_data:
        latest_sensor_data = sensor_data
        sensor_history.append(sensor_data)
        
        # Keep only the last MAX_HISTORY entries
        if len(sensor_history) > MAX_HISTORY:
            sensor_history.pop(0)
        
        # Save every reading
        save_history()
        
        return True
    return False

def exact_interval_loop():
    """Run exactly at the configured interval, starting at the nearest divisible minute"""
    print(f"Waiting for next exact {READING_INTERVAL_MINUTES}-minute interval to start...")
    
    # Simple calculation: find next time where minutes % interval == 0
    now = datetime.now()
    current_minute = now.minute
    minutes_to_wait = READING_INTERVAL_MINUTES - (current_minute % READING_INTERVAL_MINUTES)
    
    next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_wait)
    seconds_to_wait = (next_time - now).total_seconds()
    
    print(f"Next reading at: {next_time.strftime('%H:%M:%S')}")
    print(f"Waiting {seconds_to_wait:.1f} seconds until next {READING_INTERVAL_MINUTES}-minute interval")
    
    if seconds_to_wait > 0:
        time.sleep(seconds_to_wait)
    
    print(f"Starting sensor readings at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Reading interval: {READING_INTERVAL_MINUTES} minutes")
    print(f"Storage: {MAX_HISTORY} readings ({HOURS_TO_STORE} hours)")
    
    while True:
        # Read sensors
        read_sensors()
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # Show progress towards full history
        if len(sensor_history) < MAX_HISTORY:
            progress = (len(sensor_history) / MAX_HISTORY) * 100
            print(f"Reading completed at: {current_time} - History: {len(sensor_history)}/{MAX_HISTORY} ({progress:.1f}%)")
        else:
            print(f"Reading completed at: {current_time} - History: {MAX_HISTORY}/{MAX_HISTORY} (100%)")
        
        # Wait for next exact interval
        now = datetime.now()
        current_minute = now.minute
        minutes_to_wait = READING_INTERVAL_MINUTES - (current_minute % READING_INTERVAL_MINUTES)
        next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_wait)
        seconds_to_wait = (next_time - now).total_seconds()
        time.sleep(seconds_to_wait)

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/latest')
def get_latest():
    """Get latest sensor reading"""
    return jsonify(latest_sensor_data if latest_sensor_data else {})

@app.route('/api/history')
def get_history():
    """Get historical sensor data (last N readings)"""
    # Return last MAX_HISTORY readings by default
    count = min(int(request.args.get('count', MAX_HISTORY)), 2000)
    return jsonify(sensor_history[-count:])

@app.route('/api/history/full')
def get_history_full():
    """Get full history (all available data up to MAX_HISTORY)"""
    return jsonify(sensor_history)

@app.route('/api/history/last/<int:count>')
def get_history_count(count):
    """Get last N readings (max MAX_HISTORY)"""
    count = min(count, MAX_HISTORY)
    return jsonify(sensor_history[-count:])

@app.route('/api/history/last/<int:hours>hours')
def get_history_hours(hours):
    """Get history from last X hours"""
    cutoff_time = datetime.now() - timedelta(hours=hours)
    filtered_history = [
        reading for reading in sensor_history 
        if datetime.fromisoformat(reading['Time']) >= cutoff_time
    ]
    return jsonify(filtered_history)

@app.route('/api/status')
def get_status():
    """Get system status"""
    history_percentage = (len(sensor_history) / MAX_HISTORY) * 100 if MAX_HISTORY > 0 else 0
    file_exists = os.path.exists(HISTORY_FILE)

    return jsonify({
        'latest_data_available': bool(latest_sensor_data),
        'history_count': len(sensor_history),
        'max_history': MAX_HISTORY,
        'history_percentage': round(history_percentage, 1),
        'history_file_exists': file_exists,
        'last_reading_time': latest_sensor_data.get('Time') if latest_sensor_data else None,
        'system_time': datetime.now().isoformat(),
        'reading_interval_minutes': READING_INTERVAL_MINUTES,
        'hours_stored': HOURS_TO_STORE,
        'data_points_per_hour': 60 // READING_INTERVAL_MINUTES,
        'reading_interval': f'{READING_INTERVAL_MINUTES} minute(s)'
    })

@app.route('/api/refresh')
def manual_refresh():
    """Manually trigger sensor reading"""
    success = read_sensors()
    return jsonify({
        "status": "sensors refreshed" if success else "sensor read failed",
        "data": latest_sensor_data,
        "history_size": len(sensor_history),
        "max_history": MAX_HISTORY,
        "interval_minutes": READING_INTERVAL_MINUTES
    })

@app.route('/api/save')
def manual_save():
    """Manually save history to file"""
    save_history()
    return jsonify({"status": "history saved", "entries": len(sensor_history)})

@app.route('/api/clear')
def clear_history():
    """Clear history (optional)"""
    global sensor_history
    sensor_history = []
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    return jsonify({"status": "history cleared"})

@app.route('/api/config')
def get_config():
    """Get current configuration"""
    return jsonify({
        'reading_interval_minutes': READING_INTERVAL_MINUTES,
        'hours_stored': HOURS_TO_STORE,
        'max_history': MAX_HISTORY,
        'data_points_per_hour': 60 // READING_INTERVAL_MINUTES,
        'total_storage_hours': HOURS_TO_STORE
    })

if __name__ == '__main__':
    # Validate interval
    valid_intervals = [1, 2, 3, 5, 10, 15, 20, 30]
    if READING_INTERVAL_MINUTES not in valid_intervals:
        print(f"Warning: {READING_INTERVAL_MINUTES} minutes is not a standard interval.")
        print(f"Recommended intervals: {valid_intervals}")
    
    # Load previous history if exists
    load_history()
    
    # Start the interval loop
    sensor_thread = threading.Thread(target=exact_interval_loop, daemon=True)
    sensor_thread.start()
    
    print("="*50)
    print("Weather Dashboard started!")
    print(f"Reading every {READING_INTERVAL_MINUTES} minute(s)")
    print(f"Current history: {len(sensor_history)}/{MAX_HISTORY} readings")
    print(f"Data points per hour: {60 // READING_INTERVAL_MINUTES}")
    print("No database connection - pure memory storage")
    print("="*50)
    
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)