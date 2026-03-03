#!/bin/bash

# 1. Φορτώνουμε τις μεταβλητές από το .env αρχείο
source /var/www/weather_app/.env

# 2. Ελέγχουμε αν η κάμερα είναι κλειστή (False)
if [ "$CAMERA_STATUS" != "True" ] && [ "$CAMERA_STATUS" != "true" ]; then
    echo "Η κάμερα είναι κλειστή (CAMERA_STATUS=$CAMERA_STATUS). Το service μπαίνει σε αναμονή."
    # Βάζουμε το script να "κοιμάται" για να μην το κάνει restart το systemd συνέχεια
    exec sleep infinity
fi

# 3. Παίρνουμε τις τιμές
FPS=${FPS_SETTINGS}
WIDTH=${WIDTH_CAMERA}
HEIGHT=${HEIGHT_CAMERA}

echo "Ξεκινάει το ustreamer με ανάλυση ${WIDTH}x${HEIGHT} στα ${FPS} FPS..."

# 5. Εκτελούμε το ustreamer με τις δυναμικές ρυθμίσεις
exec /usr/bin/ustreamer --device /dev/video0 --host 127.0.0.1 --port 8081 --resolution ${WIDTH}x${HEIGHT} --desired-fps ${FPS}