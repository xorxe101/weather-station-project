git add .                           # 1. Προετοιμασία όλων των αρχείων
git commit -m "Περιγραφή αλλαγών"    # 2. Τοπική αποθήκευση με μήνυμα
git push                            # 3. Ανέβασμα στο GitHub

git add static/style.css            # Προετοιμάζει μόνο το CSS
git commit -m "Fixed CSS colors"    # Κάνει commit μόνο αυτό
git push                            # Το ανεβάζει

git status                          # Σου δείχνει ποια αρχεία άλλαξαν και ποια είναι πράσινα (add)
git diff                            # Σου δείχνει ακριβώς ποιες γραμμές κώδικα άλλαξες
git log --oneline                   # Σου δείχνει το ιστορικό των τελευταίων commits σου

git checkout -- static/style.css    # Ακυρώνει τις αλλαγές στο αρχείο και το επαναφέρει όπως ήταν στο τελευταίο commit
git reset HEAD static/style.css     # "Ξε-πρασινίζει" ένα αρχείο αν το έκανες add κατά λάθος

# Ρύθμιση ταυτότητας (γίνεται μία φορά)
git config --global user.email "your@email.com"
git config --global user.name "YourUsername"

# Αποθήκευση Token για να μην το ζητάει συνέχεια
git config --global credential.helper store

# Οριστική λύση αν το token σου δημιουργεί προβλήματα (Remote URL)
git remote set-url origin https://Username:TOKEN@github.com/xorxe101/weather-station-project.git

# Δήλωση ασφαλούς φακέλου για το Git
git config --global add safe.directory /var/www/weather_app

# Επαναφορά δικαιωμάτων αν "χτυπήσει" ο Apache
sudo chown -R $USER:www-data /var/www/weather_app
sudo chmod -R 755 /var/www/weather_app
