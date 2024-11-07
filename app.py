from flask import Flask, render_template, redirect, url_for, request, flash
import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
import os
import RPi.GPIO as GPIO

app = Flask(__name__)
app.secret_key = 'your_secret_key'
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
            srepeat TEXT CHECK (length(srepeat) <= 23),
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

@app.route('/toggle_device/<plugID>')
def toggle_device(plugID):
    try:
        # Conecte ao banco de dados
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()
        
        # Obtenha as informações do dispositivo
        cursor.execute('SELECT gpio, state FROM plug WHERE plugID = ?', (plugID,))
        device = cursor.fetchone()
        
        if not device:
            flash(f"Device {plugID} not found.", "error")
            return redirect(url_for('index'))
        
        gpio_pin, current_state = device
        
        # Toggle the state (True -> False or False -> True)
        new_state = not current_state
        
        # Atualize o estado do pino GPIO
        if new_state:
            GPIO.output(gpio_pin, GPIO.HIGH)
        else:
            GPIO.output(gpio_pin, GPIO.LOW)
        
        # Atualize o estado no banco de dados
        cursor.execute('UPDATE plug SET state = ? WHERE plugID = ?', (new_state, plugID))
        conn.commit()
        
        # Insira um registro no log
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
            # Set startup redirect to False or remove this check after the first initialization
            app.config['STARTUP_REDIRECT'] = False
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"An error occurred: {e}", "error")
            return render_template('setup.html', num_devices=num_devices, gpio_values=gpio_values)

    return render_template('setup.html', show_log_button=False)

# Função para obter informações do dispositivo
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
        # Conectar ao banco de dados
        conn = sqlite3.connect('piplug.db')
        cursor = conn.cursor()

        # Obter os dados do dispositivo e do timer
        cursor.execute('SELECT name, gpio, state FROM plug WHERE plugID = ?', (plugID,))
        plug = cursor.fetchone()

        cursor.execute('SELECT thour, tminute, tnewState, tactive FROM timer WHERE plugID = ?', (plugID,))
        timer_data = cursor.fetchone()

        if not plug or not timer_data:
            flash("Device or timer data not found.", "error")
            return redirect(url_for('index'))

        name, gpio, state = plug
        thour, tminute, tnewState, tactive = timer_data

        # Verificar se o timer está ativo no APScheduler
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

    # Buscar informações do dispositivo e timer
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
        # Ler dados do formulário
        thour = int(request.form['hour'])
        tminute = int(request.form['minute'])
        tnewState = request.form['newStatus'] == 'on'
        tactive = request.form['tactive'] == 'on'

        # Atualizar os valores na tabela timer
        cursor.execute('''
            UPDATE timer SET thour = ?, tminute = ?, tnewState = ?, tactive = ? WHERE plugID = ?
        ''', (thour, tminute, tnewState, tactive, plugID))
        conn.commit()

        # Agendar/desagendar o timer
        job_id = f"timer_{plugID}"
        if tactive:
            # Adicionar ou atualizar o job de agendamento
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
            # Remover o job de agendamento se desativado
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
        
        # Obter os detalhes do dispositivo e do timer
        cursor.execute('SELECT gpio, tnewState FROM timer JOIN plug ON timer.plugID = plug.plugID WHERE timer.plugID = ?', (plugID,))
        result = cursor.fetchone()
        
        if not result:
            print(f"Timer action: Device {plugID} not found.")
            return
        
        gpio_pin, tnewState = result
        
        # Acionar o GPIO
        if tnewState:
            GPIO.output(gpio_pin, GPIO.HIGH)
            action = 'plug_on'
        else:
            GPIO.output(gpio_pin, GPIO.LOW)
            action = 'plug_off'
        
        # Atualizar o estado do dispositivo no banco de dados
        cursor.execute('UPDATE plug SET state = ? WHERE plugID = ?', (tnewState, plugID))
        conn.commit()
        
        # Inserir registro no log
        cursor.execute('INSERT INTO log (plugID, origin, action) VALUES (?, ?, ?)', (plugID, 'timer', action))
        conn.commit()

        # Desativar o timer após a execução
        cursor.execute('UPDATE timer SET tactive = 0 WHERE plugID = ?', (plugID,))
        conn.commit()

        print(f"Timer action executed for device {plugID}: {'ON' if tnewState else 'OFF'}")

    except Exception as e:
        print(f"An error occurred during the timer action: {e}")
    finally:
        conn.close()

@app.route('/log')
def log():
    # Número de registros por página
    per_page = 15
    # Obter o número da página atual a partir dos parâmetros da URL
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * per_page

    # Conectar ao banco de dados e buscar os registros com paginação
    conn = sqlite3.connect('piplug.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM log')
    total_logs = cursor.fetchone()[0]

    cursor.execute('SELECT date, plugID, origin, action FROM log ORDER BY date DESC LIMIT ? OFFSET ?', (per_page, offset))
    logs = cursor.fetchall()
    conn.close()

    # Calcular o número total de páginas
    total_pages = (total_logs // per_page) + (1 if total_logs % per_page > 0 else 0)

    return render_template('log.html', logs=logs, page=page, total_pages=total_pages, show_log_button=False)

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

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        GPIO.cleanup()  # Ensure GPIO cleanup if the server crashes
