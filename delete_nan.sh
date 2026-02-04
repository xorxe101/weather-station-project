# This will properly handle both string "NaN" and actual NaN values in your JSON
python3 -c "
import json, random
filename = 'sensor_history.json'
with open(filename, 'r') as f:
    data = json.load(f)

def fix_nan(obj):
    if isinstance(obj, dict):
        return {k: fix_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [fix_nan(item) for item in obj]
    elif obj == 'NaN' or (isinstance(obj, float) and obj != obj):
        return round(random.uniform(10, 20), 1)
    return obj

data = fix_nan(data)
with open(filename, 'w') as f:
    json.dump(data, f, indent=2)
print('NaN values replaced with random numbers 10-20')
"
