# KEEP ALL YOUR EXISTING IMPORTS AT THE TOP
from flask import (Flask, render_template, request, send_file, url_for,
                   redirect, flash, session, jsonify) # Added session, jsonify
import pymongo
import gridfs # Required for error handling like NoFile
from gridfs import GridFS
from gridfs.errors import NoFile as GridFSNoFile # Specific import for clarity
from bson import ObjectId
# Renamed bson.errors to bson_errors to avoid conflict with gridfs.errors if needed later
from bson import errors as bson_errors
from io import BytesIO
import datetime
from flask_bcrypt import Bcrypt # Now used for user passwords
import traceback # For detailed error logging
# Imports needed for Login functionality
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
import logging # Import standard logging
from functools import wraps # For admin_required decorator

# --- Flask App Initialization ---
main = Flask(__name__)
main.secret_key = '3112' # TODO: Use environment variables for secrets in production!

# --- Configure Logging ---
# Basic configuration, adjust level and format as needed
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Use Flask's built-in logger for consistency
app = main # Alias for clarity in logging calls
app.logger.setLevel(logging.INFO) # Set Flask logger level

# --- Initialize Flask Extensions ---
bcrypt = Bcrypt(main)
login_manager = LoginManager(main)
login_manager.login_view = 'login' # Redirect to 'login' route if @login_required fails
login_manager.login_message_category = 'info' # Flash message category

# --- MongoDB Connection ---
mydb = None
mytable_order = None
my_table_product = None
my_review = None
my_contact = None
users_collection = None # <-- Collection for users
fs = None

# Aliases for clarity, matching common usage
orders_collection = None
products_collection = None
review_collection = None
contact_collection = None

try:
    app.logger.info("Attempting MongoDB connection...")
    # ####################################################
    # ### --- PASTE YOUR MONGODB CONNECTION CODE HERE --- ###
    # # Ensure 'users_collection = mydb["USERS"]' is present #
    # ####################################################
    myclient = pymongo.MongoClient(
        "mongodb+srv://manot6114:eSAdpaNR06qEv4Po@cluster0.gq0dj0n.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
        serverSelectionTimeoutMS=5000, # 5 second timeout
        # Removed tlsCAFile=certifi.where() as it might not be needed with srv string + default driver settings
        # If connection fails, consider adding it back if your environment requires it.
        # import certifi # <-- Add this import if using tlsCAFile
    )
    myclient.admin.command('ismaster') # Check connection by pinging the admin DB
    app.logger.info("MongoDB connection successful.")
    mydb = myclient["FLOWER"]
    mytable_order = mydb["ORDER"]
    my_table_product = mydb['PRODUCT_DATA']
    my_review = mydb['REVIEW']
    my_contact = mydb['CONTACT']
    users_collection = mydb["USERS"] # <-- Initialize users collection
    fs = GridFS(mydb)

    # Assign aliases
    orders_collection = mytable_order
    products_collection = my_table_product
    review_collection = my_review
    contact_collection = my_contact
    # #####################################################

except pymongo.errors.ConnectionFailure as e:
    app.logger.critical(f"FATAL: Could not connect to MongoDB: {e}")
except Exception as e:
    app.logger.critical(f"FATAL: An unexpected error occurred during MongoDB setup: {e}")
    app.logger.exception("Traceback for MongoDB setup error:") # Log full traceback

# --- Helper Function for DB Connection Check ---
def check_db_connection(check_users=False): # Added optional check for users collection
    """Checks if essential database components are available."""
    components = [mydb, orders_collection, products_collection, review_collection, contact_collection, fs]
    if check_users:
        components.append(users_collection)

    if any(comp is None for comp in components):
        app.logger.error("--- DB Connection Check FAILED: One or more DB components are None. ---")
        # Identify which component failed (optional detailed logging)
        if mydb is None: app.logger.error("   - mydb is None")
        if orders_collection is None: app.logger.error("   - orders_collection is None")
        if products_collection is None: app.logger.error("   - products_collection is None")
        if review_collection is None: app.logger.error("   - review_collection is None")
        if contact_collection is None: app.logger.error("   - contact_collection is None")
        if fs is None: app.logger.error("   - fs is None")
        if check_users and users_collection is None: app.logger.error("   - users_collection is None")
        return False # Indicate connection is NOT okay
    # app.logger.debug("--- DB Connection Check PASSED ---") # Changed to debug level
    return True # Indicate connection IS okay


# --- User Model and Loader ---
class User(UserMixin):
    """User class for Flask-Login."""
    def __init__(self, user_id, username):
        self.id = str(user_id) # Store user_id as string
        self.username = username
        # You can add other user attributes here if needed

@login_manager.user_loader
def load_user(user_id):
    """Loads user from DB based on user_id stored in session."""
    # app.logger.debug(f"--- load_user called with user_id: {user_id} ---")
    if not user_id:
        app.logger.warning("--- load_user called with empty or None user_id. ---")
        return None

    # Perform check *after* trying to get user_id, but before DB query
    try:
        # Validate ID format early
        user_oid = ObjectId(user_id)
    except bson_errors.InvalidId:
        app.logger.warning(f"--- load_user: Invalid ObjectId format for user_id in session: {user_id} ---")
        return None

    if not check_db_connection(check_users=True):
        app.logger.error("--- load_user: DB connection check failed ---")
        return None # Cannot load user if DB is down

    try:
        user_doc = users_collection.find_one({"_id": user_oid})
        if user_doc:
            # Pass username along with ID to the User object
            # app.logger.debug(f"--- load_user: Found user {user_doc['username']} ({user_id}) ---")
            return User(user_id=user_doc['_id'], username=user_doc['username'])
        app.logger.warning(f"--- load_user: User not found for ID {user_id} ---")
        return None
    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"--- load_user: Database error loading user {user_id}: {e} ---")
        return None
    except Exception as e:
        app.logger.error(f"--- load_user: Unexpected error loading user {user_id}: {e} ---")
        app.logger.exception("Traceback for load_user error:")
        return None

# --- Helper Functions for Admin Dashboard ---
def parse_order_date(date_str):
    """Safely parses common date string formats found in orders."""
    if not date_str: # Handle None or empty strings
        return None
    # If it's already a datetime object, return it directly
    if isinstance(date_str, datetime.datetime):
        return date_str

    if not isinstance(date_str, str):
        app.logger.warning(f"parse_order_date received non-string input: {date_str} (type: {type(date_str)})")
        return None

    common_formats = [
        "%Y-%m-%d %H:%M:%S.%f", # Format with microseconds (from default utcnow())
        "%Y-%m-%d %H:%M:%S",    # Example: 2023-10-27 15:30:00
        "%Y-%m-%d",             # Example: 2023-10-27
        "%d/%m/%Y %H:%M",       # Example: 27/10/2023 15:30
        "%d-%b-%Y",             # Example: 27-Oct-2023
        # Add other formats encountered in your data
    ]
    for fmt in common_formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except (ValueError, IndexError):
            continue # Try next format

    # Fallback if only date part matches some formats
    for fmt in common_formats:
        try:
            date_part_fmt = fmt.split(' ')[0]
            if date_part_fmt: # Ensure there's a date part format
                return datetime.datetime.strptime(date_str, date_part_fmt)
        except (ValueError, IndexError):
            continue

    app.logger.warning(f"Could not parse date string: {date_str} with known formats.")
    return None


def prepare_chart_data(order_records):
    """Prepares data aggregates for dashboard charts AND stats from order records."""
    orders_per_day = {}
    total_money_earned = 0.0
    product_sales = {}

    money_earned_today = 0.0
    products_sold_today_count = 0
    orders_today_count = 0
    orders_this_month_count = 0

    # Use timezone-naive UTC for comparisons if dates are stored as UTC
    # If dates have timezone info, use timezone-aware comparisons
    today_date = datetime.datetime.utcnow().date()
    current_month = today_date.month
    current_year = today_date.year

    for record in order_records:
        order_date_val = record.get('order_date') # Use 'order_date' as per submit route
        order_datetime = parse_order_date(order_date_val) # Use helper to parse date/datetime

        # Handle 'total_price' which might be string or float/int
        total_price_raw = record.get('total_price', 0)
        product_name = record.get('product_name') # Single product name per order in current structure

        # Safely convert price
        try:
            total_price = float(total_price_raw)
        except (ValueError, TypeError):
            total_price = 0.0
            app.logger.warning(f"Could not convert total_price '{total_price_raw}' to float for order {record.get('_id')}")

        total_money_earned += total_price

        # Process Product Sold (using 'product_name')
        if product_name and isinstance(product_name, str):
            product_sales[product_name] = product_sales.get(product_name, 0) + 1

        if order_datetime:
            # Ensure comparison is between date objects (ignore time for daily/monthly counts)
            order_date_obj = order_datetime.date()

            # --- Calculate Stats ---
            if order_date_obj == today_date:
                orders_today_count += 1
                money_earned_today += total_price
                if product_name: # Count 1 product per order (adjust if order can have multiple items)
                    # Use quantity if available and valid, otherwise count as 1 item
                    try:
                        quantity = int(record.get('quantity', 1))
                        if quantity > 0:
                            products_sold_today_count += quantity
                        else:
                            products_sold_today_count += 1 # Default to 1 if quantity is invalid/zero
                    except (ValueError, TypeError):
                         products_sold_today_count += 1 # Default to 1 if quantity is non-numeric


            if order_date_obj.year == current_year and order_date_obj.month == current_month:
                orders_this_month_count += 1

            # --- Prepare Orders Per Day Chart Data ---
            order_day_str = order_date_obj.strftime("%Y-%m-%d") # Consistent format for labels
            orders_per_day[order_day_str] = orders_per_day.get(order_day_str, 0) + 1
        else:
            app.logger.warning(f"Record {record.get('_id')} has unparseable date '{order_date_val}', skipping date-based calculations.")

    # --- Prepare Chart Outputs ---
    # Sort orders per day by date
    sorted_dates = sorted(orders_per_day.keys())
    orders_count = [orders_per_day[date] for date in sorted_dates]

    # Get top 5 most sold products
    most_sold_product_sorted = sorted(product_sales.items(), key=lambda item: item[1], reverse=True)
    most_sold_product_names = [item[0] for item in most_sold_product_sorted[:5]]
    most_sold_product_counts = [item[1] for item in most_sold_product_sorted[:5]]

    # Fetch review count (moved here for better data flow)
    review_count_val = get_review_count()

    # --- Assemble Final Dictionary ---
    chart_data_output = {
        # Chart Data
        'orders_per_day': {
            'labels': sorted_dates,
            'data': orders_count
        },
        'most_sold_products': {
            'labels': most_sold_product_names,
            'data': most_sold_product_counts
        },
        # Statistics Card Data
        'money_earned': round(total_money_earned, 2), # Overall total, rounded
        'money_earned_today': round(money_earned_today, 2),
        'products_sold_today': products_sold_today_count,
        'orders_today': orders_today_count,
        'orders_this_month': orders_this_month_count,
        'user_count': get_user_count(), # Fetch counts directly here
        'order_count': get_order_count(),
        'product_count': get_product_count(),
        'review_count': review_count_val, # Use fetched value
        'contact_count': get_contact_count(),
    }
    # app.logger.info(f"Chart Data Prepared: {chart_data_output}")
    return chart_data_output


