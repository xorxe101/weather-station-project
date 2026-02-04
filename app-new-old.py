from flask import Flask, jsonify, render_template
import mysql.connector
from datetime import datetime, timedelta
import bme280
import smbus2
import time
import glob
import threading
from time import sleep
import threading
import random  # For simulating sensor data - remove in production
import requests  # If you need to call external APIs for sensors

app = Flask(__name__)

# Global variables to store latest sensor data
latest_sensor_data = {}
sensor_history = []
MAX_HISTORY = 1440  # Store 24 hours of data (1 reading per minute)

# Add a lock to prevent simultaneous sensor readings
sensor_lock = threading.Lock()

# === Sensor Reading Functions ===

def read_temphumpres_sensor():
    """Read temperature/humidity/pressure from sensor"""
    port = 1
    address = 0x77
    bus = smbus2.SMBus(port)
    bme280.load_calibration_params(bus, address)
    data = bme280.sample(bus, address)
    return {
        'temperature': round(data.temperature, 1),
        'humidity': round(data.humidity, 1),
        'pressure': round(data.pressure, 1)
    }
    
    # Simulated data for testing
    # return round(random.uniform(15.0, 30.0), 1)
    # return {
    #   'temperature': round(random.uniform(15.0, 30.0), 1),
    #   'humidity': round(random.uniform(40.0, 80.0), 1),
    #   'pressure': round(random.uniform(1000.0, 1020.0), 1)
    # }

def read_wind_speed_sensor():
    """Read wind speed from sensor"""
    # Replace with actual sensor code
    return round(random.uniform(0.0, 20.0), 1)

def read_wind_direction_sensor():
    """Read wind direction from sensor"""
    # Replace with actual sensor code
    return round(random.uniform(0, 360), 1)

def read_rain_sensor():
    """Read rain data from sensor"""
    # Replace with actual sensor code
    return {
        'rain_fall': round(random.uniform(0.0, 5.0), 1),
        'rain_rate': round(random.uniform(0.0, 10.0), 1)
    }

def read_soil_temperature_sensor():
    """Read soil temperature from sensor"""
    try:
        class DS18B20:
            def __init__(self):
                self.device_file = glob.glob("/sys/bus/w1/devices/28*")[0] + "/w1_slave"

            def read_temp(self):
                for _ in range(3):
                    with open(self.device_file, "r") as f:
                        lines = f.readlines()
                    if lines[0].strip().endswith("YES"):
                        temp_string = lines[1].split("t=")[1]
                        return round(float(temp_string) / 1000.0, 1)
                return -255
        return DS18B20().read_temp()
    except Exception as e:
        print("Ground sensor error. Returning random value")
        return round(random.uniform(20.0, 25.0), 1)  # fallback simulated value
    # return round(random.uniform(10.0, 25.0), 1)

def read_dew_point_sensor():
    """Calculate dew point from temperature and humidity"""
    # Replace with actual sensor reading or calculation
    thp = read_temphumpres_sensor()
    temp = thp['temperature']
    humidity = thp['humidity']
    # Simple dew point calculation
    dew_point = temp - ((100 - humidity) / 5)
    return round(dew_point, 1)

def read_all_sensors():
    """Read all sensors and return combined data"""
    global latest_sensor_data
    
    with sensor_lock:
        print(f"Reading sensors from thread: {threading.current_thread().name}")
    
        try:
            # Read all sensors
            thp = read_temphumpres_sensor()
            temperature = thp['temperature']
            humidity = thp['humidity']
            pressure = thp['pressure']
            wind_speed = read_wind_speed_sensor()
            wind_direction = read_wind_direction_sensor()
            rain_data = read_rain_sensor()
            soil_temperature = read_soil_temperature_sensor()
            dew_point = read_dew_point_sensor()
            
            sensor_data = {
                'Time': datetime.now().isoformat(),
                'Air Temperature': temperature,
                'Soil Temperature': soil_temperature,
                'Humidity': humidity,
                'WindSpeed': wind_speed,
                'WindDirection': wind_direction,
                'RainFall': rain_data['rain_fall'],
                'RainRate': rain_data['rain_rate'],
                'DewPoint': dew_point,
                'Pressure': pressure
                # AM Temperature removed
            }
            
            latest_sensor_data = sensor_data
            
            # Add to history
            sensor_history.append(sensor_data)
            
            # Keep only the last MAX_HISTORY entries
            if len(sensor_history) > MAX_HISTORY:
                sensor_history.pop(0)
                
            print(f"Sensor data updated at {datetime.now().strftime('%H:%M:%S')}: {sensor_data}")
            
        except Exception as e:
            print(f"Error reading sensors: {e}")

# === Background Thread for Sensor Reading ===

