# Lighthouse Class Documentation

This document provides detailed reference for the `Lighthouse` class and its methods, as implemented in `Lighthouse.py`.

---

## Class: `Lighthouse`

### Constructor
```python
Lighthouse(config_path, pass_flask_app=False, interval=5)
```
- **config_path**: Path to the JSON config file.
- **pass_flask_app**: If True, passes the Flask app and port to the start callback.
- **interval**: Monitor interval in seconds.

### Config JSON Fields

| Field          | Description                                                                 | Required |
|----------------|-----------------------------------------------------------------------------|----------|
| `role`         | Node role: `"master"` or `"slave"`                                          | Yes      |
| `self_addr`    | Address other nodes use to reach this node (e.g., `"hostname:5000"`)        | Yes      |
| `slaves`       | List of slave addresses                                                     | Yes      |
| `parent_addr`  | Parent node address (required for slaves)                                   | Slaves   |
| `name`         | Human-readable node name for status responses                               | No       |
| `host_port`    | Actual port Flask binds to (use when behind a reverse proxy)                | No       |

#### Reverse Proxy Support (`host_port`)

When running behind a reverse proxy (e.g., nginx) that redirects traffic from one port to another, use `host_port` to specify the actual port Flask should bind to:

```json
{
  "role": "master",
  "self_addr": "hostname:5000",
  "host_port": 5001,
  "slaves": ["slave1:5000"]
}
```

- `self_addr` port (5000): The port other nodes use to communicate (through proxy)
- `host_port` (5001): The port Flask actually binds to

If `host_port` is not set, Flask binds to the port from `self_addr`.

---

## Methods

### Callback Registration
- `start_callback(func)`: Register a function to be called when starting the main code.
- `stop_callback(func)`: Register a function to be called when stopping the main code.
- `update_callback(func)`: Register a function to be called when an update is received.

### Initialization & Main Control
- `initialize()`: Initializes the node, starts monitor thread or main code as appropriate.
- `start_main_code()`: Calls the registered start callback and sets status to 'running'.
- `stop_main_code(action)`: Calls the registered stop callback and sets status to 'waiting' (unless custom status is set).

### Configuration & State
- `load_config(path)`: Loads the configuration from the given JSON file.
- `set_temp_status(status_msg="stopped temporarily", timeout=60)`: Sets a temporary status and timeout.

### Flask API Endpoints (registered via `register_routes()`)
- `get_status()`: Returns current status and known slaves (GET `/status`).
- `reset()`: Stops main code and resets status (POST `/reset`).
- `stop()`: Gracefully stops the main code (POST `/stop`).
- `update()`: Calls the update callback with the JSON body (POST `/update`).
- `sync()`: Returns the last update received (GET `/sync`).

### Internal/Utility Methods
- `register_routes()`: Registers all Flask API endpoints.
- `sync_from_slaves()`: Syncs state from slaves (used by master at startup).
- `send_update(data)`: Sends an update to all slaves.
- `notify_slaves(endpoint)`: Notifies all slaves at a given endpoint.
- `monitor()`: Monitor thread for failover and status checks.
- `ping_status(ip)`: Returns 'UP', 'IDLE', or 'DOWN' for a given node.
- `ping_raw_status(ip)`: Returns the raw status string for a given node.
- `get_slaves(ip)`: Gets the list of slaves from a given node.
- `any_main_running()`: Checks if any main node is running.
- `promote_to_active()`: Promotes this node to active (master) and notifies slaves.
- `get_all_statuses()`: Returns a list of statuses for all known nodes.

### Running the Server
- `run(app=None)`: Starts the Flask server (optionally with a provided app). If `pass_flask_app` is True, waits after initialization.

---

## Example Usage

```python
from Lighthouse.Lighthouse import Lighthouse
import subprocess

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

lh.run()
```

---