# --- Helper Functions for Dashboard Counts ---
def get_count_from_collection(collection, name):
    """Helper to get count and handle errors."""
    if not check_db_connection(check_users=(collection == users_collection)):
        app.logger.error(f"Cannot get {name} count, DB connection failed.")
        return 0
    if collection is None: # Extra safety check
        app.logger.error(f"Cannot get {name} count, collection object is None.")
        return 0
    try:
        return collection.count_documents({})
    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"Database error getting {name} count: {e}")
        return 0
    except Exception as e:
        app.logger.error(f"Unexpected error getting {name} count: {e}")
        return 0

def get_user_count():
    return get_count_from_collection(users_collection, "user")

def get_order_count():
    return get_count_from_collection(orders_collection, "order")

def get_product_count():
    return get_count_from_collection(products_collection, "product")

def get_review_count():
    return get_count_from_collection(review_collection, "review")

def get_contact_count():
    return get_count_from_collection(contact_collection, "contact")


# --- Authentication Routes ---

@main.route("/register", methods=["GET", "POST"])
def register():
    """Handles user registration."""
    if current_user.is_authenticated:
        flash("You are already logged in.", "info")
        return redirect(url_for('main_div'))

    if request.method == "POST":
        if not check_db_connection(check_users=True):
            flash("Registration currently unavailable due to a database issue.", "error")
            return render_template("register.html") # Show form again

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash("Username and password are required.", "warning")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "warning")
            return render_template("register.html", username=username)

        try:
            existing_user = users_collection.find_one({"username": username})
            if existing_user:
                flash("Username already exists. Please choose another.", "warning")
                return render_template("register.html", username=username)

            hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
            user_data = {
                "username": username,
                "password": hashed_password,
                "registered_on": datetime.datetime.utcnow(),
                "photo_id": None # Initialize photo_id field
            }
            insert_result = users_collection.insert_one(user_data)
            app.logger.info(f"User '{username}' registered with ID: {insert_result.inserted_id}")
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        except pymongo.errors.PyMongoError as e:
            app.logger.error(f"Database error during registration for {username}: {e}")
            flash("A database error occurred during registration. Please try again.", "error")
        except Exception as e:
            app.logger.exception(f"Unexpected error during registration for {username}:")
            flash("An unexpected error occurred during registration.", "error")

        return render_template("register.html", username=username)

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    """Handles user login."""
    if current_user.is_authenticated:
        flash("You are already logged in.", "info")
        return redirect(url_for('main_div'))

    if request.method == "POST":
        # app.logger.info("--- Login attempt (POST) ---")
        if not check_db_connection(check_users=True):
            flash("Login currently unavailable due to a database issue.", "error")
            app.logger.error("--- Login POST: DB check failed ---")
            return render_template("login.html")

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # app.logger.info(f"--- Login attempt for username: '{username}' ---")

        if not username or not password:
            flash("Username and password are required.", "warning")
            # app.logger.warning(f"--- Login POST: Missing fields (User: '{username}', Pass empty: {not password}) ---")
            return render_template("login.html", username=username)

        try:
            # app.logger.debug(f"--- Login POST: Querying DB for username: '{username}' ---")
            user_doc = users_collection.find_one({"username": username})

            if user_doc:
                # app.logger.debug(f"--- Login POST: User doc found for '{username}'. Checking password... ---")
                if bcrypt.check_password_hash(user_doc['password'], password):
                    # app.logger.info(f"--- Login POST: Password MATCH for '{username}' ---")
                    user_obj = User(user_id=user_doc['_id'], username=user_doc['username'])
                    login_user(user_obj) # Use Flask-Login to manage session
                    flash(f"Welcome back, {username}!", "success")

                    next_page = request.args.get('next')
                    # app.logger.info(f"--- Login POST: Success. Next page: {next_page} ---")
                    # Validate next_page to prevent open redirect vulnerability
                    if next_page and not next_page.startswith('/'):
                        next_page = url_for('main_div') # Default redirect if next_page is suspicious

                    return redirect(next_page or url_for('main_div'))
                else:
                    app.logger.warning(f"--- Login POST: Password MISMATCH for '{username}' ---")
                    flash("Invalid username or password.", "danger")
            else:
                app.logger.warning(f"--- Login POST: User doc NOT FOUND for '{username}' ---")
                flash("Invalid username or password.", "danger")

            return render_template("login.html", username=username)

        except pymongo.errors.PyMongoError as e:
            app.logger.error(f"--- Login POST: Database error for user '{username}': {e} ---")
            flash("A database error occurred during login. Please try again.", "error")
            return render_template("login.html", username=username)
        except Exception as e:
            app.logger.exception(f"--- Login POST: Unexpected error for user '{username}':")
            flash("An unexpected error occurred during login.", "error")
            return render_template("login.html", username=username)

    # app.logger.info("--- Login access (GET) ---")
    return render_template("login.html")


@main.route("/logout")
@login_required # User must be logged in to log out
def logout():
    """Logs the current user out."""
    username = current_user.username if current_user else 'Unknown'
    app.logger.info(f"--- Logout request for user: {username} ---")
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for('main_div'))

