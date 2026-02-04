import random, smbus2, bme280, glob, math
from datetime import datetime

# === Initialize values for dew point calculation ===
b = 17.625
c = 243.04  # b, c values for range [-40, +50] degrees Celcius

class SensorReader:
    def __init__(self):
        self.i2c_bus = None
        self._init_i2c()
    
    def _init_i2c(self):
        """Initialize I2C bus once"""
        try:
            self.i2c_bus = smbus2.SMBus(1)
            print("I2C bus initialized")
        except Exception as e:
            print(f"Error initializing I2C bus: {e}")
            self.i2c_bus = None
    
    def read_bme280(self):
        """Read BME280 sensor (temperature, humidity, pressure)"""
        try:
            if self.i2c_bus:
                # Load calibration once
                if not hasattr(self, 'bme_calibrated'):
                    bme280.load_calibration_params(self.i2c_bus, 0x77)
                    self.bme_calibrated = True
                
                data = bme280.sample(self.i2c_bus, 0x77)
                return {
                    'temperature': round(data.temperature, 1),
                    'humidity': round(data.humidity, 1),
                    'pressure': round(data.pressure, 1)
                }
        except Exception as e:
            print(f"BME280 read error: {e}")
        
        # Return NaN for all values if sensor fails
        return {
            'temperature': float('nan'),
            'humidity': float('nan'),
            'pressure': float('nan')
        }
    
    def read_temp_ground(self):
        """Read ground temperature from DS18B20 sensor"""
        try:
            device_files = glob.glob("/sys/bus/w1/devices/28*/w1_slave")
            if not device_files:
                print("No DS18B20 sensor found - no device files matching pattern")
                return float('nan')
                
            device_file = device_files[0]
            # print(f"Found DS18B20 sensor at: {device_file}")
            
            for attempt in range(3):  # Try up to 3 times
                try:
                    with open(device_file, "r") as f:
                        lines = f.readlines()
                    
                    if len(lines) >= 2 and lines[0].strip().endswith("YES"):
                        temp_string = lines[1].split("t=")[1]
                        temp_value = float(temp_string) / 1000.0
                        if temp_value > 50:
                            return float('nan')
                        # print(f"DS18B20 read successful: {temp_value}°C")
                        return round(temp_value, 1)
                    else:
                        print(f"DS18B20 read attempt {attempt + 1}: CRC check failed")
                        
                except Exception as e:
                    print(f"DS18B20 read attempt {attempt + 1} failed: {e}")
            
            print("DS18B20 sensor read failed after 3 attempts")
            return float('nan')
            
        except Exception as e:
            print(f"Ground sensor error: {e}")
            return float('nan')
    
    def read_wind_speed(self):
        """Read wind speed (placeholder - replace with actual sensor code)"""
        try:
            # Replace this with your actual wind speed sensor code
            # For now, using random data but you can simulate failures
            return round(random.uniform(0.0, 20.0), 1)
        except Exception as e:
            print(f"Wind speed sensor error: {e}")
            return float('nan')
    
    def read_wind_direction(self):
        """Read wind direction (placeholder - replace with actual sensor code)"""
        try:
            # Replace this with your actual wind direction sensor code
            return round(random.uniform(0, 360), 1)
        except Exception as e:
            print(f"Wind direction sensor error: {e}")
            return float('nan')
    
    def read_rain(self):
        """Read rain data (placeholder - replace with actual sensor code)"""
        try:
            # Replace this with your actual rain sensor code
            return {
                'rain_fall': round(random.uniform(0.0, 5.0), 1),
                'rain_rate': round(random.uniform(0.0, 10.0), 1)
            }
        except Exception as e:
            print(f"Rain sensor error: {e}")
            return {
                'rain_fall': float('nan'),
                'rain_rate': float('nan')
            }
    
    def calculate_dew_point(self, temperature, humidity):
        """Calculate dew point from temperature and humidity"""
        try:
            # Check if inputs are valid numbers before calculation
            if math.isnan(temperature) or math.isnan(humidity):
                return float('nan')
                
            g = math.log(humidity/100) + (b * temperature) / (c + temperature)  # γ function
            dew_point = (c * g) / (b - g)   # Tdry function
            return round(dew_point, 1)
        except Exception as e:
            print(f"Dew point calculation error: {e}")
            return float('nan')
    
    def read_all_sensors(self):
        """Read all sensors and return combined data with NaN for failures"""
        try:
            # Read BME280
            bme_data = self.read_bme280()
            temperature = bme_data['temperature']
            humidity = bme_data['humidity']
            pressure = bme_data['pressure']
            
            # Read other sensors
            temp_ground = self.read_temp_ground()
            wind_speed = self.read_wind_speed()
            wind_direction = self.read_wind_direction()
            rain_data = self.read_rain()
            dew_point = self.calculate_dew_point(temperature, humidity)
            
            sensor_data = {
                'Time': datetime.now().isoformat(),
                'Air Temperature': temperature,
                'Soil Temperature': temp_ground,
                'Humidity': humidity,
                'WindSpeed': wind_speed,
                'WindDirection': wind_direction,
                'RainFall': rain_data['rain_fall'],
                'RainRate': rain_data['rain_rate'],
                'DewPoint': dew_point,
                'Pressure': pressure
            }
            
            print(f"Sensors read: {sensor_data}")
            return sensor_data
            
        except Exception as e:
            print(f"Error reading sensors: {e}")
            # Return a complete dataset with NaN values if overall read fails
            return {
                'Time': datetime.now().isoformat(),
                'Air Temperature': float('nan'),
                'Soil Temperature': float('nan'),
                'Humidity': float('nan'),
                'WindSpeed': float('nan'),
                'WindDirection': float('nan'),
                'RainFall': float('nan'),
                'RainRate': float('nan'),
                'DewPoint': float('nan'),
                'Pressure': float('nan')
            }

# Global instance
sensor_reader = SensorReader()