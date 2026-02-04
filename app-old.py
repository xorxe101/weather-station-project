from flask import Flask, jsonify, render_template
import mysql.connector
from datetime import datetime, timedelta

app = Flask(__name__)

# === Database Connection ===
def connect_db():
    return mysql.connector.connect(
        user='weather',
        password='station',
        host='localhost',
        database='weather'
    )

# === Homepage ===
@app.route('/')
def index():
    return render_template('index.html')

# === Latest data ===
@app.route('/api/latest')
def latest_data():
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
                row[key] = str(value)  # ← Fix: convert timedelta to string

    return jsonify(row)

# === Historical data for graphs ===
@app.route('/api/history')
def history_data():
    cnx = connect_db()
    cur = cnx.cursor(dictionary=True)

    cur.execute("SELECT `Time`, `Air Temperature` AS temp, `Soil Temperature` AS ground_temp, "
                "`Humidity`, `Pressure`, `WindSpeed`, `WindDirection`, `RainFall`, `RainRate`, `DewPoint`, `Air Temperature (AM)` AS am_temp "
                "FROM Weather ORDER BY Time ASC")
    rows = cur.fetchall()
    cur.close()
    cnx.close()

    # Ensure Time and any objects are properly formatted
    for row in rows:
        if isinstance(row['Time'], datetime):
            row['Time'] = row['Time'].isoformat()

    return jsonify(rows)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')