# --- Admin Routes ---
@main.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    """Handles admin login."""
    if 'admin' in session and session.get('admin'): # Use .get for safety
         flash("Admin already logged in.", "info")
         return redirect(url_for('dashboard'))
    if current_user.is_authenticated: # Prevent logged-in regular users using admin login
         flash("Please log out first to log in as admin.", "warning")
         return redirect(url_for('main_div'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # --- !!! VERY INSECURE - Replace with proper admin user check in DB !!! ---
        # TODO: Implement proper admin role checking in the users_collection or a separate admin collection.
        # Example (conceptual):
        # user = users_collection.find_one({"username": username, "role": "admin"})
        # if user and bcrypt.check_password_hash(user['password'], password):
        #     session['admin'] = True
        #     session['admin_username'] = username
        #     # ... success ...
        if username == 'admin' and password == 'admin123': # <<< --- REPLACE THIS INSECURE CHECK
            session['admin'] = True # Mark session as admin
            session['admin_username'] = username
            app.logger.warning(f"Admin login successful for '{username}' using HARDCODED credentials.") # Log warning
            flash("Admin login successful!", "success")
            return redirect(url_for('dashboard'))
        else:
            app.logger.warning(f"Failed admin login attempt for username '{username}'.")
            flash("Invalid admin credentials.", "danger")

    return render_template('admin.html')

@main.route('/admin_logout')
def admin_logout():
    """Logs the admin out by clearing the session flag."""
    admin_username = session.get('admin_username', 'Unknown Admin')
    session.pop('admin', None)
    session.pop('admin_username', None)
    app.logger.info(f"Admin '{admin_username}' logged out.")
    flash("Admin logged out.", "success")
    return redirect(url_for('main_div'))


# --- Admin Required Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session or not session.get('admin'):
            flash("Admin access required for this page.", "warning")
            app.logger.warning(f"Unauthorized access attempt to admin route: {request.path}")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Protected Admin Dashboard ---
@main.route('/dashboard')
@admin_required # Apply the decorator
def dashboard():
    """Displays the main admin dashboard."""
    app.logger.info("Accessing Admin Dashboard.")
    # Ensure DB connection before proceeding
    if not check_db_connection():
        flash("Dashboard unavailable due to database connection issues.", "error")
        # Provide default empty structure for chart_data to avoid template errors
        chart_data = prepare_chart_data([]) # Still need basic structure
        return render_template("dashboard.html", product_records=[], order_records=[], review_records=[], chart_data=chart_data)

    try:
        # Fetch raw data
        product_records_raw = list(products_collection.find())
        # Sort orders by date descending (most recent first) - using 'order_date'
        order_records_raw = list(orders_collection.find().sort('order_date', pymongo.DESCENDING))
        # Fetch reviews
        review_records_raw = list(review_collection.find().sort('submitted_at', pymongo.DESCENDING))

        # Prepare chart data and statistics FIRST (also calculates counts)
        chart_data = prepare_chart_data(order_records_raw)

        # Prepare product records for template
        product_records_processed = []
        for record in product_records_raw:
            try:
                record['_id'] = str(record['_id'])
                image_id = record.get('image_id')
                if image_id and isinstance(image_id, ObjectId):
                    record['image_url'] = url_for('get_image', image_id=str(image_id))
                else:
                    record['image_url'] = url_for('static', filename='images/placeholder.png') # Use placeholder if no image
                product_records_processed.append(record)
            except Exception as e:
                app.logger.error(f"Error processing product record {record.get('_id', 'UNKNOWN')} for dashboard: {e}")
                # Skip or add placeholder? Skipping for now.

        # Prepare order records for template (add necessary conversions)
        order_records_processed = []
        for record in order_records_raw:
            try:
                record['_id'] = str(record['_id'])
                record['status'] = record.get('status', 'Pending') # Default to 'Pending'
                # Format date for display
                order_datetime = parse_order_date(record.get('order_date'))
                record['order_date_formatted'] = order_datetime.strftime("%Y-%m-%d %H:%M") if order_datetime else "Invalid Date"
                # Ensure price is formatted
                try:
                    record['total_price_formatted'] = f"{float(record.get('total_price', 0)):.2f}"
                except (ValueError, TypeError):
                    record['total_price_formatted'] = "N/A"
                order_records_processed.append(record)
            except Exception as e:
                 app.logger.error(f"Error processing order record {record.get('_id', 'UNKNOWN')} for dashboard: {e}")


        # Prepare review records for template
        review_records_processed = []
        for record in review_records_raw:
             try:
                record['_id'] = str(record['_id'])
                # Format date
                review_datetime = parse_order_date(record.get('submitted_at')) # Can reuse date parser
                record['submitted_at_formatted'] = review_datetime.strftime("%Y-%m-%d %H:%M") if review_datetime else "Invalid Date"
                review_records_processed.append(record)
             except Exception as e:
                app.logger.error(f"Error processing review record {record.get('_id', 'UNKNOWN')} for dashboard: {e}")


    except pymongo.errors.PyMongoError as e:
        flash(f"Database error fetching dashboard data: {e}", "error")
        app.logger.error(f"Database error fetching dashboard data: {e}")
        product_records_processed = []
        order_records_processed = []
        review_records_processed = []
        # Provide default empty structure for chart_data
        chart_data = prepare_chart_data([])
    except Exception as e:
        flash(f"An unexpected error occurred loading the dashboard: {e}", "error")
        app.logger.exception("Unexpected error in dashboard route:") # Log full traceback
        product_records_processed = []
        order_records_processed = []
        review_records_processed = []
        chart_data = prepare_chart_data([])

    return render_template(
        "dashboard.html",
        product_records=product_records_processed,
        order_records=order_records_processed,
        review_records=review_records_processed, # Pass processed reviews
        chart_data=chart_data # Contains chart data and stats counts
    )


# --- Order Status Update ---
@main.route("/update_order_status/<order_id>", methods=['POST'])
@admin_required # Only admins can update status
def update_order_status(order_id):
    """Updates the status of a specific order via JSON request."""
    try:
        oid = ObjectId(order_id)
    except bson_errors.InvalidId:
        app.logger.error(f"Invalid ObjectId received for status update: {order_id}")
        return jsonify({"success": False, "message": "Invalid order ID format."}), 400

    if not request.is_json:
         app.logger.warning(f"Non-JSON request received for status update on order {order_id}")
         return jsonify({"success": False, "message": "Request must be JSON."}), 400

    data = request.get_json()
    if data is None:
        app.logger.warning(f"Invalid or empty JSON payload received for status update on order {order_id}")
        return jsonify({"success": False, "message": "Invalid or empty JSON payload."}), 400

    new_status = data.get('status')
    if not new_status:
        app.logger.warning(f"Missing 'status' in JSON payload for order {order_id}")
        return jsonify({"success": False, "message": "'status' field is required."}), 400

    # Keep statuses consistent (Title Case recommended)
    allowed_statuses = ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']
    if new_status not in allowed_statuses:
         app.logger.warning(f"Invalid status value '{new_status}' received for order {order_id}")
         return jsonify({"success": False, "message": f"Invalid status value. Allowed: {', '.join(allowed_statuses)}"}), 400

    if not check_db_connection():
        app.logger.error(f"DB connection failed during status update attempt for order {order_id}")
        return jsonify({"success": False, "message": "Database connection error."}), 503 # Service Unavailable

    try:
        result = orders_collection.update_one(
            {"_id": oid},
            {"$set": {"status": new_status, "status_last_updated": datetime.datetime.utcnow()}}
        )

        if result.matched_count == 0:
            app.logger.warning(f"Order ID {order_id} not found in database for status update.")
            return jsonify({"success": False, "message": "Order not found."}), 404
        elif result.modified_count == 0:
             app.logger.info(f"Order {order_id} status already set to '{new_status}'. No update needed.")
             return jsonify({"success": True, "message": f"Order status is already '{new_status}'."}), 200 # OK
        else:
            app.logger.info(f"Order {order_id} status updated to '{new_status}'.")
            return jsonify({"success": True, "message": f"Order status successfully updated to '{new_status}'."}), 200 # OK

    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"Database error updating status for order {order_id}: {e}")
        return jsonify({"success": False, "message": f"Database error occurred."}), 500
    except Exception as e:
         app.logger.exception(f"Unexpected error updating status for order {order_id}:")
         return jsonify({"success": False, "message": "An unexpected server error occurred."}), 500


# --- Existing Flower Shop Routes (Keep existing, modifications applied where needed) ---
@main.route("/get_image/<image_id>") # Renamed from /image to avoid clash if static folder has 'image'
def get_image(image_id):
    """Serves an image file from GridFS."""
    placeholder_path = 'static/images/placeholder.png'
    default_mimetype = 'image/png'

    if not check_db_connection():
        app.logger.warning(f"DB connection failed for image request: {image_id}")
        try:
            return send_file(placeholder_path, mimetype=default_mimetype)
        except FileNotFoundError:
            app.logger.error(f"Placeholder image not found at {placeholder_path}")
            return "Service unavailable", 503

    try:
        oid = ObjectId(image_id)
    except bson_errors.InvalidId:
        app.logger.warning(f"Invalid ObjectId requested for image: {image_id}")
        try:
            return send_file(placeholder_path, mimetype=default_mimetype)
        except FileNotFoundError:
             app.logger.error(f"Placeholder image not found at {placeholder_path}")
             return "Invalid image ID", 400

    try:
        image_file = fs.get(oid)
        mimetype = getattr(image_file, 'content_type', None) or 'image/jpeg'
        return send_file(BytesIO(image_file.read()), mimetype=mimetype)
    except GridFSNoFile:
        app.logger.warning(f"Image not found in GridFS: {image_id}")
        try:
            return send_file(placeholder_path, mimetype=default_mimetype)
        except FileNotFoundError:
            app.logger.error(f"Placeholder image not found at {placeholder_path}")
            return "Image not found", 404
    except pymongo.errors.PyMongoError as db_err:
        app.logger.error(f"Database error retrieving image {image_id}: {db_err}")
        return "Database error retrieving image", 500
    except Exception as e:
        app.logger.exception(f"Error retrieving image {image_id}:") # Log full traceback
        return "Error retrieving image", 500


@main.route("/up")
@admin_required # Only admins can access the upload page
def up():
    """Renders the product upload form page."""
    return render_template('upload.html')


@main.route("/edit/<product_id>", methods=['GET', 'POST'])
@admin_required # Only admins can edit products
def edit_product(product_id):
    """Handles editing an existing product."""
    try:
        oid = ObjectId(product_id)
    except bson_errors.InvalidId:
        flash("Invalid product ID format.", "error")
        return redirect(url_for('dashboard')) # Redirect admin to dashboard

    if not check_db_connection():
        flash("Database connection error.", "error")
        return redirect(url_for('dashboard'))

    product = None # Define product outside try/except for access in POST on error
    try:
        product = products_collection.find_one({"_id": oid})
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for('dashboard'))

        # Prepare product for GET request or re-rendering on POST error
        product['_id'] = str(product['_id'])
        product['flower_name'] = product.get('flower_name', '')
        product['flower_price'] = product.get('flower_price', '') # Keep raw price for form field
        product['flower_description'] = product.get('flower_description', '')
        image_id = product.get('image_id')
        if image_id and isinstance(image_id, ObjectId):
            product['image_url'] = url_for('get_image', image_id=str(image_id))
        else:
            product['image_url'] = url_for('static', filename='images/placeholder.png')

    except pymongo.errors.PyMongoError as e:
         flash(f"Database error fetching product: {e}", "error")
         app.logger.error(f"DB error fetching product {product_id} for edit: {e}")
         return redirect(url_for('dashboard'))
    except Exception as e:
         flash(f"An unexpected error occurred fetching product details: {e}", "error")
         app.logger.exception(f"Unexpected error fetching product {product_id} for edit:")
         return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return render_template('edit_product.html', product=product)

    # --- POST Request ---
    if request.method == 'POST':
        flower_name = request.form.get('fname', '').strip()
        flower_price_str = request.form.get('price', '').strip()
        flower_description = request.form.get('des', '').strip()
        image_file = request.files.get('image')

        # Basic validation
        if not flower_name:
            flash("Flower name cannot be empty.", "error")
            return render_template('edit_product.html', product=product) # Render again with error

        # Validate price format (allow float/int)
        flower_price = None
        if flower_price_str: # Only validate if a price was entered
            try:
                flower_price = float(flower_price_str)
            except ValueError:
                flash("Invalid price format. Please enter a number.", "error")
                return render_template('edit_product.html', product=product)
        else:
            # Decide behavior for empty price: Allow clear? Set to 0? Forbid?
            # Assuming setting to 0 if cleared
            flower_price = 0.0
            # Alternatively, forbid empty price:
            # flash("Price cannot be empty.", "error")
            # return render_template('edit_product.html', product=product)


        update_data = {}
        # Only add to update if the value actually changed (optional optimization)
        if flower_name != product.get('flower_name'):
            update_data['flower_name'] = flower_name
        if flower_price != product.get('flower_price'): # Compare with original numeric price
            update_data['flower_price'] = flower_price
        if flower_description != product.get('flower_description'):
            update_data['flower_description'] = flower_description

        old_image_id = product.get('image_id') # Get original image_id (might be ObjectId or None)
        new_file_id = None

        # Handle image update
        if image_file and image_file.filename != '':
            allowed_extensions = {'png', 'jpg', 'jpeg'}
            file_ext = image_file.filename.split('.')[-1].lower() if '.' in image_file.filename else ''
            if file_ext not in allowed_extensions:
                flash(f"Invalid image file type '{file_ext}'. Only .png, .jpg, .jpeg allowed.", "error")
                return render_template('edit_product.html', product=product) # Show error on edit page

            try:
                 # Store new image
                 image_file.seek(0) # Ensure stream is at beginning
                 new_file_id = fs.put(
                     image_file,
                     filename=image_file.filename,
                     content_type=image_file.mimetype
                 )
                 update_data['image_id'] = new_file_id
                 app.logger.info(f"New image uploaded for product {product_id}, GridFS ID: {new_file_id}")

            except Exception as gridfs_e:
                 flash(f"Error storing updated image: {gridfs_e}", "error")
                 app.logger.error(f"GridFS error updating image for {product_id}: {gridfs_e}")
                 # Don't proceed with DB update if image saving failed
                 return render_template('edit_product.html', product=product)


        # Perform DB Update only if there are changes or a new image
        if update_data:
            try:
                result = products_collection.update_one({"_id": oid}, {"$set": update_data})

                if result.modified_count > 0:
                    flash(f"Product updated successfully.", "success")
                    # Delete old image *after* successful DB update if a new one was set
                    if old_image_id and new_file_id and old_image_id != new_file_id and isinstance(old_image_id, ObjectId):
                         try:
                             fs.delete(old_image_id)
                             app.logger.info(f"Old image {old_image_id} deleted for product {product_id}.")
                         except GridFSNoFile:
                             app.logger.warning(f"Old image {old_image_id} not found in GridFS during cleanup for product {product_id}.")
                         except Exception as del_e:
                             app.logger.error(f"Failed to delete old image {old_image_id} for product {product_id}: {del_e}")

                elif result.matched_count == 0:
                     flash(f"Product not found during update.", "error") # Should not happen if initial find worked
                else:
                    # If modified_count is 0, but we uploaded an image, it means only the image changed
                    if new_file_id:
                         flash(f"Product image updated successfully.", "success")
                         # Delete old image here too if only image changed
                         if old_image_id and new_file_id and old_image_id != new_file_id and isinstance(old_image_id, ObjectId):
                             try: fs.delete(old_image_id); app.logger.info(f"Old image {old_image_id} deleted (only image change).")
                             except Exception as del_e: app.logger.error(f"Failed to delete old image {old_image_id} (only image change): {del_e}")
                    else:
                        flash(f"No changes detected for the product.", "info")

                return redirect(url_for('dashboard')) # Redirect admin to dashboard

            except pymongo.errors.PyMongoError as db_e:
                 flash(f"Database error updating product: {db_e}", "error")
                 app.logger.error(f"DB error updating product {product_id}: {db_e}")
                 # If DB update failed BUT we uploaded a new image, delete the new (orphaned) image
                 if new_file_id:
                     try:
                         fs.delete(new_file_id)
                         app.logger.info(f"Cleaned up orphaned new image {new_file_id} after failed DB update for product {product_id}.")
                     except Exception as cleanup_e:
                         app.logger.error(f"Failed cleanup of orphaned new image {new_file_id}: {cleanup_e}")
                 return render_template('edit_product.html', product=product) # Show error on edit page
            except Exception as e:
                 flash(f"An unexpected error occurred during update: {e}", "error")
                 app.logger.exception(f"Unexpected error updating product {product_id}:")
                 if new_file_id: # Cleanup on unexpected error too
                      try: fs.delete(new_file_id); app.logger.info(f"Cleaned up orphaned new image {new_file_id} after unexpected error.")
                      except Exception as cl: app.logger.error(f"Failed cleanup of orphaned new image {new_file_id}: {cl}")
                 return render_template('edit_product.html', product=product)
        else:
            flash("No updates provided.", "warning")
            return redirect(url_for('edit_product', product_id=product_id))


