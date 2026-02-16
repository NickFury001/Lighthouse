# Lighthouse

![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.7%2B-blue)

**Lighthouse** is a lightweight, Python-based failover management system designed to ensure high availability for long-running processes such as bots or services (e.g., Discord bots). It uses a master-slave architecture where one node is active and others are ready to take over automatically if the master fails.

## 🔧 Features

- Simple failover logic using HTTP and JSON configs
- Master-slave role management
- Automatic slave promotion if the master goes down
- RESTful API for monitoring and control
- Callback registration for custom start/stop logic
- Option to pass the Flask app and port to the start callback
- Configurable monitoring interval

## 📁 Structure

- `Lighthouse` class (main logic)
- `config.json` (node role and network info)
- `bot_main.py` (or any custom code to run as the main process)

## 🚀 Usage

### 0. Install Requirements

Before running Lighthouse, install the required Python packages:

```sh
pip install flask waitress requests
```

### 1. Prepare `config.json`

You can optionally add a `name` field to your config for easier identification in status responses. The `name` parameter is not required.

Example for a **master**:

```json
{
  "role": "master",
  "self_addr": "127.0.0.1:5000",
  "slaves": ["127.0.0.1:5001", "127.0.0.1:5002"],
  "name": "Main Node"
}
```

Example for a **slave**:

```json
{
  "role": "slave",
  "self_addr": "127.0.0.1:5001",
  "parent_addr": "127.0.0.1:5000",
  "slaves": [],
  "name": "Backup Node 1"
}
```

Example with **reverse proxy** (e.g., nginx):

If you use a reverse proxy that redirects external port 5000 to internal port 5001, set `host_port` to the actual port Flask should bind to:

```json
{
  "role": "master",
  "self_addr": "hostname:5000",
  "host_port": 5001,
  "slaves": ["slave1:5000", "slave2:5000"],
  "name": "Main Node"
}
```

- `self_addr`: The address other nodes use to reach this node (through the proxy)
- `host_port`: The actual port Flask binds to (optional, defaults to port from `self_addr`)

### 2. Create Your Main Bot or Process

For example, in `bot_main.py`:

```python
import time

while True:
    print("Bot running...")
    time.sleep(5)
```

> Replace `bot_main.py` with your actual script — it can be a Discord bot or any other long-running service.

### 3. Start Lighthouse

In your `main.py`:

```python
from Lighthouse.Lighthouse import Lighthouse
import subprocess
from flask import Flask

lh = Lighthouse("config.json")
proc = None

@lh.start_callback
def start():
    global proc
    proc = subprocess.Popen(["python3", "bot_main.py"])

@lh.stop_callback
def stop():
    global proc
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait()

@lh.update_callback
def update(data):
    print("Received update:", data)
    # Handle update logic here

# Optionally, you can pass a Flask app instance to lh.run(app=your_app)
# For example:
# app = Flask(__name__)
# lh.run(app=app)
lh.run()
```

### 4. Advanced: Pass Flask App and Port

If your bot or service needs access to the Flask app or dynamic port, use `pass_flask_app=True`:

```python
lh = Lighthouse("config.json", pass_flask_app=True)

@lh.start_callback
def start(app, port):
    print(f"Starting with Flask app on port {port}")
    # Your bot code here, using `app` if needed
```

---

## ⚙️ Configuration Options

### Constructor Parameters

| Parameter         | Description                                                        | Default      |
|------------------|--------------------------------------------------------------------|-------------|
| `config_path`    | Path to the JSON file that defines the node's role, address, peers | *(required)*|
| `pass_flask_app` | Pass `Flask` app and port to `start_callback()`                    | `False`     |
| `interval`       | Time (in seconds) between monitor checks                           | `5`         |

### Config JSON Fields

| Field          | Description                                                                 | Required |
|----------------|-----------------------------------------------------------------------------|----------|
| `role`         | Node role: `"master"` or `"slave"`                                          | Yes      |
| `self_addr`    | Address other nodes use to reach this node (e.g., `"hostname:5000"`)        | Yes      |
| `slaves`       | List of slave addresses                                                     | Yes      |
| `parent_addr`  | Parent node address (required for slaves)                                   | Slaves   |
| `name`         | Human-readable node name for status responses                               | No       |
| `host_port`    | Actual port Flask binds to (use when behind a reverse proxy)                | No       |

---

## 📡 API Endpoints

* `GET /status` – Returns current status and known slaves
* `POST /reset` – Stops main code and resets status
* `POST /stop` – Gracefully stops the main code
* `POST /update` – Calls the registered update callback with the JSON body of the request
* `GET /sync` – Returns the last update received by this node (used for state synchronization between nodes)

## 🛠️ Notes

* All API endpoints are registered on the Flask app.
* The class is designed for extensibility via callbacks.
* For advanced usage, see the DOCUMENTATION.md and code comments.
* Use different ports and IPs per node
* All nodes must be able to reach each other via HTTP
* Ensure the bot process is stateless or uses external storage for shared state
* Consider using a process manager like `systemd` or `supervisord` for production

## 🧾 License & Attribution

This project is licensed under the [Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

You are free to use, share, and adapt this project — even commercially — as long as you give **visible credit**.

Example attribution (for about pages, docs, or UI):

> Powered by Lighthouse – https://github.com/NickFury001/Lighthouse (CC BY 4.0)

See the [`NOTICE`](./NOTICE) and [`LICENSE`](./LICENSE) files for details.
