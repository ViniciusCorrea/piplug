# <img src="static/images/logo.png" alt="PiPlug Logo" width="50"> PiPlug

PiPlug is a web-based platform designed to manage and schedule GPIO-controlled devices. It allows users to toggle devices, set up schedules, and monitor system logs through a user-friendly interface.

## Features

- **Device Management**: Turn devices on or off and view their current status.
- **Scheduling**: Create, edit, activate, or deactivate schedules for devices to automate their operations.
- **Logs**: Maintain a system log of all device activities, including manual, scheduled, and timer-based actions.
- **GPIO Control**: Use the Raspberry Pi's GPIO pins to control connected devices.
- **Responsive Interface**: A clean and intuitive web interface built with Bootstrap for easy navigation.

## Prerequisites

- Python 3.7 or higher
- Raspberry Pi with GPIO pins

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/ViniciusCorrea/piplug.git
   cd piplug

2. **Install dependencies**: Ensure you have pip installed and run:
   ```bash
   pip install -r requirements.txt
   
3. **Run the application**:
   ```bash
   python app.py

4. **Access the web interface**: Open your web browser and navigate to:
   ```bash
   http://<your-pi-ip>:5000/

## Usage

- **Devices**: Control connected devices and view their status.
- **Add Schedule**: Schedule devices to turn on or off at specific times and days.
- **Edit Schedule**: Modify or delete existing schedules.
- **System Logs**: View the history of all device actions and clear logs when needed.


## Technologies Used

- **Flask**: Web framework for creating the server-side logic.
- **APScheduler**: Scheduling library to handle periodic and one-time task scheduling.
- **SQLite**: Database for persisting schedules, logs, and device states.
- **RPi.GPIO**: Library for interfacing with the Raspberry Pi's GPIO pins.
- **Bootstrap**: Front-end framework for responsive UI design.

## License

This project is licensed under the GPLv3 License. See the LICENSE file for details.
