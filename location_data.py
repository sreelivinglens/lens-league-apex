# Location data for Lens League registration
# India: all states/UTs with major cities
# World: major countries with states/provinces
# Camera/phone models for brand data

INDIA_STATES_CITIES = {
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool", "Tirupati", "Kakinada", "Rajahmundry", "Chittoor", "Anantapur", "Other"],
    "Arunachal Pradesh": ["Itanagar", "Naharlagun", "Pasighat", "Tawang", "Other"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Nagaon", "Tinsukia", "Tezpur", "Other"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga", "Bodh Gaya", "Other"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur", "Korba", "Durg", "Jagdalpur", "Other"],
    "Goa": ["Panaji", "Vasco da Gama", "Margao", "Mapusa", "Ponda", "Other"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar", "Gandhinagar", "Anand", "Other"],
    "Haryana": ["Faridabad", "Gurugram", "Panipat", "Ambala", "Yamunanagar", "Rohtak", "Hisar", "Karnal", "Other"],
    "Himachal Pradesh": ["Shimla", "Dharamsala", "Solan", "Mandi", "Kullu", "Manali", "Kangra", "Other"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar", "Hazaribagh", "Other"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi", "Davangere", "Ballari", "Shivamogga", "Tumakuru", "Other"],
    "Kerala": ["Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Kollam", "Palakkad", "Alappuzha", "Kannur", "Other"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain", "Sagar", "Rewa", "Satna", "Other"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Thane", "Nashik", "Aurangabad", "Solapur", "Kolhapur", "Navi Mumbai", "Amravati", "Other"],
    "Manipur": ["Imphal", "Thoubal", "Bishnupur", "Churachandpur", "Other"],
    "Meghalaya": ["Shillong", "Tura", "Nongstoin", "Other"],
    "Mizoram": ["Aizawl", "Lunglei", "Champhai", "Other"],
    "Nagaland": ["Kohima", "Dimapur", "Mokokchung", "Other"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Sambalpur", "Berhampur", "Puri", "Other"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali", "Other"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Kota", "Bikaner", "Ajmer", "Udaipur", "Jaisalmer", "Pushkar", "Other"],
    "Sikkim": ["Gangtok", "Namchi", "Gyalshing", "Other"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli", "Vellore", "Erode", "Ooty", "Other"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam", "Secunderabad", "Other"],
    "Tripura": ["Agartala", "Udaipur", "Dharmanagar", "Other"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Agra", "Varanasi", "Allahabad", "Meerut", "Noida", "Ghaziabad", "Mathura", "Vrindavan", "Other"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Rishikesh", "Nainital", "Mussoorie", "Roorkee", "Other"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Asansol", "Siliguri", "Darjeeling", "Other"],
    # Union Territories
    "Andaman & Nicobar Islands": ["Port Blair", "Other"],
    "Chandigarh": ["Chandigarh"],
    "Dadra & Nagar Haveli and Daman & Diu": ["Daman", "Diu", "Silvassa", "Other"],
    "Delhi": ["New Delhi", "Delhi"],
    "Jammu & Kashmir": ["Srinagar", "Jammu", "Leh", "Kargil", "Other"],
    "Ladakh": ["Leh", "Kargil", "Other"],
    "Lakshadweep": ["Kavaratti", "Other"],
    "Puducherry": ["Puducherry", "Karaikal", "Mahe", "Other"],
}

# World countries with states/provinces (major photography markets first)
WORLD_LOCATIONS = {
    "United States": {
        "California": ["Los Angeles", "San Francisco", "San Diego", "Sacramento", "Oakland", "Other"],
        "New York": ["New York City", "Buffalo", "Albany", "Rochester", "Other"],
        "Texas": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "Other"],
        "Florida": ["Miami", "Orlando", "Tampa", "Jacksonville", "Other"],
        "Illinois": ["Chicago", "Springfield", "Other"],
        "Washington": ["Seattle", "Spokane", "Other"],
        "Massachusetts": ["Boston", "Cambridge", "Other"],
        "Colorado": ["Denver", "Boulder", "Colorado Springs", "Other"],
        "Georgia": ["Atlanta", "Savannah", "Other"],
        "Other State": ["Other"],
    },
    "United Kingdom": {
        "England": ["London", "Manchester", "Birmingham", "Leeds", "Bristol", "Liverpool", "Sheffield", "Other"],
        "Scotland": ["Edinburgh", "Glasgow", "Aberdeen", "Other"],
        "Wales": ["Cardiff", "Swansea", "Other"],
        "Northern Ireland": ["Belfast", "Other"],
    },
    "Australia": {
        "New South Wales": ["Sydney", "Newcastle", "Wollongong", "Other"],
        "Victoria": ["Melbourne", "Geelong", "Ballarat", "Other"],
        "Queensland": ["Brisbane", "Gold Coast", "Cairns", "Other"],
        "Western Australia": ["Perth", "Fremantle", "Other"],
        "South Australia": ["Adelaide", "Other"],
        "Other": ["Other"],
    },
    "Canada": {
        "Ontario": ["Toronto", "Ottawa", "Hamilton", "Other"],
        "British Columbia": ["Vancouver", "Victoria", "Other"],
        "Quebec": ["Montreal", "Quebec City", "Other"],
        "Alberta": ["Calgary", "Edmonton", "Other"],
        "Other Province": ["Other"],
    },
    "Germany": {
        "Bavaria": ["Munich", "Nuremberg", "Augsburg", "Other"],
        "Berlin": ["Berlin"],
        "Hamburg": ["Hamburg"],
        "North Rhine-Westphalia": ["Cologne", "Düsseldorf", "Dortmund", "Other"],
        "Other State": ["Other"],
    },
    "France": {
        "Île-de-France": ["Paris"],
        "Provence": ["Marseille", "Nice", "Other"],
        "Auvergne-Rhône-Alpes": ["Lyon", "Other"],
        "Other Region": ["Other"],
    },
    "Japan": {
        "Tokyo": ["Tokyo"],
        "Osaka": ["Osaka"],
        "Kyoto": ["Kyoto"],
        "Hokkaido": ["Sapporo", "Other"],
        "Other Prefecture": ["Other"],
    },
    "Singapore": {
        "Singapore": ["Singapore"],
    },
    "United Arab Emirates": {
        "Dubai": ["Dubai"],
        "Abu Dhabi": ["Abu Dhabi"],
        "Sharjah": ["Sharjah"],
        "Other Emirate": ["Other"],
    },
    "South Africa": {
        "Gauteng": ["Johannesburg", "Pretoria", "Other"],
        "Western Cape": ["Cape Town", "Stellenbosch", "Other"],
        "KwaZulu-Natal": ["Durban", "Other"],
        "Other Province": ["Other"],
    },
    "Brazil": {
        "São Paulo": ["São Paulo", "Campinas", "Other"],
        "Rio de Janeiro": ["Rio de Janeiro", "Other"],
        "Other State": ["Other"],
    },
    "New Zealand": {
        "Auckland": ["Auckland"],
        "Wellington": ["Wellington"],
        "Canterbury": ["Christchurch", "Other"],
        "Other Region": ["Other"],
    },
    "Other Country": {
        "Other": ["Other"],
    },
}

# Camera brands and models for self-declaration
# EXIF supersedes this for rankings — this is for brand/profile data only
CAMERA_BRANDS = {
    "Canon": [
        "EOS R5", "EOS R6 Mark II", "EOS R8", "EOS R50", "EOS R100",
        "EOS 5D Mark IV", "EOS 6D Mark II", "EOS 90D", "EOS 850D",
        "Other Canon"
    ],
    "Nikon": [
        "Z9", "Z8", "Z7 II", "Z6 III", "Z6 II", "Z5 II", "Z50",
        "D850", "D780", "D7500", "D3500",
        "Other Nikon"
    ],
    "Sony": [
        "Alpha A1", "Alpha A7R V", "Alpha A7 IV", "Alpha A7C II",
        "Alpha A6700", "Alpha A6400", "ZV-E10",
        "Other Sony"
    ],
    "Fujifilm": [
        "X-T5", "X-T4", "X-S20", "X-H2S", "X100VI", "X-E4",
        "GFX 100S", "GFX 50S II",
        "Other Fujifilm"
    ],
    "Olympus / OM System": [
        "OM-1 Mark II", "OM-1", "OM-5", "E-M10 Mark IV",
        "Other Olympus / OM System"
    ],
    "Panasonic": [
        "Lumix S5 II", "Lumix S5", "Lumix G9 II", "Lumix GH6",
        "Other Panasonic"
    ],
    "Leica": [
        "M11", "M10-R", "Q3", "SL3",
        "Other Leica"
    ],
    "Hasselblad": [
        "X2D 100C", "907X", "Other Hasselblad"
    ],
    "Pentax / Ricoh": [
        "K-3 Mark III", "K-1 Mark II", "Other Pentax / Ricoh"
    ],
    "DJI (Drone)": [
        "Mavic 3 Pro", "Mavic 3 Classic", "Air 3", "Mini 4 Pro", "Mini 3 Pro",
        "Inspire 3", "Other DJI"
    ],
}

PHONE_BRANDS = {
    "Apple iPhone": [
        "iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 16 Plus", "iPhone 16",
        "iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 15 Plus", "iPhone 15",
        "iPhone 14 Pro Max", "iPhone 14 Pro", "iPhone 14",
        "iPhone 13 Pro Max", "iPhone 13 Pro", "iPhone 13",
        "Older iPhone", "Other iPhone"
    ],
    "Samsung": [
        "Galaxy S24 Ultra", "Galaxy S24+", "Galaxy S24",
        "Galaxy S23 Ultra", "Galaxy S23+", "Galaxy S23",
        "Galaxy S22 Ultra", "Galaxy Z Fold 6", "Galaxy Z Flip 6",
        "Galaxy A55", "Galaxy A35",
        "Other Samsung"
    ],
    "Google Pixel": [
        "Pixel 9 Pro XL", "Pixel 9 Pro", "Pixel 9",
        "Pixel 8 Pro", "Pixel 8", "Pixel 7 Pro", "Pixel 7",
        "Other Pixel"
    ],
    "OnePlus": [
        "OnePlus 12", "OnePlus 11", "OnePlus Open",
        "Other OnePlus"
    ],
    "Xiaomi": [
        "Xiaomi 14 Ultra", "Xiaomi 14 Pro", "Xiaomi 14",
        "Redmi Note 13 Pro+", "POCO X6 Pro",
        "Other Xiaomi"
    ],
    "Vivo": [
        "X100 Pro", "X100", "V30 Pro", "Other Vivo"
    ],
    "OPPO": [
        "Find X7 Ultra", "Reno 12 Pro", "Other OPPO"
    ],
    "Other Android": [
        "Other Android phone"
    ],
}

def get_countries():
    """Returns the full list of countries for the Country dropdown/datalist.

    Countries with detailed state/city data (INDIA_STATES_CITIES /
    WORLD_LOCATIONS) appear first (India + the WORLD_LOCATIONS countries,
    alphabetised), followed by all other ISO countries alphabetised.
    "Other Country" is kept as a final catch-all for edge cases (disputed
    territories, etc.) where free-text entry is the only option.
    """
    detailed = sorted(set(['India'] + [c for c in WORLD_LOCATIONS.keys() if c != 'Other Country']))
    others = sorted(c for c in ALL_COUNTRIES if c not in detailed)
    return detailed + others + ["Other Country"]


def has_detailed_location_data(country):
    """Returns True if `country` has a full state -> [cities] mapping in
    INDIA_STATES_CITIES or WORLD_LOCATIONS (i.e. State/City can use the
    cascading dropdown UI). Returns False for all other countries, where
    the frontend should fall back to free-text State/City inputs."""
    if country == 'India':
        return True
    return country in WORLD_LOCATIONS and country != 'Other Country'


def get_states(country):
    """Returns states/provinces for a country"""
    if country == "India":
        return sorted(INDIA_STATES_CITIES.keys())
    return list(WORLD_LOCATIONS.get(country, {}).keys())

def get_cities(country, state):
    """Returns cities for a country/state combination"""
    if country == "India":
        return INDIA_STATES_CITIES.get(state, ["Other"])
    return WORLD_LOCATIONS.get(country, {}).get(state, ["Other"])


# Full ISO-3166 country list (common short names), used by get_countries()
# for countries without detailed state/city data — State and City for these
# fall back to free-text inputs (see has_detailed_location_data()).
ALL_COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus",
    "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon",
    "Canada", "Central African Republic", "Chad", "Chile", "China",
    "Colombia", "Comoros", "Congo", "Costa Rica", "Croatia", "Cuba",
    "Cyprus", "Czech Republic", "Democratic Republic of the Congo",
    "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador",
    "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia",
    "Eswatini", "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia",
    "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala",
    "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary",
    "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Ivory Coast", "Jamaica", "Japan", "Jordan", "Kazakhstan",
    "Kenya", "Kiribati", "Kosovo", "Kuwait", "Kyrgyzstan", "Laos", "Latvia",
    "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali",
    "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico",
    "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco",
    "Mozambique", "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands",
    "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea",
    "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine",
    "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines",
    "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia",
    "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa",
    "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname",
    "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan", "Tanzania",
    "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago",
    "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay",
    "Uzbekistan", "Vanuatu", "Vatican City", "Venezuela", "Vietnam",
    "Yemen", "Zambia", "Zimbabwe",
]
