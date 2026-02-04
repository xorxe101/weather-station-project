from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
import time
import threading
import json
import os

from sensor_reader import sensor_reader

app = Flask(__name__)

# Global variables - Store everything in memory
latest_sensor_data = {}
sensor_history = []
MAX_HISTORY = 6  # Keep last 6 readings (1 minute of 10-second data)

# File for persistence
HISTORY_FILE = 'sensor_history_test.json'

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

def exact_10_seconds_loop():
    """Run exactly every 10 seconds"""
    print("Waiting for next 10-second interval to start...")
    
    # Wait for first exact 10-second interval
    now = datetime.now()
    seconds_to_wait = 10 - (now.second % 10)
    if seconds_to_wait > 0:
        next_interval = now.replace(microsecond=0) + timedelta(seconds=seconds_to_wait)
        sleep_time = (next_interval - now).total_seconds()
        print(f"Waiting {sleep_time:.1f} seconds until {next_interval.strftime('%H:%M:%S')}")
        time.sleep(sleep_time)
    
    print(f"Starting sensor readings at: {datetime.now().strftime('%H:%M:%S')}")
    
    while True:
        # Read sensors (NO DATABASE)
        read_sensors()
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # Show progress
        if len(sensor_history) < MAX_HISTORY:
            progress = (len(sensor_history) / MAX_HISTORY) * 100
            print(f"Reading at: {current_time} - History: {len(sensor_history)}/{MAX_HISTORY} ({progress:.1f}%)")
        else:
            print(f"Reading at: {current_time} - History: {MAX_HISTORY}/{MAX_HISTORY} (100%)")
        
        # Wait for next 10-second interval
        now = datetime.now()
        seconds_to_wait = 10 - (now.second % 10)
        next_interval = now.replace(microsecond=0) + timedelta(seconds=seconds_to_wait)
        sleep_time = (next_interval - now).total_seconds()
        time.sleep(sleep_time)

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
    """Get full history (all available data)"""
    return jsonify(sensor_history)

@app.route('/api/history/last/<int:count>')
def get_history_count(count):
    """Get last N readings"""
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
        'reading_interval': '10 seconds'
    })

@app.route('/api/refresh')
def manual_refresh():
    """Manually trigger sensor reading"""
    success = read_sensors()
    return jsonify({
        "status": "sensors refreshed" if success else "sensor read failed",
        "data": latest_sensor_data,
        "history_size": len(sensor_history),
        "max_history": MAX_HISTORY
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

if __name__ == '__main__':
    # Load previous history if exists
    load_history()
    
    # Start the 10-second loop
    sensor_thread = threading.Thread(target=exact_10_seconds_loop, daemon=True)
    sensor_thread.start()
    
    print("Weather Dashboard started!")
    print(f"Reading every 10 seconds at exact intervals")
    print(f"Storing up to {MAX_HISTORY} readings in memory (~2.8 hours of 10-second data)")
    print(f"Current history: {len(sensor_history)}/{MAX_HISTORY} readings")
    print("No database connection - pure memory storage with file persistence")
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