@main.route("/delete_product/<product_id>", methods=['POST'])
@admin_required # Only admins can delete products
def delete_product(product_id):
    """Deletes a product and its associated image."""
    try:
        oid = ObjectId(product_id)
    except bson_errors.InvalidId:
        flash("Invalid product ID format.", "error")
        return redirect(url_for('dashboard'))

    if not check_db_connection():
        flash("Database connection error.", "error")
        return redirect(url_for('dashboard'))

    image_id_to_delete = None
    try:
        # Find the product first to get the image ID
        product_to_delete = products_collection.find_one({"_id": oid}, {"image_id": 1})

        if not product_to_delete:
            flash(f"Product not found.", "warning")
            return redirect(url_for('dashboard'))

        image_id_to_delete = product_to_delete.get('image_id')

        # Delete the product document
        result = products_collection.delete_one({"_id": oid})

        if result.deleted_count > 0:
            flash(f"Product deleted successfully.", "success")
            app.logger.info(f"Product {product_id} deleted from collection.")

            # If product deletion was successful, try deleting the associated image
            if image_id_to_delete and isinstance(image_id_to_delete, ObjectId):
                try:
                    fs.delete(image_id_to_delete)
                    app.logger.info(f"Associated image {image_id_to_delete} deleted from GridFS for product {product_id}.")
                except GridFSNoFile:
                    app.logger.warning(f"Image {image_id_to_delete} not found in GridFS for deleted product {product_id}.")
                except Exception as gridfs_e:
                    app.logger.error(f"Error deleting image {image_id_to_delete} from GridFS: {gridfs_e}")
                    # Don't obscure the product deletion success, just add a warning
                    flash(f"Product data deleted, but couldn't remove associated image file.", "warning")
            elif image_id_to_delete:
                 app.logger.warning(f"Product {product_id} deleted, but associated image_id '{image_id_to_delete}' was not a valid ObjectId.")
            else:
                 app.logger.info(f"Product {product_id} deleted, no associated image found or image_id was null.")
        else:
             # This case is unlikely if find_one succeeded just before, but possible due to race conditions
             flash(f"Product could not be deleted (might have been removed already).", "error")
             app.logger.warning(f"Delete command failed for product {product_id} despite being found initially.")

    except pymongo.errors.PyMongoError as db_e:
        app.logger.error(f"Database error during product deletion {product_id}: {db_e}")
        flash(f"A database error occurred while deleting the product: {db_e}", "error")
    except Exception as e:
        app.logger.exception(f"Unexpected error during product deletion {product_id}:")
        flash(f"An unexpected error occurred: {e}", "error")

    return redirect(url_for('dashboard')) # Redirect admin to dashboard


@main.route("/upload", methods=['POST'])
@admin_required # Only admins can upload new products
def upload():
    """Handles the upload of a new product."""
    if not check_db_connection():
        flash("Database connection error.", "error")
        return redirect(url_for('up'))

    try:
        flower_name = request.form.get('fname', '').strip()
        flower_price_str = request.form.get('price', '').strip()
        flower_description = request.form.get('des', '').strip()
        image_file = request.files.get('image')

        # --- Validation ---
        if not flower_name or not flower_price_str or not image_file or image_file.filename == '':
             flash("Missing required fields (Name, Price, Image).", "error")
             return redirect(url_for('up'))

        try:
            flower_price = float(flower_price_str) # Validate price format
            if flower_price < 0:
                 flash("Price cannot be negative.", "error")
                 return redirect(url_for('up'))
        except ValueError:
             flash("Invalid price format. Please enter a number.", "error")
             return redirect(url_for('up'))

        allowed_extensions = {'png', 'jpg', 'jpeg'}
        file_ext = image_file.filename.split('.')[-1].lower() if '.' in image_file.filename else ''
        if file_ext not in allowed_extensions:
            flash(f"Invalid file type '{file_ext}'. Only .png, .jpg, .jpeg allowed.", "error")
            return redirect(url_for('up'))

        # --- Store Image in GridFS ---
        file_id = None
        try:
            image_file.seek(0) # Ensure stream is at beginning
            file_id = fs.put(
                image_file,
                filename=image_file.filename,
                content_type=image_file.mimetype
            )
            app.logger.info(f"Image '{image_file.filename}' stored in GridFS with ID: {file_id}")
        except Exception as gridfs_e:
             app.logger.error(f"GridFS error uploading image '{image_file.filename}': {gridfs_e}")
             flash(f"Error storing image file: {gridfs_e}", "error")
             return redirect(url_for('up'))

        # --- Store Product Data in MongoDB ---
        product_data = {
            'flower_name': flower_name,
            'flower_price': flower_price, # Store as float
            'flower_description': flower_description,
            'image_id': file_id,
            'upload_date': datetime.datetime.utcnow()
        }
        try:
            insert_result = products_collection.insert_one(product_data)
            app.logger.info(f"Product '{flower_name}' inserted with ID: {insert_result.inserted_id}")
            flash("Product uploaded successfully!", "success")
            return redirect(url_for('dashboard')) # Redirect admin to dashboard after upload
        except pymongo.errors.PyMongoError as db_e:
             app.logger.error(f"Database error inserting product '{flower_name}': {db_e}")
             flash(f"Database error saving product data: {db_e}", "error")
             # Cleanup orphaned GridFS file
             if file_id:
                 try:
                     fs.delete(file_id)
                     app.logger.info(f"Cleaned up orphaned GridFS file {file_id} after failed DB insert.")
                 except Exception as cleanup_e:
                     app.logger.error(f"Error cleaning up orphaned GridFS file {file_id}: {cleanup_e}")
             return redirect(url_for('up'))

    except Exception as e:
        app.logger.exception("Error during product upload:")
        flash(f"An unexpected error occurred during upload: {e}", "error")
        return redirect(url_for('up'))

# Renamed collection alias for consistency
@main.route('/delete_review/<review_id_str>', methods=['POST'])
@admin_required # Only admins can delete reviews
def delete_review(review_id_str):
    """Deletes a specific review."""
    if not check_db_connection():
        flash("Database connection error.", "error")
        return redirect(url_for('dashboard'))
    try:
        oid = ObjectId(review_id_str)
        result = review_collection.delete_one({'_id': oid})
        if result.deleted_count > 0:
            flash("Review deleted successfully.", "success")
            app.logger.info(f"Review {review_id_str} deleted.")
        else:
            flash("Review not found or already deleted.", "warning")
            app.logger.warning(f"Review deletion failed: ID {review_id_str} not found.")
    except bson_errors.InvalidId:
        flash("Invalid review ID format.", "error")
        app.logger.error(f"Invalid ObjectId for review deletion: {review_id_str}")
    except pymongo.errors.PyMongoError as e:
        flash("Database error deleting review.", "error")
        app.logger.error(f"Database error deleting review {review_id_str}: {e}")
    except Exception as e:
        flash("An unexpected error occurred deleting the review.", "error")
        app.logger.exception(f"Unexpected error deleting review {review_id_str}:")

    return redirect(url_for('dashboard')) # Redirect admin back to dashboard


