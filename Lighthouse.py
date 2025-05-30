import json, time, threading, requests
from flask import Flask, jsonify, request
from waitress import serve
from threading import Event

class Lighthouse: 
	def __init__(self, config_path, pass_flask_app = False, interval = 5):
		self.config = self.load_config(config_path)
		self.pass_flask_app = pass_flask_app
		self.stop_monitor_thread = False
		self.monitor_interval = interval
		self.status = 'waiting'
		self.custom_status = False
		self.start_code_callback = None
		self.stop_code_callback = None
		self.update_code_callback = None
		self.start_conditions = []
		self.timeout_start = 0
		self.timeout = 0
		self.last_update = None
	
	def start_callback(self, func):
		self.start_code_callback = func
		return func
	
	def stop_callback(self, func):
		self.stop_code_callback = func
		return func
	
	def update_callback(self, func):
		self.update_code_callback = func
		return func

	def initialize(self):
		if self.config['role'] == 'master' and self.timeout == 0:
			self.sync_from_slaves()
			self.notify_slaves("reset")
			self.start_main_code()
		elif not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
			self.stop_event = threading.Event()
			self.stop_monitor_thread = False
			self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
			self.monitor_thread.start()
	
	def sync_from_slaves(self):
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				resp = requests.get(f'http://{ip}/sync', timeout=2)
				data = resp.json()
				if data.get('last_update'):
					# Optionally, apply this update to master
					if self.update_code_callback:
						self.update_code_callback(data['last_update'])
					break  # Use the first available state
			except Exception as e:
				print(f"Failed to sync from slave {ip}: {e}")

	def load_config(self, path):
		with open(path, 'r') as f:
			return json.load(f)
	
	def register_routes(self):
		self.app.add_url_rule("/status", "status", self.get_status, methods=["GET"])
		self.app.add_url_rule("/reset", "reset", self.reset, methods=["POST"])
		self.app.add_url_rule("/stop", "stop", self.stop, methods=["POST"])
		self.app.add_url_rule("/update", "update", self.update, methods=["POST"])
		self.app.add_url_rule("/sync", "sync", self.sync, methods=["GET"])

	def set_temp_status(self, status_msg = "stopped temporarily", timeout = 60):
		self.custom_status = True
		self.status = status_msg
		self.timeout_start = time.time()
		self.timeout = timeout
		self.stop_main_code("stop")

	def get_status(self):
		return jsonify({
			'name': self.config['name'] if 'name' in self.config else 'Server',
			'status': self.status,
			'slaves': self.config['slaves']
		})

	def reset(self):
		self.stop_main_code("reset")
		self.initialize()
		return '', 204

	def stop(self):
		self.stop_main_code("stop")
		return '', 204

	def sync(self):
		return jsonify({'last_update': self.last_update}), 200

	def update(self):
		data = request.get_json()
		self.last_update = data
		if hasattr(self, 'update_code_callback') and self.update_code_callback:
			if self.update_code_callback.__code__.co_argcount > 0:
				self.update_code_callback(data)
			else:
				self.update_code_callback()
		return '', 204

	def send_update(self, data):
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f'http://{ip}/update', json=data, timeout=2)
			except Exception as e:
				print(f'Failed to send update to {ip}: {e}')
	
	def monitor(self):
		while not self.stop_monitor_thread:
			try:
				if self.timeout != 0 and self.timeout_start+self.timeout < time.time():
					self.stop_monitor_thread = True
					self.custom_status = False
					self.monitor_thread.join()
					self.monitor_thread = None
					self.timeout = 0
					self.initialize()
				elif self.config['role'] == "slave":
					parent_status = self.ping_raw_status(self.config['parent_addr'])
					if self.config['slaves'] == []:
						self.config['slaves'] = self.get_slaves(self.config['parent_addr'])
					if parent_status not in ['running', "waiting"] and not self.status == 'running':
						print('Parent down. Checking failover...')
						time.sleep(5*self.config['slaves'].index(self.config['self_addr']))
						if not self.any_main_running():
							self.promote_to_active()
			except Exception as e:
				print('Error in monitor:', e)
			

			time.sleep(self.monitor_interval)

	def ping_status(self, ip):
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			if data['status'] == 'running':
				return 'UP'
			else:
				return 'IDLE'
		except Exception:
			return 'DOWN'

	def ping_raw_status(self, ip):
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			return data['status']
		except Exception:
			return None

	def get_slaves(self, ip):
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			ip_list = data['slaves'] if self.config['parent_addr'] in data['slaves'] else [self.config['parent_addr']] + data['slaves']
			return ip_list
		except Exception:
			return []

	def any_main_running(self):
		ip_list = self.config['slaves'] if self.config['role'] == 'master' or ('parent_addr' in self.config and self.config['parent_addr'] in self.config['slaves']) else [self.config['parent_addr']] + self.config['slaves']
		for ip in ip_list:
			if ip == self.config['self_addr']:
				continue
			if self.ping_status(ip) == 'UP':
				return True
		return False

	def promote_to_active(self):
		self.start_main_code()
		self.notify_slaves('reset')

	def notify_slaves(self, endpoint):
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f'http://{ip}/{endpoint.lstrip("/")}', timeout=2)
			except Exception:
				print(f'Failed to notify {ip}')

	def start_main_code(self):
		print('Starting main code...')
		self.status = 'running'
		if self.start_code_callback:
			if self.pass_flask_app:
				self.start_code_callback(self.app, self.config['self_addr'].split(':')[1])
			else:
				self.start_code_callback()

	def get_all_statuses(self):
		res = []
		if self.config["self_addr"] not in self.config["slaves"]:
			res.append({
				'name': self.config['name'] if 'name' in self.config else 'Server',
				'ip': self.config['self_addr'],
				'status': self.status
			})
		if self.config['role'] != 'master':
			ip_list = self.config['slaves'] if self.config['parent_addr'] in self.config['slaves'] else [self.config['parent_addr']] + self.config['slaves']
		else:
			ip_list = self.config['slaves']
		for ip in ip_list:
			if ip == self.config['self_addr']:
				res.append({
					'name': self.config['name'] if 'name' in self.config else 'Server',
					'ip': self.config['self_addr'],
					'status': self.status
				})
			else:
				try:
					response = requests.get(f'http://{ip}/status', timeout=2)
					data = response.json()
					res.append({
						'name': data['name'] if 'name' in data else 'Server',
						'ip': ip,
						'status': data['status']
					})
				except Exception:
					res.append({
						'name': 'Server',
						'status': 'crashed'
					})
		return res

	def stop_main_code(self, action):
		print('Stopping main code...')
		self.status = 'waiting' if not self.custom_status else self.status
		if self.stop_code_callback:
			if self.stop_code_callback.__code__.co_argcount > 0:
				self.stop_code_callback(action)
			else:
				self.stop_code_callback()

	def run(self, app=None):
		self.app = app
		if self.app is None:
			self.app = Flask(__name__)
		self.register_routes()
		if not self.pass_flask_app:
			threading.Thread(target=self.initialize, daemon=True).start()
			host, port = self.config['self_addr'].split(':')
			serve(self.app, host='0.0.0.0', port=int(port))
		else:
			self.initialize()
			Event().wait()