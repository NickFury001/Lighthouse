import json, time, threading, requests
from flask import Flask, jsonify, request
from waitress import serve
from threading import Event

class Lighthouse: 
	def __init__(self, config_path, pass_flask_app = False, interval = 30):
		self.config = self.load_config(config_path)
		self.pass_flask_app = pass_flask_app
		self.stop = False
		self.monitor_interval = interval
		self.wait_step = 5
		self.req_caching_time = interval
		self.status = 'waiting'
		self.custom_status = False
		self.start_code_callback = None
		self.stop_code_callback = None
		self.start_conditions = []
		self.timeout = 0
		self.request_cache = {}
	def send_get(self, path, *args, **kwargs):
		if path in self.request_cache:
			if self.request_cache[path]['t'] > time.time():
				print("saved request")
				return self.request_cache[path]['response']
		res = requests.get(path, *args, **kwargs)
		self.request_cache[path] = {
			't': time.time() + self.req_caching_time,
			'response': res
		}
	def start_callback(self, func):
		self.start_code_callback = func
		return func
	
	def stop_callback(self, func):
		self.stop_code_callback = func
		return func

	def initialize(self):
		if self.config['role'] == 'master' and self.timeout == 0:
			self.notify_slaves("reset")
			self.start_main_code()
		elif not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
			self.stop_event = threading.Event()
			self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
			self.monitor_thread.start()

	def load_config(self, path):
		with open(path, 'r') as f:
			return json.load(f)
	
	def register_routes(self):
		self.app.add_url_rule("/status", "status", self.get_status, methods=["GET"])
		self.app.add_url_rule("/reset", "reset", self.reset, methods=["POST"])
		self.app.add_url_rule("/stop", "stop", self.stop, methods=["POST"])

	def set_temp_status(self, status_msg = "stopped temporarily", timeout = 60):
		self.custom_status = True
		self.status = status_msg
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

	def monitor(self):
		while not self.stop:
			try:
				if self.timeout != 0 and time.time()+self.timeout < time.time():
					self.stop = True
					self.custom_status = False
					self.monitor_thread.join()
					del self.monitor_thread
					self.timeout = 0
					self.initialize()
				elif self.config['role'] == "slave":
					parent_status = self.ping_raw_status(self.config['parent_addr'])
					if self.config['slaves'] == []:
						self.config['slaves'] = self.get_slaves(self.config['parent_addr'])
					if parent_status not in ['running', "waiting"] and not self.status == 'running':
						print('Parent down. Checking failover...')
						time.sleep(self.wait_step*self.config['slaves'].index(self.config['self_addr']))
						if not self.any_main_running():
							self.promote_to_active()
			except Exception as e:
				print('Error in monitor:', e)
			

			time.sleep(self.monitor_interval)
		self.stop = False

	def ping_status(self, ip):
		try:
			res = self.send_get(f'http://{ip}/status', timeout=2)
			data = res.json()
			if data['status'] == 'running':
				return 'UP'
			else:
				return 'IDLE'
		except:
			return 'DOWN'

	def ping_raw_status(self, ip):
		try:
			res = self.send_get(f'http://{ip}/status', timeout=2)
			data = res.json()
			return data['status']
		except:
			return None

	def get_slaves(self, ip):
		try:
			res = self.send_get(f'http://{ip}/status', timeout=2)
			data = res.json()
			ip_list = data['slaves'] if self.config['parent_addr'] in data['slaves'] else [self.config['parent_addr']] + data['slaves']
			return ip_list
		except:
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
		self.notify_slaves('/reset')

	def notify_slaves(self, endpoint):
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f'http://{ip}/{endpoint.lstrip('/')}', timeout=2)
			except:
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
					response = self.send_get(f'http://{ip}/status', timeout=2)
					data = response.json()
					res.append({
						'name': data['name'] if 'name' in data else 'Server',
						'ip': ip,
						'status': data['status']
					})
				except:
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