@main.route("/", methods=['GET'])
@login_required # Requires login to see the main shop page
def main_div():
    app.logger.info(f"--- Accessing '/' route by user: {current_user.username} ({current_user.id}) ---")
    img_records = []
    reviews = []

    if not check_db_connection():
        app.logger.error("--- '/' route: DB check FAILED ---") # Log failure
        flash("Website experiencing database connection issues. Please try again later.", "error")
        return render_template("index.html", img_records=[], reviews=[], username=current_user.username)
    else:
        # app.logger.info("--- '/' route: DB check PASSED ---") # Log success (can be noisy)
        pass

    # Fetch Products
    try:
        # app.logger.debug(f"--- Attempting to query collection: {products_collection.name} ---")
        # Force cursor execution and convert to list for easier debugging
        products_list = list(products_collection.find().limit(20)) # Consider pagination for large catalogs
        # app.logger.info(f"--- Found {len(products_list)} product documents in DB ---") # Log count

        if not products_list:
             app.logger.warning("--- No products found in the database collection! ---")

        for index, record in enumerate(products_list):
            # Log the raw record before processing (can be very verbose, use DEBUG level)
            # app.logger.debug(f"--- Processing product index {index}, raw data: {record} ---")
            try:
                product_id_str = str(record['_id'])
                image_id = record.get('image_id')
                img_url = None

                # Explicitly check image_id type and log
                if image_id and isinstance(image_id, ObjectId):
                   img_url = url_for('get_image', image_id=str(image_id))
                   # app.logger.debug(f"     Product {product_id_str}: Found ObjectId image_id {image_id}, generated URL: {img_url}")
                elif image_id:
                   app.logger.warning(f"     Product {product_id_str}: Found image_id but it's NOT an ObjectId. Type: {type(image_id)}, Value: {image_id}. Using placeholder.")
                   img_url = url_for('static', filename='images/placeholder.png') # Fallback URL
                else:
                   app.logger.debug(f"     Product {product_id_str}: No image_id found. Using placeholder.")
                   img_url = url_for('static', filename='images/placeholder.png') # Fallback URL

                # Handle price formatting safely
                raw_price = record.get('flower_price') # Don't default here, check explicitly
                formatted_price = "N/A" # Default formatted price
                if raw_price is not None:
                    try:
                        formatted_price = f"{float(raw_price):.2f}"
                    except (ValueError, TypeError) as price_err:
                        app.logger.warning(f"     Product {product_id_str}: Error formatting price '{raw_price}'. Error: {price_err}. Using 'N/A'.")
                else:
                     app.logger.warning(f"     Product {product_id_str}: Missing 'flower_price' field. Using 'N/A'.")


                processed_data = {
                    'product_id': product_id_str,
                    'img_url': img_url,
                    'flower_name': record.get('flower_name', 'N/A'),
                    'flower_price': formatted_price, # Use safely formatted price
                    'flower_description': record.get('flower_description', 'N/A')
                }
                img_records.append(processed_data)
                # app.logger.debug(f"     Product index {index} successfully processed and added to img_records.")

            except Exception as inner_e:
                 # Log the specific record that caused the error AND the traceback
                 app.logger.error(f"!!! Error processing product record at index {index} (ID: {record.get('_id', 'UNKNOWN')}): {inner_e}", exc_info=True)
                 # Decide whether to skip or stop: continue # Skip problematic record

        # app.logger.info(f"--- Finished processing products. Final img_records size: {len(img_records)} ---")
        # Log first few items to see what's actually being passed
        # app.logger.debug(f"--- Sample img_records data: {img_records[:3]} ---")

    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"Database error fetching products for main page: {e}", exc_info=True) # Add traceback
        flash("Could not load products due to a database error.", "error")
        img_records = [] # Ensure it's empty on error
    except Exception as e:
        app.logger.exception("Unexpected error fetching products for main page:") # Log full traceback
        flash("An unexpected error occurred while loading products.", "error")
        img_records = [] # Ensure it's empty on error

    # Fetch Reviews
    try:
        reviews_raw = list(review_collection.find().sort('submitted_at', pymongo.DESCENDING).limit(10)) # Limit reviews shown
        reviews = []
        for rev in reviews_raw:
            try:
                review_datetime = parse_order_date(rev.get('submitted_at'))
                formatted_date = review_datetime.strftime("%Y-%m-%d") if review_datetime else "Unknown Date"
                reviews.append({
                    'text': rev.get('text', ''),
                    'username': rev.get('username', 'Anonymous'),
                    'date': formatted_date
                })
            except Exception as rev_e:
                app.logger.error(f"Error processing review {rev.get('_id', 'UNKNOWN')} for main page: {rev_e}")

    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"Database error fetching reviews for main page: {e}")
        # Don't flash another error, products might have loaded
        reviews = []
    except Exception as e:
        app.logger.exception("Unexpected error fetching reviews for main page:")
        reviews = []


    # app.logger.info(f"--- Rendering index.html with {len(img_records)} products and {len(reviews)} reviews ---")
    return render_template("index.html",
                           img_records=img_records,
                           reviews=reviews,
                           username=current_user.username)


@main.route("/buy", methods=['POST', 'GET'])
@login_required # Requires login to initiate purchase
def buy():
    """Renders the page for buying a specific product."""
    # app.logger.info(f"--- Accessing '/buy' route (Method: {request.method}) ---")
    if not check_db_connection():
        flash("Database connection error. Cannot load product details.", "error")
        return redirect(url_for('main_div'))

    product = None
    product_id_str = None

    if request.method == 'POST':
        product_id_str = request.form.get('product_id')
        app.logger.debug(f"Buy page POST request for product_id: {product_id_str}")
        if not product_id_str:
            flash("No product selected.", "error")
            return redirect(url_for('main_div'))
        try:
            oid = ObjectId(product_id_str)
            product = products_collection.find_one({'_id': oid})
            if product is None:
                 app.logger.warning(f"Product with ID {product_id_str} not found in DB for buy page.")
                 flash("Product not found.", "error")
                 return redirect(url_for('main_div'))

            # Prepare product data for template
            product['_id'] = str(product['_id']) # Use string ID in template

            # --- Robust Price Formatting ---
            raw_price = product.get('flower_price')
            formatted_price = "N/A"
            if raw_price is not None:
                try:
                    product_price_float = float(raw_price) # Keep the float value for calculations if needed later
                    formatted_price = f"{product_price_float:.2f}"
                except (ValueError, TypeError) as price_err:
                     app.logger.error(f"Error formatting price for product {product_id_str} in /buy. Raw price: '{raw_price}'. Error: {price_err}")
                     # If price is invalid, user shouldn't be able to buy it. Redirect.
                     flash("Product price information is invalid. Cannot proceed.", "error")
                     return redirect(url_for('main_div'))
            else:
                 app.logger.error(f"Product {product_id_str} is missing 'flower_price'. Cannot proceed.")
                 flash("Product price information is missing. Cannot proceed.", "error")
                 return redirect(url_for('main_div'))

            product['flower_price_formatted'] = formatted_price
            product['flower_price_float'] = product_price_float # Pass float price too if needed

            # --- Image URL Generation ---
            image_url = None
            image_id = product.get('image_id')
            try:
                if image_id and isinstance(image_id, ObjectId):
                    image_url = url_for('get_image', image_id=str(image_id))
                else:
                     image_url = url_for('static', filename='images/placeholder.png')
                product['image_url'] = image_url
            except Exception as url_err:
                 app.logger.error(f"Error generating image URL for product {product_id_str} in /buy. Image ID: '{image_id}'. Error: {url_err}", exc_info=True)
                 product['image_url'] = url_for('static', filename='images/placeholder.png') # Fallback

            app.logger.debug(f"Product found for buy page: {product.get('flower_name', 'N/A')}")
            # Pass empty submitted_data initially
            return render_template("buy.html", product=product, product_id_str=product_id_str, submitted_data={}, username=current_user.username)

        except bson_errors.InvalidId:
            app.logger.warning(f"Invalid ObjectId format from buy form: {product_id_str}")
            flash("Invalid product ID format.", "error")
            return redirect(url_for('main_div'))
        except pymongo.errors.PyMongoError as db_err:
            app.logger.error(f"Database error fetching product {product_id_str} for buy page: {db_err}")
            flash("Database error loading product details.", "error")
            return redirect(url_for('main_div'))
        except Exception as e:
            # Log the specific exception and product data (if retrieved)
            app.logger.exception(f"Unexpected error processing product {product_id_str} for buy page. Product data (if retrieved): {product}")
            flash("Could not load product details due to an unexpected error.", "error")
            return redirect(url_for('main_div'))

    elif request.method == 'GET':
        # If GET request, redirect to main page. User must select product first.
        flash("Please select a product from the main page to buy.", "info")
        return redirect(url_for('main_div'))
    else:
        # Fallback redirect if method is neither POST nor GET
         app.logger.warning(f"Unsupported HTTP method '{request.method}' used for /buy route.")
         return redirect(url_for('main_div'))


