import json import time import threading import requests from flask import Flask, jsonify, request

app = Flask(name)

class Lighthouse: def init(self, config_path): self.config = self.load_config(config_path) self.status = "waiting" self.is_main_code_running = False

if self.config['role'] == 'master':
		self.start_main_code()
		self.status = "running"

	self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
	self.monitor_thread.start()

def load_config(self, path):
	with open(path, 'r') as f:
		return json.load(f)

def get_status(self):
	return jsonify({
		'status': self.status,
		'is_main_code_running': self.is_main_code_running
	})

def reset(self):
	self.stop_main_code()
	self.status = "waiting"
	return '', 204

def stop(self):
	self.stop_main_code()
	self.status = "waiting"
	return '', 204

def monitor(self):
	while True:
		try:
			parent_status = self.ping_status(self.config['parent_ip'])

			if parent_status == 'DOWN':
				print("Parent down. Checking failover...")
				if not self.any_main_running():
					self.promote_to_active()
			else:
				print("Parent is up.")

		except Exception as e:
			print("Error in monitor:", e)

		time.sleep(5)

def ping_status(self, ip):
	try:
		res = requests.get(f"http://{ip}/status", timeout=2)
		data = res.json()
		if data['is_main_code_running']:
			return 'UP'
		else:
			return 'IDLE'
	except:
		return 'DOWN'

def any_main_running(self):
	for ip in self.config['all_slaves'] + [self.config['parent_ip']]:
		if ip == self.config['self_ip']:
			continue
		if self.ping_status(ip) == 'UP':
			return True
	return False

def promote_to_active(self):
	self.start_main_code()
	self.status = "running"
	self.notify_slaves('/reset')

def notify_slaves(self, endpoint):
	for ip in self.config['all_slaves']:
		if ip == self.config['self_ip']:
			continue
		try:
			requests.post(f"http://{ip}{endpoint}", timeout=2)
		except:
			print(f"Failed to notify {ip}")

def start_main_code(self):
	print("Starting main code...")
	self.is_main_code_running = True
	# subprocess.Popen(["python3", "bot_main.py"])  # Example

def stop_main_code(self):
	print("Stopping main code...")
	self.is_main_code_running = False
	# Terminate the subprocess or similar

lighthouse = Lighthouse("config.json")

@app.route('/status', methods=['GET']) def status(): return lighthouse.get_status()

@app.route('/reset', methods=['POST']) def reset(): return lighthouse.reset()

@app.route('/stop', methods=['POST']) def stop(): return lighthouse.stop()

if name == 'main': app.run(host='0.0.0.0', port=80)

