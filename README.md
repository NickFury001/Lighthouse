# Lighthouse

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

### 1. Prepare `config.json`

Example for a **master**:

```json
{
  "role": "master",
  "self_addr": "127.0.0.1:5000",
  "slaves": ["127.0.0.1:5001", "127.0.0.1:5002"]
}
````

Example for a **slave**:

```json
{
  "role": "slave",
  "self_addr": "127.0.0.1:5001",
  "parent_addr": "127.0.0.1:5000",
  "slaves": []
}
```

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

| Parameter        | Description                                     | Default |
| ---------------- | ----------------------------------------------- | ------- |
| `pass_flask_app` | Pass `Flask` app and port to `start_callback()` | `False` |
| `interval`       | Time (in seconds) between monitor checks        | `5`     |

---

## 📡 API Endpoints

* `GET /status` – Returns current status and known slaves
* `POST /reset` – Stops main code and resets status
* `POST /stop` – Gracefully stops the main code

## 🛠️ Notes

* Use different ports and IPs per node
* All nodes must be able to reach each other via HTTP
* Ensure the bot process is stateless or uses external storage for shared state
* Consider using a process manager like `systemd` or `supervisord` for production

## ✅ License

This project is licensed under the [MIT License](./LICENSE), with an additional attribution requirement.

If you use Lighthouse in a publicly accessible product — such as a bot, web app, or hosted service — you **must display the phrase**:

> **"Powered by Lighthouse"**

...along with a **clickable link** to the original repository:
**[https://github.com/NickFury001/Lighthouse](https://github.com/NickFury001/Lighthouse)**

See the [LICENSE](./LICENSE) file for full details.