@main.route("/submit", methods=['POST'])
@login_required # Require login to submit order
def submit():
    """Handles the submission of an order."""
    app.logger.info(f"--- Accessing '/submit' route by user: {current_user.username} ---")
    if not check_db_connection():
         flash("Database connection error. Cannot process order.", "error")
         # Use request.referrer to redirect back to the buy page if possible
         return redirect(request.referrer or url_for('main_div'))

    form_data = request.form
    app.logger.debug(f"Received Order Form Data: {dict(form_data)}")

    # Extract and validate crucial IDs and quantity first
    order_type = form_data.get('order_type')
    product_id_str = form_data.get('product_id')
    quantity_str = form_data.get('quan')
    product_name_from_form = form_data.get('product') # Get name from form too

    # --- Basic Validation ---
    if not product_id_str or not quantity_str or not order_type or not product_name_from_form:
        flash("Missing required order information. Please try again.", "error")
        # Try redirecting back if product_id is available, otherwise main page
        if product_id_str:
            # Need to simulate a POST to /buy which isn't straightforward. Redirecting to main is safer.
            # Or, store the failed form data in session and re-render /buy? Complex.
            app.logger.warning("Submit failed: Missing core fields. Redirecting to main.")
            return redirect(url_for('main_div'))
        else:
            app.logger.warning("Submit failed: Missing product_id and other fields. Redirecting to main.")
            return redirect(url_for('main_div'))

    try:
        oid = ObjectId(product_id_str)
        quantity_val = int(quantity_str)
        if quantity_val <= 0:
            raise ValueError("Quantity must be positive.")
    except bson_errors.InvalidId:
        flash("Invalid product ID submitted.", "error")
        return redirect(url_for('main_div'))
    except (ValueError, TypeError):
        flash("Invalid quantity submitted. Please enter a whole number greater than 0.", "error")
        # Redirect back to the buy page for this product_id if possible
        # We need to trigger a POST-like behavior to /buy or pass product_id via GET
        # Simplest robust way: redirect to main, user has to re-select.
        return redirect(url_for('main_div'))


    # Fetch Product Details from DB (Verify price and existence)
    product = None
    try:
        product = products_collection.find_one({'_id': oid})
        if product is None:
             raise ValueError(f"Product with ID {product_id_str} not found in database.")

        # Verify product name matches (simple check)
        db_product_name = product.get('flower_name', '')
        if db_product_name.lower() != product_name_from_form.lower():
             app.logger.warning(f"Product name mismatch! Form: '{product_name_from_form}', DB: '{db_product_name}' for ID {product_id_str}")
             # Decide action: reject order or use DB name? Using DB name is safer.
             product_name_to_use = db_product_name
        else:
             product_name_to_use = db_product_name # Use consistent name from DB

        # Re-prepare product data for potential re-render on validation error below
        # (We need this *before* the validation checks)
        product['_id'] = str(product['_id']) # String ID for template
        product['flower_price_formatted'] = f"{product.get('flower_price', 0):.2f}"
        image_id = product.get('image_id')
        product['image_url'] = url_for('get_image', image_id=str(image_id)) if image_id and isinstance(image_id, ObjectId) else url_for('static', filename='images/placeholder.png')

    except (ValueError, pymongo.errors.PyMongoError) as find_err:
        app.logger.error(f"Error finding/validating product {product_id_str} during submission: {find_err}")
        flash("Error retrieving product details for order. Please try again.", "error")
        return redirect(url_for('main_div'))
    except Exception as fetch_err:
        app.logger.exception(f"Unexpected error refetching product {product_id_str} during submission:")
        flash("Unexpected error retrieving product details.", "error")
        return redirect(url_for('main_div'))

    # --- Field Validation (Contact Info, Address) ---
    required_fields = ['name', 'phone', 'email']
    if order_type == 'delivery':
        required_fields.append('address')
    elif order_type not in ['pickup', 'delivery']:
        flash(f"Invalid order type received: {order_type}", "error")
        app.logger.warning(f"Invalid order type '{order_type}' submitted.")
        # Re-render buy page with error
        return render_template("buy.html", product=product, product_id_str=product_id_str, error="Invalid order type selected.", submitted_data=form_data, username=current_user.username)

    validation_error = None
    record = {}
    for field in required_fields:
        field_value = form_data.get(field)
        # Handle address specially for pickup
        if order_type == 'pickup' and field == 'address':
            record[field] = 'N/A' # Store N/A explicitly
            continue
        # Check other required fields
        if field_value is None or not field_value.strip():
            # Map field names to user-friendly names
            field_map = {'name': 'Name', 'quan': 'Quantity', 'phone': 'Phone Number', 'email': 'Email', 'address': 'Address', 'product': 'Product Name'}
            pretty_field_name = field_map.get(field, field.replace('_', ' ').title())
            validation_error = f"Missing required field: {pretty_field_name}"
            break
        # Store validated/cleaned data
        record[field] = field_value.strip()

    # Add the already validated parts
    record['product_id'] = oid
    record['quan'] = quantity_val
    record['order_type'] = order_type
    record['product'] = product_name_to_use # Use verified name

    if validation_error:
        flash(validation_error, "error")
        app.logger.warning(f"Order submission failed validation: {validation_error}")
        # Re-render buy page with error and submitted data
        return render_template("buy.html", product=product, product_id_str=product_id_str, error=validation_error, submitted_data=form_data, username=current_user.username)

    # --- Price Calculation (use DB price) ---
    try:
        unit_price = float(product.get('flower_price', 0)) # Price stored as float in DB
        if unit_price <= 0:
             # This should have been caught during the /buy page load, but double check.
             app.logger.error(f"Product {product_id_str} has invalid price in DB: {unit_price}")
             raise ValueError("Product price is invalid or zero.")
        calculated_total_price = round(unit_price * quantity_val, 2)
        app.logger.info(f"Server Calculated Price for order: {unit_price} * {quantity_val} = {calculated_total_price}")
    except (ValueError, TypeError, AttributeError) as price_err:
        app.logger.error(f"Error calculating total price: {price_err}. Product Price from DB: '{product.get('flower_price')}'")
        flash("Error determining product price. Cannot complete order.", "error")
        return render_template("buy.html", product=product, product_id_str=product_id_str, error="Product price error.", submitted_data=form_data, username=current_user.username)

    # --- Order Insertion ---
    try:
        order_to_insert = {
            'product_id': record['product_id'], # ObjectId
            'product_name': record['product'],   # Verified product name
            'quantity': record['quan'],
            'unit_price': unit_price,            # Price from DB
            'total_price': calculated_total_price, # Calculated price
            'order_type': record['order_type'],
            'customer_name': record['name'],
            'customer_phone': record['phone'],
            'customer_email': record['email'],
            'address': record.get('address', 'N/A'), # Get address, default N/A
            'order_date': datetime.datetime.utcnow(),
            'status': 'Pending', # Default status
            'status_last_updated': datetime.datetime.utcnow(),
            'user_id': ObjectId(current_user.id) # Link to logged-in user (already checked @login_required)
        }
        app.logger.info(f"Associating order with user_id: {current_user.id}")

        app.logger.debug(f"Attempting to insert order: {order_to_insert}")
        insert_result = orders_collection.insert_one(order_to_insert)
        new_order_id = insert_result.inserted_id
        app.logger.info(f"Order insertion successful. ID: {new_order_id}")

        # Redirect to Bill page
        order_id_str_for_url = str(new_order_id)
        redirect_url = url_for('show_bill', order_id=order_id_str_for_url)
        app.logger.debug(f"Generated redirect URL for bill: {redirect_url}")
        flash("Thank you! Your order has been placed successfully.", "success")
        return redirect(redirect_url)

    except pymongo.errors.PyMongoError as db_err:
        error_message = "A database error occurred while saving your order. Please try again."
        app.logger.error(f"Database error inserting order: {db_err}")
        flash(error_message, "error")
        return render_template("buy.html", product=product, product_id_str=product_id_str, error=error_message, submitted_data=form_data, username=current_user.username)
    except Exception as e:
        error_message = "An unexpected error occurred while processing your order. Please try again later."
        app.logger.exception("Unexpected error processing order submission:")
        flash(error_message, "error")
        return render_template("buy.html", product=product, product_id_str=product_id_str, error=error_message, submitted_data=form_data, username=current_user.username)


@main.route('/bill/<string:order_id>')
@login_required # User should be logged in to see their bill
def show_bill(order_id):
    """Displays the order confirmation/bill page."""
    app.logger.info(f"\n--- Accessing '/bill/{order_id}' route for user: {current_user.username} ---")
    # app.logger.debug(f"[BILL]: Received order_id string: '{order_id}'")
    if not check_db_connection():
        app.logger.error("--- [BILL] DB connection check failed. ---")
        flash("Database connection error. Cannot retrieve bill.", "error")
        return redirect(url_for('main_div'))

    try:
        order_oid = ObjectId(order_id)
        # app.logger.debug(f"[BILL]: Converted to ObjectId: {order_oid}")
    except bson_errors.InvalidId:
        app.logger.error(f"[BILL]: FAILED ObjectId conversion for string: '{order_id}'")
        flash(f"Invalid Order ID format received.", "error")
        return redirect(url_for('main_div'))

    try:
        # app.logger.debug(f"--- [BILL] Querying for order _id: {order_oid} ---")
        order = orders_collection.find_one({'_id': order_oid})
        if not order:
            app.logger.warning(f"[BILL]: Order NOT FOUND in DB for _id {order_oid}.")
            flash(f"Order '{order_id}' not found.", "error")
            return redirect(url_for('main_div'))
        # app.logger.debug(f"[BILL]: Found order in DB for _id {order_oid}.")

        # --- Authorization Check: Ensure the order belongs to the current user ---
        order_user_id = order.get('user_id')
        if not order_user_id or str(order_user_id) != current_user.id:
            app.logger.warning(f"[BILL]: Unauthorized access attempt! User {current_user.id} tried to access order {order_id} belonging to user {order_user_id}.")
            flash("You are not authorized to view this order.", "error")
            return redirect(url_for('main_div')) # Or redirect to a user's order history page

        # Data extraction and formatting
        order_date_obj = parse_order_date(order.get('order_date'))
        order_date_str = order_date_obj.strftime("%Y-%m-%d %H:%M:%S UTC") if order_date_obj else "Unknown Date"

        try: quantity = int(order.get('quantity', 1))
        except (ValueError, TypeError): quantity = 1

        try: total_price_float = float(order.get('total_price', 0))
        except (ValueError, TypeError): total_price_float = 0.0

        try: price_per_unit = float(order.get('unit_price', 0))
        except (ValueError, TypeError): price_per_unit = 0.0

        order_type = order.get('order_type', 'N/A')
        address = order.get('address', 'N/A')

        bill_data = {
            'order_id': order_id,
            'date': order_date_str,
            'customer_name': order.get('customer_name', 'N/A'),
            'order_type': order_type.capitalize(),
            'address': address if order_type.lower() == 'delivery' else 'N/A (Pickup)',
            'product_name': order.get('product_name', 'Unknown Item'),
            'quantity': quantity,
            'price_per_unit_formatted': f"{price_per_unit:.2f}",
            'total_price_formatted': f"{total_price_float:.2f}",
            'store_name': "FLORAAI SHOP", # TODO: Make this configurable?
            'thank_you': "Thank you for your order!"
        }
        # app.logger.debug(f"--- [BILL] Data prepared for template: {bill_data} ---")
        return render_template('bill.html', bill=bill_data, username=current_user.username)

    except pymongo.errors.PyMongoError as db_err:
        app.logger.exception(f"--- [BILL] DATABASE ERROR during lookup/processing for order {order_id}:")
        flash("Database error retrieving bill details.", "error")
        return redirect(url_for('main_div'))
    except Exception as e:
        app.logger.exception(f"--- [BILL] UNEXPECTED ERROR in show_bill function for order {order_id}:")
        flash("An unexpected error occurred generating the bill.", "error")
        return redirect(url_for('main_div'))


