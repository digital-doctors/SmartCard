from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import requests
import json
import os

app = Flask(__name__)
app.secret_key = "9866c563db3cbf4b76493ed64a91b72c"  # CHANGE THIS before deployment!

# ======= Static fallback merchant list =======
MERCHANTS = [
    (40.741895, -73.989308, "Dining", "Starbucks"),
    (40.758896, -73.985130, "Gas", "Shell Station"),
    (40.730610, -73.935242, "Groceries", "Whole Foods Market"),
    (40.752726, -73.977229, "Travel", "Port Authority Bus Terminal"),
    (40.712776, -74.005974, "Dining", "Shake Shack"),
]

FOURSQUARE_API_KEY = "NVSJSAPKIFDTDMGJ3O2PDUE3WEBDITCJBOU5PGYWLLXWZXQR"
USERS_FILE = "users.json"




# ======= Utility functions for user data =======
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


# ======= Merchant detection functions =======
def get_merchant_foursquare(lat, lon, api_key):
    url = "https://api.foursquare.com/v3/places/search"
    headers = {"Authorization": api_key}
    params = {"ll": f"{lat},{lon}", "radius": 100, "limit": 1}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=3)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                merchant = results[0]
                name = merchant.get("name")
                categories = merchant.get("categories", [])
                fsq_cat = categories[0]['name'].lower() if categories else ""
                if any(x in fsq_cat for x in ["restaurant", "cafe", "food"]):
                    category = "Dining"
                elif any(x in fsq_cat for x in ["gas", "fuel"]):
                    category = "Gas"
                elif any(x in fsq_cat for x in ["grocery", "supermarket"]):
                    category = "Groceries"
                elif any(x in fsq_cat
                         for x in ["travel", "station", "airport"]):
                    category = "Travel"
                else:
                    category = "Other"
                return category, name
    except Exception as e:
        print("Foursquare API error:", e)
    return None, None


def detect_merchant_overpass(lat, lon):
    query = f"""
    [out:json][timeout:3];
    (
      node(around:100,{lat},{lon})["amenity"~"restaurant|cafe|fast_food|fuel|supermarket|bus_station|train_station|airport"];
      way(around:100,{lat},{lon})["amenity"~"restaurant|cafe|fast_food|fuel|supermarket|bus_station|train_station|airport"];
      relation(around:100,{lat},{lon})["amenity"~"restaurant|cafe|fast_food|fuel|supermarket|bus_station|train_station|airport"];
    );
    out center 1;
    """
    try:
        r = requests.post("https://overpass-api.de/api/interpreter",
                          data=query,
                          timeout=5)
        data = r.json()
        elements = data.get("elements", [])
        if not elements:
            return None, None
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name")
            amenity = tags.get("amenity")
            if not name or not amenity:
                continue
            if amenity in ("restaurant", "cafe", "fast_food"):
                return "Dining", name
            elif amenity == "fuel":
                return "Gas", name
            elif amenity == "supermarket":
                return "Groceries", name
            elif amenity in ("bus_station", "train_station", "airport"):
                return "Travel", name
        first = elements[0]
        tags = first.get("tags", {})
        return "Other", tags.get("name", "Unknown")
    except Exception as e:
        print("Overpass API error:", e)
        return None, None


def detect_merchant_fallback(lat, lon):
    for mlat, mlon, category, name in MERCHANTS:
        dist = ((lat - mlat)**2 + (lon - mlon)**2)**0.5
        if dist < 0.001:
            return category, name
    return None, None


# ======= Routes =======
@app.route('/')
def root():
    if 'user' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_users()
        email = request.form.get('email')
        password = request.form.get('password')

        if email in users and users[email]['password'] == password:
            session['user'] = email
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        users = load_users()
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone_number')
        dob = request.form.get('dob')
        address = request.form.get('address')

        if email in users:
            return render_template('register.html',
                                   error="Email already registered")

        users[email] = {
            'password': password,
            'phone_number': phone,
            'dob': dob,
            'address': address,
            'cards': []
        }
        save_users(users)
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user_email = session['user']
    user = users.get(user_email, {})
    name = user_email.split('@')[0]  # or use a stored name if you collect it

    return render_template('index.html', name=name)


@app.route('/add')
def add_card_page():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('add.html')


@app.route('/cards', methods=['GET', 'POST'])
def manage_cards():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    users = load_users()
    user_email = session['user']

    if user_email not in users:
        return jsonify({'error': 'User not found'}), 404

    if 'cards' not in users[user_email]:
        users[user_email]['cards'] = []

    if request.method == 'POST':
        data = request.json
        if data.get('delete'):
            users[user_email]['cards'] = [
                c for c in users[user_email]['cards']
                if c['name'] != data['name']
            ]
        else:
            if all(k in data for k in ('name', 'cardHolder', 'category',
                                       'rewardPercent')):
                new_card = {
                    'name': data['name'],
                    'cardHolder': data['cardHolder'],
                    'category': data['category'],
                    'rewardPercent': float(data['rewardPercent'])
                }
                users[user_email]['cards'].append(new_card)
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Missing card fields'
                }), 400
        save_users(users)
        return jsonify({'status': 'success'})

    else:
        return jsonify(users[user_email].get('cards', []))


@app.route('/recommend', methods=['POST'])
def recommend():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    lat = data.get('lat')
    lon = data.get('lon')
    if lat is None or lon is None:
        return jsonify({'error': 'Missing lat or lon'}), 400

    addr = "Unknown"
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
                         params={
                             "lat": lat,
                             "lon": lon,
                             "format": "jsonv2"
                         },
                         headers={"User-Agent": "SmartCardApp/1.0"},
                         timeout=3)
        if r.status_code == 200:
            j = r.json()
            addr = j.get("display_name", "Unknown")
    except Exception:
        pass

    category, merchant_name = get_merchant_foursquare(lat, lon,
                                                      FOURSQUARE_API_KEY)
    if not category:
        category, merchant_name = detect_merchant_overpass(lat, lon)
    if not category:
        category, merchant_name = detect_merchant_fallback(lat, lon)

    if not category:
        return jsonify({
            "address": addr,
            "message": "No merchant found nearby."
        })

    users = load_users()
    user_cards = users.get(session['user'], {}).get('cards', [])
    filtered_cards = [c for c in user_cards if c['category'] == category]

    if not filtered_cards:
        return jsonify({
            "address": addr,
            "message": f"No card for {category} category."
        })

    best_card = max(filtered_cards, key=lambda c: c['rewardPercent'])
    return jsonify({
        "address":
        addr,
        "message":
        f"You're near {merchant_name}. Use {best_card['name']} for {best_card['rewardPercent']}% back!"
    })


@app.route('/api/profile')
def api_profile():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    users = load_users()
    email = session['user']
    user = users.get(email)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    profile = {
        "email": email,
        "phone_number": user.get('phone_number', ''),
        "dob": user.get('dob', ''),
        "address": user.get('address', ''),
    }
    return jsonify(profile)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
