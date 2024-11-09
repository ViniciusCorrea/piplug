from flask import Flask, render_template, redirect, url_for, request, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from datetime import datetime, timedelta
from tzlocal import get_localzone
import RPi.GPIO as GPIO
import sqlite3
import atexit
import pytz
import os

# Initialize the Flask application
app = Flask(__name__)

app.secret_key = 'your_secret_key'

# Configure the APScheduler
scheduler = BackgroundScheduler()
scheduler.start()

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
            srepeat TEXT CHECK (length(srepeat) <= 30),
            snewStatus BOOLEAN NOT NULL,
            sactive BOOLEAN NOT NULL,
            FOREIGN KEY (plugID) REFERENCES plug(plugID)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log (
            logID INTEGER PRIMARY KEY AUTOINCREMENT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            plugID TEXT NOT NULL CHECK (length(plugID) = 3),
            origin TEXT CHECK (origin IN ('manual', 'sched', 'timer', 'start', 'end')),
            action TEXT NOT NULL CHECK (length(action) <= 10),
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

# Function to load active schedules from the database and schedule them
def load_active_schedules():
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Retrieve all active schedules from the database
        cursor.execute('SELECT scheduleID, plugID, shour, sminute, snewStatus, srepeat FROM schedule WHERE sactive = ?', (True,))
        active_schedules = cursor.fetchall()

        # Schedule each active job in APScheduler
        for schedule in active_schedules:
            schedule_id, plugID, shour, sminute, snewStatus, srepeat = schedule

            if srepeat:  # Create a recurring job based on specified days
                scheduler.add_job(
                    id=f'schedule_{schedule_id}',
                    func=execute_schedule_action,
                    trigger='cron',
                    hour=shour,
                    minute=sminute,
                    day_of_week=srepeat,
                    args=[plugID, snewStatus, schedule_id]
                )
            else:  # Create a one-time job for the next occurrence
                now = datetime.now()
                run_time = now.replace(hour=shour, minute=sminute, second=0, microsecond=0)
                if run_time <= now:
                    run_time += timedelta(days=1)
                scheduler.add_job(
                    id=f'schedule_{schedule_id}',
                    func=execute_schedule_action,
                    trigger='date',
                    run_date=run_time,
                    args=[plugID, snewStatus, schedule_id]
                )

        conn.close()
        print("Active schedules loaded successfully.")
    except Exception as e:
        print(f"Error loading active schedules: {e}")

# Function to deactivate all jobs in APScheduler when the server shuts down
def shutdown_server():
    try:
        # Remove all active jobs from APScheduler
        for job in scheduler.get_jobs():
            scheduler.remove_job(job.id)
        print("All active schedules have been deactivated.")
        log_server_end()
    except Exception as e:
        print(f"Error shutting down scheduler: {e}")

# Register the shutdown function with atexit to ensure it runs on server exit
atexit.register(shutdown_server)

# Insert a record into the log table indicating the server startup
def log_server_start():
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Inserir dados na tabela log
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', ('---', 'start', 'server_on'))
        conn.commit()
        conn.close()
        print("Server startup log inserted successfully.")
    except Exception as e:
        print(f"Failed to log server startup: {e}")

# Insert a record into the log table indicating the server ending
def log_server_end():
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Inserir dados na tabela log
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', ('---', 'end', 'server_off'))
        conn.commit()
        conn.close()
        print("Server ending log inserted successfully.")
    except Exception as e:
        print(f"Failed to log server ending: {e}")

# Run startup routines when the server starts.
def server_startup():
    if not check_database():
        print("Database does not exist, redirecting to setup.")
        app.config['STARTUP_REDIRECT'] = True
    else:
        print("Initializing system configurations...")
        initialize_timer_tactive()
        setup_gpio_pins()
        load_active_schedules()
        log_server_start()
        app.config['STARTUP_REDIRECT'] = False

@app.route('/toggle_device/<plugID>')
def toggle_device(plugID):
    try:
        # Connect to database
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()
        
        # Get device information
        cursor.execute('SELECT gpio, state FROM plug WHERE plugID = ?', (plugID,))
        device = cursor.fetchone()
        
        if not device:
            flash(f"Device {plugID} not found.", "error")
            return redirect(url_for('index'))
        
        gpio_pin, current_state = device
        
        # Toggle the state (True -> False or False -> True)
        new_state = not current_state
        
        # Update GPIO pin state
        if new_state:
            GPIO.output(gpio_pin, GPIO.HIGH)
        else:
            GPIO.output(gpio_pin, GPIO.LOW)
        
        # Update the state in the database
        cursor.execute('UPDATE plug SET state = ? WHERE plugID = ?', (new_state, plugID))
        conn.commit()
        
        # Insert a record into the log
        action = "plug_on" if new_state else "plug_off"
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', (plugID, 'manual', action))
        conn.commit()
        
        flash(f"Device {plugID} has been {'turned on' if new_state else 'turned off'}.", "success")
        
    except Exception as e:
        flash(f"An error occurred: {e}", "error")
    finally:
        conn.close()
    
    referrer = request.referrer
    if referrer and 'device' in referrer:
        return redirect(url_for('device', plugID=plugID))
    return redirect(url_for('index'))

@app.route('/')
def index():
    if app.config.get('STARTUP_REDIRECT', False):
        return redirect(url_for('setup'))
    # Connect to the database
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    
    # Fetch data from the 'plug' table
    cursor.execute('SELECT plugID, name, state FROM plug')
    plugs = cursor.fetchall()
    
    # Check if each device has an active schedule
    plug_schedules = {}
    for plug in plugs:
        plugID = plug[0]
        cursor.execute('SELECT sactive FROM schedule WHERE plugID = ? AND sactive = 1', (plugID,))
        plug_schedules[plugID] = cursor.fetchone() is not None

    conn.close()

    return render_template('index.html', plugs=plugs, plug_schedules=plug_schedules, show_log_button=True)

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

        try:
            # Initialize database and add records
            initialize_database(num_devices, gpio_values)
            setup_gpio_pins()
            log_server_start()
            # Set startup redirect to False or remove this check after the first initialization
            app.config['STARTUP_REDIRECT'] = False
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"An error occurred: {e}", "error")
            return render_template('setup.html', num_devices=num_devices, gpio_values=gpio_values)

    return render_template('setup.html', show_log_button=False)