@main.route('/contact', methods=['POST'])
def contact():
    """Handles the contact form submission."""
    app.logger.info("--- Accessing '/contact' route ---")
    if not check_db_connection():
        flash("Database connection error. Cannot submit contact form.", "error")
        return redirect(url_for('main_div') + '#contact') # Anchor to contact section

    form_data = request.form
    # app.logger.debug(f"Contact form data: {dict(form_data)}")
    name = form_data.get('name', '').strip()
    email = form_data.get('email', '').strip()
    message = form_data.get('message', '').strip()

    if not name or not email or not message:
         flash("Please fill out all fields in the contact form.", "warning")
         return redirect(url_for('main_div') + '#contact')

    # Basic email format check (simple)
    if '@' not in email or '.' not in email.split('@')[-1]:
        flash("Please enter a valid email address.", "warning")
        return redirect(url_for('main_div') + '#contact')

    contact_entry = {
        'name': name,
        'email': email,
        'message': message,
        'submission_date': datetime.datetime.utcnow(),
        'status': 'New' # Optional: track status (New, Read, Replied)
    }
    try:
        # app.logger.debug(f"Attempting to insert contact entry: {contact_entry}")
        insert_result = contact_collection.insert_one(contact_entry)
        app.logger.info(f"Contact entry inserted with ID: {insert_result.inserted_id}")
        flash("Thank you for your message! We'll get back to you soon.", "success")
        return redirect(url_for('main_div') + '#home') # Redirect to top after success
    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"Error inserting contact message into database: {e}")
        flash("There was an issue submitting your message due to a database error. Please try again later.", "error")
        return redirect(url_for('main_div') + '#contact')
    except Exception as e:
        app.logger.exception("An unexpected error occurred during contact submission:")
        flash("An unexpected error occurred. Please try again later.", "error")
        return redirect(url_for('main_div') + '#contact')


@main.route('/review', methods=['POST'])
@login_required # Require login to submit reviews
def review():
    """Handles review submission."""
    app.logger.info(f"--- Accessing '/review' route by user: {current_user.username} ---")
    if not check_db_connection():
        app.logger.error("--- Review: DB connection check failed. ---")
        flash("Database connection error. Cannot submit review.", "error")
        return redirect(url_for('main_div') + '#reviews') # Anchor

    review_text = request.form.get('review_text', '').strip()
    app.logger.debug(f"--- Review form data 'review_text': {review_text!r} ---")

    if not review_text:
        app.logger.warning("--- Review text validation failed (empty). ---")
        flash("Please enter a review before submitting.", "warning")
        return redirect(url_for('main_div') + '#reviews')

    MAX_REVIEW_LENGTH = 1000 # Define a max length
    if len(review_text) > MAX_REVIEW_LENGTH:
        flash(f"Review text is too long (max {MAX_REVIEW_LENGTH} characters).", "warning")
        return redirect(url_for('main_div') + '#reviews')

    review_document = {
        'text': review_text,
        'submitted_at': datetime.datetime.utcnow(),
        'username': current_user.username, # Get from logged-in user
        'user_id': ObjectId(current_user.id) # Store user's ObjectId
    }
    app.logger.info(f"Review submitted by user: {current_user.username} ({current_user.id})")
    app.logger.debug(f"--- Prepared review document: {review_document} ---")

    try:
        # app.logger.debug("--- Attempting review insert_one ---")
        insert_result = review_collection.insert_one(review_document)
        app.logger.info(f"--- Review insert_one succeeded, Result ID: {insert_result.inserted_id} ---")
        flash("Thank you for your review!", "success")
        return redirect(url_for('main_div') + '#reviews') # Anchor
    except pymongo.errors.PyMongoError as e:
        app.logger.error(f"--- REVIEW DB ERROR (PyMongoError): {e} ---")
        flash("There was an issue submitting your review due to a database error.", "error")
        return redirect(url_for('main_div') + '#reviews')
    except Exception as e:
        app.logger.exception(f"--- REVIEW UNEXPECTED ERROR (Other Exception):")
        flash("An unexpected error occurred while submitting your review.", "error")
        return redirect(url_for('main_div') + '#reviews')


# --- NEW PROFILE ROUTES ---

@main.route("/profile")
@login_required
def profile():
    """Display the user's profile information page."""
    username = current_user.username
    user_id = current_user.id
    app.logger.info(f"--- Accessing '/profile' route for user: {username} ({user_id}) ---")

    photo_url = None
    user_orders = [] # Initialize orders list

    if not check_db_connection(check_users=True):
        flash("Database connection error. Cannot load profile details.", "error")
        return render_template("profile.html", username=username, photo_url=None, orders=[], active_tab='details')

    try:
        user_id_obj = ObjectId(user_id)

        # Fetch User Details (Photo)
        user_data = users_collection.find_one({"_id": user_id_obj}, {"photo_id": 1})
        if user_data and user_data.get("photo_id"):
            photo_id = user_data["photo_id"]
            if isinstance(photo_id, ObjectId): # Check type just in case
                try:
                    photo_id_str = str(photo_id)
                    photo_url = url_for('get_photo', photo_id=photo_id_str)
                    # app.logger.debug(f"   Found photo_id: {photo_id_str}. Generated photo URL: {photo_url}")
                except Exception as url_gen_error:
                    app.logger.error(f"   Error generating photo URL for photo_id '{photo_id}': {url_gen_error}")
            else:
                 app.logger.warning(f"   User {username} ({user_id}) has invalid photo_id type in DB: {type(photo_id)}")
        # If no photo_id or it's invalid, photo_url remains None, use default in template

        # Fetch User Orders
        # Sort by most recent first
        user_orders_cursor = orders_collection.find({"user_id": user_id_obj}).sort('order_date', pymongo.DESCENDING)
        for order in user_orders_cursor:
             try:
                 order_datetime = parse_order_date(order.get('order_date'))
                 formatted_date = order_datetime.strftime("%Y-%m-%d %H:%M") if order_datetime else "Invalid Date"
                 try: formatted_price = f"{float(order.get('total_price', 0)):.2f}"
                 except (ValueError, TypeError): formatted_price = "N/A"

                 user_orders.append({
                     'order_id': str(order['_id']),
                     'date': formatted_date,
                     'product_name': order.get('product_name', 'N/A'),
                     'quantity': order.get('quantity', 'N/A'),
                     'total_price': formatted_price,
                     'status': order.get('status', 'Pending') # Show order status
                 })
             except Exception as order_proc_err:
                  app.logger.error(f"Error processing order {order.get('_id')} for profile page: {order_proc_err}")


    except bson_errors.InvalidId:
        app.logger.error(f"   Error: Invalid ObjectId format for current user ID: {user_id}")
        flash("Internal error: Invalid user session data.", "error")
        logout_user()
        return redirect(url_for('login'))
    except pymongo.errors.PyMongoError as db_error:
        app.logger.error(f"   Database error fetching data for profile ({user_id}): {db_error}")
        flash("Could not load profile details due to a database error.", "error")
    except Exception as e:
        app.logger.exception(f"   Unexpected error fetching data for profile ({user_id}):")
        flash("An unexpected error occurred while loading profile details.", "error")

    # Determine active tab based on query param or default to 'details'
    active_tab = request.args.get('tab', 'details')

    # Make sure 'templates/profile.html' exists
    return render_template(
        "profile.html",
        username=username,
        photo_url=photo_url,  # Pass URL or None
        orders=user_orders,   # Pass user's orders
        active_tab=active_tab # Pass active tab name
    )