def sensor_reading_loop():
    """More precise version that always calculates next exact minute"""
    print("Waiting for next exact minute (0 seconds) to start first reading...")
    
    # Wait for exact minute before first reading
    now = datetime.now()
    if now.second != 0:
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        sleep_seconds = (next_minute - now).total_seconds()
        print(f"Waiting {sleep_seconds:.1f} seconds until first reading at {next_minute.strftime('%H:%M:%S')}")
        sleep(sleep_seconds)
    
    print(f"Starting first sensor reading at exact minute: {datetime.now().strftime('%H:%M:%S')}")
    read_all_sensors()
    
    # Main loop - always calculate next exact minute
    while True:
        # Calculate next exact minute
        now = datetime.now()
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        sleep_seconds = (next_minute - now).total_seconds()
        
        # Wait for next exact minute
        sleep(sleep_seconds)
        
        # Take reading
        read_all_sensors()
        print(f"Sensor reading at {datetime.now().strftime('%H:%M:%S')}")

# === Database Connection ===

def connect_db():
    return mysql.connector.connect(
        user='weather',
        password='station', 
        host='localhost',
        database='weather'
    )

def log_to_database():
    """Optional: Log sensor data to database"""
    try:
        cnx = connect_db()
        cur = cnx.cursor()
        
        data = latest_sensor_data
        query = """
        INSERT INTO Weather 
        (`Time`, `Air Temperature`, `Soil Temperature`, `Humidity`, `WindSpeed`, 
         `WindDirection`, `RainFall`, `RainRate`, `DewPoint`, `Pressure`)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        values = (
            datetime.now(),
            data.get('Air Temperature'),
            data.get('Soil Temperature'), 
            data.get('Humidity'),
            data.get('WindSpeed'),
            data.get('WindDirection'),
            data.get('RainFall'),
            data.get('RainRate'),
            data.get('DewPoint'),
            data.get('Pressure')
        )
        
        cur.execute(query, values)
        cnx.commit()
        cur.close()
        cnx.close()
        print("Data logged to database")
        
    except Exception as e:
        print(f"Error logging to database: {e}")

# === Flask Routes ===

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/latest')
def latest_data():
    """Return latest sensor data from memory"""
    if not latest_sensor_data:
        return database_latest_data()
    
    return jsonify(latest_sensor_data)

@app.route('/api/history')
def history_data():
    """Return historical sensor data from memory"""
    if not sensor_history:
        return database_history_data()
    
    return jsonify(sensor_history[-100:])

@app.route('/api/refresh')
def manual_refresh():
    """Manual endpoint to refresh sensor data"""
    read_all_sensors()
    return jsonify({"status": "sensors refreshed", "data": latest_sensor_data})

@app.route('/api/status')
def system_status():
    """Check system and sensor status"""
    status = {
        'sensor_data_available': bool(latest_sensor_data),
        'history_count': len(sensor_history),
        'last_reading_time': latest_sensor_data.get('Time') if latest_sensor_data else None,
        'system_time': datetime.now().isoformat()
    }
    return jsonify(status)

# === Database Fallback Routes ===

def database_latest_data():
    """Fallback to database if sensors aren't working"""
    cnx = connect_db()
    cur = cnx.cursor(dictionary=True)
    
    cur.execute("SELECT * FROM Weather ORDER BY Time DESC LIMIT 1")
    row = cur.fetchone()
    cur.close()
    cnx.close()
    
    if row:
        for key, value in row.items():
            if isinstance(value, datetime):
                row[key] = value.isoformat()
            elif isinstance(value, timedelta):
                row[key] = str(value)
    
    return jsonify(row)

def database_history_data():
    """Fallback to database history if sensor history is empty"""
    cnx = connect_db()
    cur = cnx.cursor(dictionary=True)
    
    cur.execute("SELECT `Time`, `Air Temperature` AS temp, `Soil Temperature` AS ground_temp, "
                "`Humidity`, `Pressure`, `WindSpeed`, `WindDirection`, `RainFall`, `RainRate`, `DewPoint` "
                "FROM Weather ORDER BY Time DESC LIMIT 100")
    rows = cur.fetchall()
    cur.close()
    cnx.close()
    
    for row in rows:
        if isinstance(row['Time'], datetime):
            row['Time'] = row['Time'].isoformat()
    
    return jsonify(rows)

# === Application Startup ===

if __name__ == '__main__':
    print("Weather Station starting...")
    print("Waiting for exact minute (0 seconds) to begin first sensor reading")
    
    # Start the precise sensor monitoring thread
    print("Starting precise sensor monitoring...")
    sensor_thread = threading.Thread(target=sensor_reading_loop, daemon=True)  # Use the precise version
    sensor_thread.start()
    
    print("Sensor monitoring started. Readings will occur at exact minutes (XX:00, XX:01, XX:02, etc.)")
    app.run(debug=True, host='0.0.0.0', port=5000)
