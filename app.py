from flask import Flask, render_template, redirect, url_for, request, flash
import sqlite3
import os
import RPi.GPIO as GPIO

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Initialize GPIO settings
GPIO.setmode(GPIO.BCM)  # Use Broadcom pin numbering

def initialize_database(num_devices, gpio_values):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Create tables if they don't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plug (
            plugID TEXT PRIMARY KEY CHECK (length(plugID) = 3),
            name TEXT NOT NULL CHECK (length(name) <= 10),
            gpio INTEGER NOT NULL CHECK (gpio BETWEEN 2 AND 26),
            state BOOLEAN NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timer (
            plugID TEXT PRIMARY KEY CHECK (length(plugID) = 3),
            thour INTEGER NOT NULL CHECK (thour BETWEEN 0 AND 23),
            tminute INTEGER NOT NULL CHECK (tminute BETWEEN 0 AND 59),
            tnewState BOOLEAN NOT NULL,
            tactive BOOLEAN NOT NULL,
            FOREIGN KEY (plugID) REFERENCES plug(plugID)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule (
            scheduleID INTEGER PRIMARY KEY AUTOINCREMENT,
            plugID TEXT NOT NULL CHECK (length(plugID) = 3),
            shour INTEGER NOT NULL CHECK (shour BETWEEN 0 AND 23),
            sminute INTEGER NOT NULL CHECK (sminute BETWEEN 0 AND 59),
            srepeat TEXT CHECK (length(srepeat) <= 23),
            snewStatus BOOLEAN NOT NULL,
            sactive BOOLEAN NOT NULL,
            FOREIGN KEY (plugID) REFERENCES plug(plugID)
        )
    ''')

    # Insert data into plug and timer tables based on user input
    for i in range(num_devices):
        plug_id = f'P{i+1:02}'  # Format as P01, P02, etc.
        name = f'Plug {i+1}'
        gpio = gpio_values[i]

        # Convert GPIO value to integer and check for validity
        if gpio is None or gpio == '':
            print(f"Invalid GPIO value for device {plug_id}")
            conn.close()
            raise ValueError("GPIO value cannot be empty.")

        cursor.execute('INSERT INTO plug (plugID, name, gpio, state) VALUES (?, ?, ?, ?)',
                       (plug_id, name, int(gpio), False))
        cursor.execute('INSERT INTO timer (plugID, thour, tminute, tnewState, tactive) VALUES (?, 0, 0, 0, 0)',
                       (plug_id,))

    conn.commit()
    conn.close()

def check_database():
    """Check if the database exists; if not, redirect to setup."""
    if not os.path.exists('piplug.db'):
        return False
    return True

def initialize_timer_tactive():
    """Set all `tactive` values in the `timer` table to False."""
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE timer SET tactive = 0")
    conn.commit()
    conn.close()

def setup_gpio_pins():
    """Set all GPIO pins in the `plug` table as outputs and turn them off."""
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute("SELECT gpio FROM plug")
    gpios = cursor.fetchall()
    for gpio in gpios:
        gpio_pin = gpio[0]
        GPIO.setup(gpio_pin, GPIO.OUT)
        GPIO.output(gpio_pin, GPIO.LOW)  # Turn off initially
    conn.close()

def turn_off_all_devices():
    """Turn off all devices by setting their GPIO pins to low."""
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute("SELECT gpio FROM plug")
    gpios = cursor.fetchall()
    for gpio in gpios:
        GPIO.output(gpio[0], GPIO.LOW)
    conn.close()

@app.before_first_request
def server_startup():
    """Run startup routines when the server first starts."""
    if not check_database():
        print("Database does not exist, redirecting to setup.")
        app.config['STARTUP_REDIRECT'] = True
    else:
        print("Initializing system configurations...")
        initialize_timer_tactive()
        setup_gpio_pins()
        turn_off_all_devices()
        app.config['STARTUP_REDIRECT'] = False

@app.route('/')
def index():
    """Main route that redirects to setup or index based on initialization."""
    if app.config.get('STARTUP_REDIRECT', False):
        return redirect(url_for('setup'))
    return redirect(url_for('index_html'))

# Check if piplug.db exists and redirect to index if it does
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if os.path.exists('piplug.db'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        num_devices = int(request.form.get('num_devices'))
        gpio_values = [request.form.get(f'gpio_{i+1}') for i in range(num_devices)]

        # Check for empty values or duplicates
        if '' in gpio_values or len(gpio_values) != len(set(gpio_values)):
            flash("Please check the GPIO values. Each GPIO value must be unique.", "error")
            return render_template('setup.html', num_devices=num_devices, gpio_values=gpio_values)

        # Call a function to initialize the database and tables
        try:
            initialize_database(num_devices, gpio_values)
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"An error occurred: {e}", "error")
            return render_template('setup.html', num_devices=num_devices, gpio_values=gpio_values)

    return render_template('setup.html', show_log_button=False)

@app.route('/index')
def index_html():
    """Main index page."""
    return "Index Page with device control"

#@app.before_request
#def handle_redirect():
#    """Check if startup redirection is needed."""
#    if app.config.get('STARTUP_REDIRECT', False) and request.endpoint != 'setup':
#        return redirect(url_for('setup'))

#@app.teardown_appcontext
#def server_shutdown(exception=None):
#    """Run shutdown routines when the server is about to shut down."""
#    print("Cleaning up GPIO...")
#    GPIO.cleanup()
#    print("Server is shutting down...")

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        GPIO.cleanup()  # Ensure GPIO cleanup if the server crashes
