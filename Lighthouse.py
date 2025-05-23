import json, time, threading, requests
from flask import Flask, jsonify, request

class Lighthouse: 
	def __init__(self, config_path, pass_flask_app = False, interval = 5):
		self.config = self.load_config(config_path)
		self.pass_flask_app = pass_flask_app
		self.monitor_interval = interval
		self.status = "waiting"
		self.start_code_callback = None
		self.stop_code_callback = None
		self.start_conditions = []
		self.app = None
	
	def start_callback(self, func):
		self.start_code_callback = func
		return func
	
	def stop_callback(self, func):
		self.stop_code_callback = func
		return func

	def initialize(self):
		if self.config['role'] == 'master':
			self.notify_slaves("reset")
			self.start_main_code()
		elif not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
			self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
			self.monitor_thread.start()

	def load_config(self, path):
		with open(path, 'r') as f:
			return json.load(f)
	
	def register_routes(self):
		self.app.add_url_rule("/status", "status", self.get_status, methods=["GET"])
		self.app.add_url_rule("/reset", "reset", self.reset, methods=["POST"])
		self.app.add_url_rule("/stop", "stop", self.stop, methods=["POST"])

	def get_status(self):
		return jsonify({
			'status': self.status,
			'slaves': self.config['slaves']
		})

	def reset(self):
		self.stop_main_code()
		self.initialize()
		return '', 204

	def stop(self):
		self.stop_main_code()
		return '', 204

	def monitor(self):
		while True:
			try:
				parent_status = self.ping_status(self.config['parent_addr'])

				if parent_status == 'DOWN' and not self.status == "running":
					print("Parent down. Checking failover...")
					time.sleep(5*self.config["slaves"].index(self.config['self_addr']))
					if not self.any_main_running():
						self.promote_to_active()
				else:
					if self.config['slaves'] == []:
						self.config['slaves'] = self.get_slaves(self.config['parent_addr'])

			except Exception as e:
				print("Error in monitor:", e)

			time.sleep(self.monitor_interval)

	def ping_status(self, ip):
		try:
			res = requests.get(f"http://{ip}/status", timeout=2)
			data = res.json()
			if data['status'] == "running":
				return 'UP'
			else:
				return 'IDLE'
		except:
			return 'DOWN'

	def get_slaves(self, ip):
		try:
			res = requests.get(f"http://{ip}/status", timeout=2)
			data = res.json()
			return data['slaves']
		except:
			return []

	def any_main_running(self):
		for ip in self.config['slaves'] + [self.config['parent_addr']]:
			if ip == self.config['self_addr']:
				continue
			if self.ping_status(ip) == 'UP':
				return True
		return False

	def promote_to_active(self):
		self.start_main_code()
		self.notify_slaves('/reset')

	def notify_slaves(self, endpoint):
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f"http://{ip}/{endpoint.lstrip('/')}", timeout=2)
			except:
				print(f"Failed to notify {ip}")

	def start_main_code(self):
		print("Starting main code...")
		self.status = "running"
		if self.start_code_callback:
			if self.pass_flask_app:
				self.start_code_callback(self.app, self.config['self_addr'].split(":")[1])
			else:
				self.start_code_callback()

	def stop_main_code(self):
		print("Stopping main code...")
		self.status = "waiting"
		if self.stop_code_callback:
			self.stop_code_callback()

	def run(self):
		self.app = Flask(__name__)
		self.register_routes()
		threading.Thread(target=self.initialize, daemon=True).start()
		host, port = self.config['self_addr'].split(":")
		if not self.pass_flask_app:
			self.app.run(host="0.0.0.0", port=int(port))