@main.route("/upload_photo", methods=["POST"])
@login_required
def upload_photo():
    """Upload and save the profile photo."""
    user_id = current_user.id
    app.logger.info(f"--- Accessing '/upload_photo' route for user {user_id} ---")

    if 'photo' not in request.files:
        flash("No photo file part selected.", "warning")
        return redirect(url_for("profile", tab="details"))

    photo = request.files['photo']
    if photo.filename == '':
        flash("No file selected for upload.", "warning")
        return redirect(url_for("profile", tab="details"))

    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    if '.' not in photo.filename or \
       photo.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        flash("Invalid file type. Please upload an image (png, jpg, jpeg, gif).", "warning")
        return redirect(url_for("profile", tab="details"))

    # Optional: Add file size validation
    # MAX_FILE_SIZE = 5 * 1024 * 1024 # 5 MB
    # photo.seek(0, os.SEEK_END) # Go to end of file
    # file_length = photo.tell() # Get size
    # photo.seek(0) # Reset stream position
    # if file_length > MAX_FILE_SIZE:
    #     flash(f"File too large. Maximum size is {MAX_FILE_SIZE // 1024 // 1024} MB.", "warning")
    #     return redirect(url_for("profile", tab="details"))

    if not check_db_connection(check_users=True):
        flash("Database connection error. Cannot upload photo.", "error")
        return redirect(url_for("profile", tab="details"))

    new_photo_id = None # Initialize in outer scope for potential cleanup
    try:
        user_id_obj = ObjectId(user_id)

        # Find existing photo_id *before* uploading new one
        user_doc = users_collection.find_one({"_id": user_id_obj}, {"photo_id": 1})
        old_photo_id = user_doc.get('photo_id') if user_doc else None

        # Store the new photo in GridFS
        photo.seek(0)
        new_photo_id = fs.put(photo, content_type=photo.content_type, filename=photo.filename, user_id=user_id_obj) # Add user_id metadata
        app.logger.info(f"Uploaded new profile photo {new_photo_id} for user {user_id}")

        # Store new photo_id in the user's document
        update_result = users_collection.update_one(
            {"_id": user_id_obj},
            {"$set": {"photo_id": new_photo_id}}
        )

        if update_result.modified_count > 0:
             flash("Profile photo updated successfully!", "success")
             # Delete old photo *after* successful DB update
             if old_photo_id and isinstance(old_photo_id, ObjectId) and old_photo_id != new_photo_id:
                 try:
                     fs.delete(old_photo_id)
                     app.logger.info(f"Deleted old profile photo {old_photo_id} for user {user_id}")
                 except GridFSNoFile:
                     app.logger.warning(f"Old profile photo {old_photo_id} not found in GridFS for user {user_id}, continuing.")
                 except Exception as del_e:
                     app.logger.error(f"Error deleting old photo {old_photo_id}: {del_e}")
             elif old_photo_id and not isinstance(old_photo_id, ObjectId):
                  app.logger.warning(f"Old photo_id {old_photo_id} for user {user_id} was not a valid ObjectId, not deleting.")

        elif update_result.matched_count == 0:
             # This means the user_id was invalid somehow, despite being logged in
             app.logger.error(f"Could not find user {user_id_obj} to update photo_id {new_photo_id}.")
             flash("User record not found during update. Please log in again.", "error")
             # Rollback: Delete the newly uploaded photo if user link failed
             if new_photo_id:
                 try: fs.delete(new_photo_id); app.logger.info(f"Cleaned up photo {new_photo_id} due to user not found.")
                 except Exception as cl: app.logger.error(f"Failed cleanup of photo {new_photo_id}: {cl}")
             logout_user()
             return redirect(url_for('login'))

        else: # modified_count == 0 and matched_count > 0
             app.logger.warning(f"Photo stored ({new_photo_id}), but users collection update reported 0 modifications for user {user_id_obj}. Possibly same photo uploaded again?")
             # Potentially the same photo_id was set again. Not necessarily an error.
             flash("Profile photo uploaded, but no change was needed in user record.", "info")


    except bson_errors.InvalidId:
        app.logger.error(f"   Error: Invalid ObjectId format for current user ID: {user_id}")
        flash("Internal error: Invalid user session data.", "error")
        logout_user() # Log out user with bad session ID
        return redirect(url_for('login'))
    except pymongo.errors.PyMongoError as db_err:
        app.logger.error(f"Database error during photo upload for user {user_id}: {db_err}")
        flash("A database error occurred while uploading the photo.", "error")
        # Rollback potential GridFS upload if DB fails
        if new_photo_id:
            try: fs.delete(new_photo_id); app.logger.info(f"Cleaned up photo {new_photo_id} due to DB error.")
            except Exception as cle: app.logger.error(f"Failed cleanup of photo {new_photo_id}: {cle}")
    except gridfs.errors.GridFSError as fs_err:
        app.logger.error(f"GridFS error during photo upload for user {user_id}: {fs_err}")
        flash("An error occurred storing the photo file.", "error")
    except Exception as e:
        app.logger.exception(f"Unexpected error during photo upload for user {user_id}:")
        flash("An unexpected error occurred during photo upload.", "error")
        # Rollback potential GridFS upload if other errors occur after put
        if new_photo_id:
             try: fs.delete(new_photo_id); app.logger.info(f"Cleaned up photo {new_photo_id} due to unexpected error.")
             except Exception as cle: app.logger.error(f"Failed cleanup of photo {new_photo_id}: {cle}")

    return redirect(url_for("profile", tab="details"))


@main.route("/get_photo/<string:photo_id>")
def get_photo(photo_id):
    """Serves a profile photo file from GridFS, with default avatar fallback."""
    default_avatar_path = 'static/images/default_avatar.png'
    default_mimetype = 'image/png'
    # app.logger.debug(f"--- Accessing '/get_photo/{photo_id}' route ---")

    if not check_db_connection():
         try:
             # Make sure you have a default avatar at 'static/images/default_avatar.png'
             return send_file(default_avatar_path, mimetype=default_mimetype)
         except FileNotFoundError:
             app.logger.error(f"Default avatar '{default_avatar_path}' not found.")
             return "Service unavailable", 503 # DB error and no fallback

    try:
        oid = ObjectId(photo_id)
    except bson_errors.InvalidId:
         app.logger.warning(f"Invalid ObjectId format for photo: {photo_id}")
         try:
             return send_file(default_avatar_path, mimetype=default_mimetype)
         except FileNotFoundError:
            app.logger.error(f"Default avatar '{default_avatar_path}' not found.")
            return "Invalid photo ID", 400 # Invalid ID and no fallback

    try:
        image_file = fs.get(oid)
        # Optional Security: Check if the image is associated with a user and if access is allowed.
        # For profile photos, generally okay to serve if the ID is known, but could add checks.
        # Example: Check if associated user_id matches current_user.id if privacy is needed.

        return send_file(
            BytesIO(image_file.read()),
            mimetype=image_file.content_type or 'image/jpeg',
            as_attachment=False # Display inline
        )
    except GridFSNoFile:
         app.logger.warning(f"Photo not found in GridFS: {photo_id}")
         try:
             return send_file(default_avatar_path, mimetype=default_mimetype)
         except FileNotFoundError:
             app.logger.error(f"Default avatar '{default_avatar_path}' not found.")
             return "Photo not found", 404 # File not found in GridFS and no fallback
    except pymongo.errors.PyMongoError as db_err:
        app.logger.error(f"Database error retrieving photo {photo_id}: {db_err}")
        # Don't show db error to user, try sending default avatar
        try:
            return send_file(default_avatar_path, mimetype=default_mimetype)
        except FileNotFoundError:
            return "Error retrieving photo", 500
    except Exception as e:
        app.logger.exception(f"Unexpected error retrieving photo {photo_id}:")
        try:
            return send_file(default_avatar_path, mimetype=default_mimetype)
        except FileNotFoundError:
            return "Error retrieving photo", 500


@main.route("/edit_password", methods=["POST"])
@login_required
def edit_password():
    """Update user password."""
    user_id = current_user.id
    app.logger.info(f"--- Password change attempt for user: {user_id} ---")

    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")

    if not current_password or not new_password or not confirm_password:
        flash("All password fields are required.", "warning")
        return redirect(url_for("profile", tab="security"))

    if new_password != confirm_password:
        flash("New password and confirmation password do not match.", "warning")
        return redirect(url_for("profile", tab="security"))

    if len(new_password) < 8:
         flash("New password must be at least 8 characters long.", "warning")
         return redirect(url_for("profile", tab="security"))
    # TODO: Add more complexity checks if desired (regex for uppercase, number, symbol)

    if not check_db_connection(check_users=True):
        flash("Database connection error. Cannot update password.", "error")
        return redirect(url_for("profile", tab="security"))

    try:
        user_id_obj = ObjectId(user_id)
        user = users_collection.find_one({"_id": user_id_obj})

        if not user:
            app.logger.error(f"Error: User {user_id} not found in DB during password change.")
            flash("User not found. Please log in again.", "error")
            logout_user()
            return redirect(url_for("login"))

        if not bcrypt.check_password_hash(user["password"], current_password):
            app.logger.warning(f"Password change failed for {user_id}: Incorrect current password.")
            flash("Incorrect current password.", "danger")
            return redirect(url_for("profile", tab="security"))

        # Check if new password is the same as the old one (re-check hash)
        if bcrypt.check_password_hash(user["password"], new_password):
            flash("New password cannot be the same as the old password.", "warning")
            return redirect(url_for("profile", tab="security"))

        # Hash and update password
        hashed_password = bcrypt.generate_password_hash(new_password).decode("utf-8")
        update_result = users_collection.update_one(
            {"_id": user_id_obj},
            {"$set": {"password": hashed_password}}
        )

        if update_result.modified_count > 0:
            app.logger.info(f"Password updated successfully for user {user_id}")
            flash("Password updated successfully!", "success")
        else:
             app.logger.warning(f"Password update command sent for user {user_id}, but DB reported 0 modifications.")
             # This might happen if the hash calculation somehow resulted in the same hash (unlikely with bcrypt)
             # Or if there was a concurrent update or issue.
             flash("Password update may not have completed successfully. Please try again.", "warning")

    except bson_errors.InvalidId:
        app.logger.error(f"   Error: Invalid ObjectId format for current user ID: {user_id}")
        flash("Internal error: Invalid user session data.", "error")
        logout_user()
        return redirect(url_for('login'))
    except pymongo.errors.PyMongoError as db_err:
        app.logger.error(f"Database error during password update for user {user_id}: {db_err}")
        flash("A database error occurred while updating the password.", "error")
    except Exception as e:
        app.logger.exception(f"Unexpected error during password update for user {user_id}:")
        flash("An unexpected error occurred during password update.", "error")

    return redirect(url_for("profile", tab="security"))

# --- END NEW PROFILE ROUTES ---


# --- Main Execution ---
if __name__ == '__main__':
    # Ensure required directories (templates, static/images) exist if needed.
    # Ensure default avatar exists at 'static/images/default_avatar.png'.
    # Ensure placeholder image exists at 'static/images/placeholder.png'.
    app.logger.info("Starting Flask application...")
    # Use host='0.0.0.0' to be accessible on network (e.g., in Docker)
    # Use debug=False for production (IMPORTANT!)
    # threaded=True is generally good for handling concurrent requests, especially with I/O like GridFS.
    main.run(host='0.0.0.0', port=5000, debug=True, threaded=True) # CHANGE debug=False for production