# Function to get device information
def get_device_info(plugID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM plug WHERE plugID = ?', (plugID,))
    plug_info = cursor.fetchone()

    cursor.execute('SELECT * FROM timer WHERE plugID = ?', (plugID,))
    timer_info = cursor.fetchone()

    conn.close()
    return plug_info, timer_info

@app.route('/device/<plugID>')
def device(plugID):
    try:
        # Connect to database
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Get device and timer data
        cursor.execute('SELECT name, gpio, state FROM plug WHERE plugID = ?', (plugID,))
        plug = cursor.fetchone()

        cursor.execute('SELECT thour, tminute, tnewState, tactive FROM timer WHERE plugID = ?', (plugID,))
        timer_data = cursor.fetchone()

        if not plug or not timer_data:
            flash("Device or timer data not found.", "error")
            return redirect(url_for('index'))

        name, gpio, state = plug
        thour, tminute, tnewState, tactive = timer_data

        # Check if the timer is active in APScheduler
        job_id = f"timer_{plugID}" 
        job = scheduler.get_job(job_id)
        time_remaining = None
        if job:
            run_time = job.next_run_time
            time_remaining = run_time - datetime.now(run_time.tzinfo)

        conn.close()

        return render_template(
            'device.html',
            plugID=plugID,
            name=name,
            gpio=gpio,
            state=state,
            tnewState=tnewState,
            tactive=tactive,
            time_remaining=time_remaining, 
            show_log_button=True
        )

    except Exception as e:
        flash(f"An error occurred: {e}", "error")
        return redirect(url_for('index'))


@app.route('/update_name/<plugID>', methods=['POST'])
def update_name(plugID):
    new_name = request.form['newName']

    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE plug SET name = ? WHERE plugID = ?', (new_name, plugID))
    conn.commit()
    conn.close()

    return redirect(url_for('device', plugID=plugID))

@app.route('/timer/<plugID>', methods=['GET', 'POST'])
def timer(plugID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Fetch device and timer information
    cursor.execute('SELECT name FROM plug WHERE plugID = ?', (plugID,))
    device = cursor.fetchone()
    if not device:
        flash("Device not found.", "error")
        return redirect(url_for('index'))
    name = device[0]

    cursor.execute('SELECT thour, tminute, tnewState, tactive FROM timer WHERE plugID = ?', (plugID,))
    timer_info = cursor.fetchone()
    if not timer_info:
        flash("Timer information not found.", "error")
        return redirect(url_for('index'))

    thour, tminute, tnewState, tactive = timer_info

    if request.method == 'POST':
        # Read form data
        thour = int(request.form['hour'])
        tminute = int(request.form['minute'])
        tnewState = request.form['newStatus'] == 'on'
        tactive = request.form['tactive'] == 'on'

        # Update values ​​in timer table
        cursor.execute('''
            UPDATE timer SET thour = ?, tminute = ?, tnewState = ?, tactive = ? WHERE plugID = ?
        ''', (thour, tminute, tnewState, tactive, plugID))
        conn.commit()

        # Schedule/unschedule the timer
        job_id = f"timer_{plugID}"
        if tactive:
            # Add or update scheduling job
            run_time = datetime.now() + timedelta(hours=thour, minutes=tminute)
            scheduler.add_job(
                func=execute_timer_action,
                id=job_id,
                args=[plugID],
                trigger='date',
                run_date=run_time,
                replace_existing=True
            )
            flash("Timer scheduled successfully.", "success")
        else:
            # Remove scheduling job if disabled
            try:
                scheduler.remove_job(job_id)
            except JobLookupError:
                flash("Timer job not found, but timer is now inactive.", "info")

        conn.close()
        return redirect(url_for('device', plugID=plugID))

    conn.close()
    return render_template('timer.html', plugID=plugID, name=name, thour=thour, tminute=tminute, tnewState=tnewState, tactive=tactive, show_log_button=True)

def execute_timer_action(plugID):
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()
        
        # Get device and timer details
        cursor.execute('SELECT gpio, tnewState FROM timer JOIN plug ON timer.plugID = plug.plugID WHERE timer.plugID = ?', (plugID,))
        result = cursor.fetchone()
        
        if not result:
            print(f"Timer action: Device {plugID} not found.")
            return
        
        gpio_pin, tnewState = result
        
        # Trigger GPIO
        if tnewState:
            GPIO.output(gpio_pin, GPIO.HIGH)
            action = 'plug_on'
        else:
            GPIO.output(gpio_pin, GPIO.LOW)
            action = 'plug_off'
        
        # Update device status in database
        cursor.execute('UPDATE plug SET state = ? WHERE plugID = ?', (tnewState, plugID))
        conn.commit()
        
        # Insert record into log
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', (plugID, 'timer', action))
        conn.commit()

        # Disable timer after execution
        cursor.execute('UPDATE timer SET tactive = 0 WHERE plugID = ?', (plugID,))
        conn.commit()

        print(f"Timer action executed for device {plugID}: {'ON' if tnewState else 'OFF'}")

    except Exception as e:
        print(f"An error occurred during the timer action: {e}")
    finally:
        conn.close()

@app.route('/log')
def log():
    # Number of records per page
    per_page = 15
    # Get current page number from URL parameters
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * per_page

    # Connect to the database and fetch records with pagination
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM log')
    total_logs = cursor.fetchone()[0]

    cursor.execute('SELECT date, plugID, origin, action FROM log ORDER BY date DESC LIMIT ? OFFSET ?', (per_page, offset))
    logs = cursor.fetchall()
    conn.close()

    # Convert dates to system time zone
    local_tz = get_localzone()
    logs_converted = []
    for log in logs:
        date, plug_id, origin, action = log
        date_utc = datetime.strptime(date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.utc)
        date_local = date_utc.astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
        logs_converted.append((date_local, plug_id, origin, action))

    # Calculate the total number of pages
    total_pages = (total_logs // per_page) + (1 if total_logs % per_page > 0 else 0)

    return render_template('log.html', logs=logs_converted, page=page, total_pages=total_pages, show_log_button=False)

@app.route('/clear_log')
def clear_log():
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM log')
        conn.commit()
        conn.close()
        flash('System log cleared successfully.', 'success')
    except Exception as e:
        flash(f'Error clearing log: {e}', 'error')
    return redirect(url_for('index'))

@app.route('/add_schedule/<plugID>', methods=['GET', 'POST'])
def add_schedule(plugID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Get data from the device to render the form
    cursor.execute('SELECT name FROM plug WHERE plugID = ?', (plugID,))
    plug = cursor.fetchone()

    if not plug:
        flash("Device not found.", "error")
        return redirect(url_for('index'))

    name = plug[0]

    if request.method == 'POST':
        shour = int(request.form['shour'])
        sminute = int(request.form['sminute'])
        srepeat = request.form.getlist('srepeat')
        snewStatus = True if request.form['snewStatus'] == 'On' else False

        # Insert schedule into schedule table
        cursor.execute('INSERT INTO schedule (plugID, shour, sminute, snewStatus, sactive, srepeat) VALUES (?, ?, ?, ?, ?, ?)',
                       (plugID, shour, sminute, snewStatus, True, ','.join(srepeat)))
        conn.commit()

        # Add task to APScheduler
        schedule_id = cursor.lastrowid
        if srepeat:
            scheduler.add_job(
                id=f'schedule_{schedule_id}',
                func=execute_schedule_action,
                trigger='cron',
                hour=shour,
                minute=sminute,
                day_of_week=','.join(srepeat),
                args=[plugID, snewStatus, schedule_id]
            )
        else:
            now = datetime.now()
            run_time = now.replace(hour=shour, minute=sminute, second=0, microsecond=0)
            if run_time <= now:
                run_time += timedelta(days=1)
            scheduler.add_job(
                id=f'schedule_{schedule_id}',
                func=execute_schedule_action,
                trigger='date',
                run_date=run_time,
                args=[plugID, snewStatus, schedule_id]
            )

        flash("Schedule added successfully.", "success")
        return redirect(url_for('schedules', plugID=plugID))

    conn.close()
    return render_template('add_schedule.html', plugID=plugID, name=name, show_log_button=True)

def execute_schedule_action(plugID, snewStatus, schedule_id):
    try:
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Update device status
        cursor.execute('UPDATE plug SET state = ? WHERE plugID = ?', (snewStatus, plugID))
        conn.commit()

        # Trigger the device's GPIO
        cursor.execute('SELECT gpio FROM plug WHERE plugID = ?', (plugID,))
        gpio_pin = cursor.fetchone()
        
        if gpio_pin:
            gpio_pin = gpio_pin[0]          
            if snewStatus:
                GPIO.output(gpio_pin, GPIO.HIGH)  # Turn on the device
            else:
                GPIO.output(gpio_pin, GPIO.LOW)   # Turn off the device

        # Insert record into log
        action = 'plug_on' if snewStatus else 'plug_off'
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', (plugID, 'sched', action))
        conn.commit()

        # Check if schedule is recurring based on scheduleID
        cursor.execute('SELECT srepeat FROM schedule WHERE scheduleID = ?', (schedule_id,))
        repeat_days = cursor.fetchone()

        if not repeat_days or not repeat_days[0]:  # Check if srepeat is empty
            # Disables scheduling and removes it from APScheduler if it is not recurring
            cursor.execute('UPDATE schedule SET sactive = ? WHERE scheduleID = ?', (False, schedule_id))
            conn.commit()
            scheduler.remove_job(f'schedule_{schedule_id}')

        conn.close()

    except Exception as e:
        print(f"Error executing scheduled action for {plugID}: {e}")


@app.route('/schedules/<plugID>')
def schedules(plugID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Get Device Name
    cursor.execute('SELECT name FROM plug WHERE plugID = ?', (plugID,))
    plug = cursor.fetchone()
    if not plug:
        flash("Device not found.", "error")
        return redirect(url_for('index'))
    
    name = plug[0]

    # Get device schedules
    cursor.execute('SELECT scheduleID, shour, sminute, snewStatus, sactive, srepeat FROM schedule WHERE plugID = ? ORDER BY scheduleID DESC', (plugID,))
    schedules = cursor.fetchall()
    conn.close()

    # Convert the results to a list of dictionaries
    schedules_list = []
    for schedule in schedules:
        schedules_list.append({
            'scheduleID': schedule[0],
            'shour': schedule[1],
            'sminute': schedule[2],
            'snewStatus': schedule[3],
            'sactive': schedule[4],
            'srepeat': schedule[5]
        })

    return render_template('schedules.html', plugID=plugID, name=name, schedules=schedules_list, show_log_button=True)

@app.route('/toggle_schedule/<scheduleID>')
def toggle_schedule(scheduleID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Check the current status of 'sactive'
    cursor.execute('SELECT sactive, plugID, shour, sminute, snewStatus, srepeat FROM schedule WHERE scheduleID = ?', (scheduleID,))
    schedule = cursor.fetchone()
    if not schedule:
        flash("Schedule not found.", "error")
        return redirect(url_for('index'))
    
    sactive, plugID, shour, sminute, snewStatus, srepeat = schedule
    new_state = not sactive

    # Update the status of 'sactive' in the database
    cursor.execute('UPDATE schedule SET sactive = ? WHERE scheduleID = ?', (new_state, scheduleID))
    conn.commit()

    if new_state:
        # Enable scheduling
        if srepeat:
            scheduler.add_job(
                id=f'schedule_{scheduleID}',
                func=execute_schedule_action,
                trigger='cron',
                hour=shour,
                minute=sminute,
                day_of_week=srepeat,
                args=[plugID, snewStatus, scheduleID]
            )
        else:
            run_time = datetime.now().replace(hour=shour, minute=sminute, second=0, microsecond=0)
            if run_time <= datetime.now():
                run_time += timedelta(days=1)
            scheduler.add_job(
                id=f'schedule_{scheduleID}',
                func=execute_schedule_action,
                trigger='date',
                run_date=run_time,
                args=[plugID, snewStatus, scheduleID]
            )
    else:
        # Disable scheduling
        try:
            scheduler.remove_job(f'schedule_{scheduleID}')
        except JobLookupError:
            print(f"Job schedule_{scheduleID} not found.")

    conn.close()
    return redirect(url_for('schedules', plugID=plugID))

@app.route('/edit_schedule/<int:scheduleID>', methods=['GET', 'POST'])
def edit_schedule(scheduleID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Get the scheduling data
    cursor.execute('SELECT plugID, shour, sminute, snewStatus, srepeat FROM schedule WHERE scheduleID = ?', (scheduleID,))
    schedule = cursor.fetchone()

    if not schedule:
        flash("Schedule not found.", "error")
        return redirect(url_for('index'))

    plugID, shour, sminute, snewStatus, srepeat = schedule

    # Get Device Name
    cursor.execute('SELECT name FROM plug WHERE plugID = ?', (plugID,))
    plug = cursor.fetchone()
    name = plug[0] if plug else "Unknown"

    if request.method == 'POST':
        # Get form data
        new_shour = int(request.form['shour'])
        new_sminute = int(request.form['sminute'])
        new_srepeat = request.form.getlist('srepeat')
        new_snewStatus = True if request.form['snewStatus'] == 'On' else False

        # Update the schedule in the schedule table
        cursor.execute('''
            UPDATE schedule
            SET shour = ?, sminute = ?, snewStatus = ?, sactive = ?, srepeat = ?
            WHERE scheduleID = ?
        ''', (new_shour, new_sminute, new_snewStatus, True, ','.join(new_srepeat), scheduleID))
        conn.commit()

        # Update the schedule in APScheduler
        try:
            scheduler.remove_job(f'schedule_{scheduleID}')
        except JobLookupError:
            pass  # If it doesn't exist, ignore it

        if new_srepeat:
            scheduler.add_job(
                id=f'schedule_{scheduleID}',
                func=execute_schedule_action,
                trigger='cron',
                hour=new_shour,
                minute=new_sminute,
                day_of_week=','.join(new_srepeat),
                args=[plugID, new_snewStatus, scheduleID]
            )
        else:
            run_time = datetime.now().replace(hour=new_shour, minute=new_sminute, second=0, microsecond=0)
            if run_time <= datetime.now():
                run_time += timedelta(days=1)
            scheduler.add_job(
                id=f'schedule_{scheduleID}',
                func=execute_schedule_action,
                trigger='date',
                run_date=run_time,
                args=[plugID, new_snewStatus, scheduleID]
            )

        flash("Schedule updated successfully.", "success")
        return redirect(url_for('schedules', plugID=plugID))

    conn.close()
    return render_template('edit_schedule.html', scheduleID=scheduleID, plugID=plugID, name=name, shour=shour, sminute=sminute, snewStatus=snewStatus, srepeat=srepeat, show_log_button=True)

@app.route('/delete_schedule/<int:scheduleID>', methods=['POST'])
def delete_schedule(scheduleID):
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()

    # Get plugID to redirect correctly after deletion
    cursor.execute('SELECT plugID FROM schedule WHERE scheduleID = ?', (scheduleID,))
    schedule = cursor.fetchone()

    if schedule:
        plugID = schedule[0]
        # Remove from database
        cursor.execute('DELETE FROM schedule WHERE scheduleID = ?', (scheduleID,))
        conn.commit()

        # Remove from APScheduler
        try:
            scheduler.remove_job(f'schedule_{scheduleID}')
        except JobLookupError:
            pass  # If it doesn't exist, ignore it

        flash("Schedule deleted successfully.", "success")
        return redirect(url_for('schedules', plugID=plugID))
    else:
        flash("Schedule not found.", "error")
        return redirect(url_for('index'))

    conn.close()


if __name__ == '__main__':
    try:
        server_startup()
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        GPIO.cleanup()
