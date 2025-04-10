# FloraAI-Shop-
# FloraAI-Shop - Flask Web Application

**Author:** Manosakthi Thiyagarajan

## Description

FloraAI-Shop is a web application built with Flask and MongoDB that allows users to browse, order, and review flower products. It includes separate functionalities for regular users and administrators. Administrators can manage products, view orders, manage reviews, and monitor basic site statistics via a dashboard.

## Features

**User Features:**

*   User Registration and Login
*   Password Hashing (via Flask-Bcrypt)
*   Browse Products
*   View Product Details
*   Order Products (Pickup or Delivery)
*   View Order Confirmation/Bill
*   Submit Product Reviews
*   Submit Contact Form Messages
*   User Profile Management:
    *   View Profile Details
    *   Upload Profile Photo
    *   View Order History
    *   Change Password

**Admin Features:**

*   Separate Admin Login (Currently basic - **See Security Notes**)
*   Admin Dashboard:
    *   View Statistics (Total Earnings, Orders Today/Month, Product/User/Order/Review/Contact Counts)
    *   Charts for Orders per Day and Most Sold Products
    *   View and Manage Products (Add, Edit, Delete)
    *   View and Manage Orders (Update Order Status)
    *   View and Manage Reviews (Delete)
    *   View Contact Form Submissions (Implied, viewable in DB or could be added to dashboard)
*   Product Image Upload/Management using GridFS

## Technologies Used

*   **Backend:** Python, Flask
*   **Database:** MongoDB
*   **File Storage:** MongoDB GridFS (for product & profile images)
*   **Authentication:** Flask-Login, Flask-Bcrypt
*   **Frontend:** HTML, CSS, JavaScript (Templates use Jinja2)
*   **Other Libraries:** PyMongo, BSON, Werkzeug (via Flask)

## Prerequisites

*   Python 3.7+
*   `pip` (Python package installer)
*   MongoDB Server (Local instance or a cloud service like MongoDB Atlas)
*   Git (Optional, for cloning)

## Setup and Installation

1.  **Clone the repository (if applicable):**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment (Recommended):**
    ```bash
    # Windows
    python -m venv venv
    .\venv\Scripts\activate

    # macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    Create a `requirements.txt` file with the following content:
    ```
    Flask
    pymongo[srv] # [srv] is needed for MongoDB Atlas connection strings
    Flask-Bcrypt
    Flask-Login
    # gridfs is part of pymongo, no separate install needed
    # Add other specific dependencies if any (e.g., certifi if required by your MongoDB setup)
    ```
    Then install them:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure MongoDB Connection:**
    *   Open the `main.py` file.
    *   Locate the section marked `### --- PASTE YOUR MONGODB CONNECTION CODE HERE --- ###`.
    *   Replace the placeholder connection code with your actual MongoDB connection string and database setup. Ensure the `users_collection` is correctly initialized (`users_collection = mydb["USERS"]`).
    *   **IMPORTANT:** For production, avoid hardcoding credentials. Use environment variables or a configuration file.

5.  **Configure Flask Secret Key:**
    *   In `main.py`, find the line `main.secret_key = '3112'`.
    *   **IMPORTANT:** Change this to a long, random, and secret string. For production, load this from an environment variable.

6.  **Admin Credentials:**
    *   **CRITICAL SECURITY NOTE:** The current admin login uses hardcoded credentials (`admin`/`admin123`) in the `admin_login` route. This is **highly insecure**.
    *   **Recommendation:** Implement proper role-based access control. Add an 'is_admin' field (or similar) to your `USERS` collection and check this field during admin login after verifying the hashed password. Update the `admin_required` decorator accordingly.

7.  **Required Static Files:**
    *   Ensure you have the following image files in a `static/images/` directory within your project:
        *   `placeholder.png` (Used when a product has no image)
        *   `default_avatar.png` (Used when a user has no profile photo)

## Running the Application

1.  Make sure your MongoDB server is running and accessible.
2.  Ensure your virtual environment is activated.
3.  Run the Flask development server:
    ```bash
    python main.py
    ```
4.  Open your web browser and navigate to `http://127.0.0.1:5000/` or `http://localhost:5000/`. (The code uses `host='0.0.0.0'`, so it might also be accessible via your machine's local network IP address).

## Important Notes & Security

*   **Admin Credentials:** As mentioned above, the hardcoded admin credentials are a major security risk and **must** be changed for any real-world use.
*   **Secret Key:** Always use a strong, unique secret key and keep it confidential, especially in production.
*   **Debug Mode:** The application currently runs with `debug=True`. **Never** run with debug mode enabled in a production environment, as it can expose sensitive information and allow arbitrary code execution. Set `debug=False` in `main.run()` for production.
*   **Input Validation:** While some validation is present, ensure all user inputs (forms, URL parameters) are rigorously validated and sanitized on the server-side to prevent security vulnerabilities like Cross-Site Scripting (XSS) and injection attacks.
*   **Error Handling:** The application includes basic error handling and logging, but review and enhance it for robustness in production.
*   **Dependencies:** Keep dependencies updated to patch potential security vulnerabilities.
*   **HTTPS:** Always use HTTPS in production to encrypt communication between the client and server.
