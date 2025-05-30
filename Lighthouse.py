import json, time, threading, requests
from flask import Flask, jsonify, request
from waitress import serve
from threading import Event
import logging

class Lighthouse: 
	def __init__(self, config_path, pass_flask_app = False, interval = 5):
		self.logger = logging.getLogger("Lighthouse")  # Moved up before load_config
		logging.basicConfig(
			level=logging.INFO,
			format="%(asctime)s [%(levelname)s] %(message)s",
		)
		self.config = self.load_config(config_path)
		self.pass_flask_app = pass_flask_app
		self.stop_monitor_thread = threading.Event()  # Use Event for thread safety
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
		self.logger.info("Initializing Lighthouse node with role '%s'", self.config.get('role'))
		if self.config['role'] == 'master' and self.timeout == 0:
			self.sync_from_slaves()
			self.notify_slaves("reset")
			self.start_main_code()
		elif not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
			self.stop_event = threading.Event()
			self.stop_monitor_thread.clear()  # Reset event
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
					self.logger.info("Synced state from slave %s", ip)
					# Optionally, apply this update to master
					if self.update_code_callback:
						self.update_code_callback(data['last_update'])
					break  # Use the first available state
			except Exception as e:
				self.logger.error(f"Failed to sync from slave {ip}: {e}")

	def load_config(self, path):
		self.logger.info("Loading config from %s", path)
		with open(path, 'r') as f:
			return json.load(f)
	
	def register_routes(self):
		self.logger.info("Registering Flask routes")
		self.app.add_url_rule("/status", "status", self.get_status, methods=["GET"])
		self.app.add_url_rule("/reset", "reset", self.reset, methods=["POST"])
		self.app.add_url_rule("/stop", "stop", self.stop, methods=["POST"])
		self.app.add_url_rule("/update", "update", self.update, methods=["POST"])
		self.app.add_url_rule("/sync", "sync", self.sync, methods=["GET"])

	def set_temp_status(self, status_msg = "stopped temporarily", timeout = 60):
		self.logger.warning("Setting temporary status: '%s' for %ds", status_msg, timeout)
		self.custom_status = True
		self.status = status_msg
		self.timeout_start = time.time()
		self.timeout = timeout
		self.stop_main_code("stop")

	def get_status(self):
		self.logger.debug("Status requested")
		return jsonify({
			'name': self.config['name'] if 'name' in self.config else 'Server',
			'status': self.status,
			'slaves': self.config['slaves']
		})

	def reset(self):
		self.logger.info("Reset endpoint called")
		self.stop_main_code("reset")
		self.initialize()
		return '', 204

	def stop(self):
		self.logger.info("Stop endpoint called")
		self.stop_main_code("stop")
		return '', 204

	def sync(self):
		self.logger.debug("Sync endpoint called")
		return jsonify({'last_update': self.last_update}), 200

	def update(self):
		self.logger.info("Update endpoint called")
		data = request.get_json()
		self.last_update = data
		if hasattr(self, 'update_code_callback') and self.update_code_callback:
			if self.update_code_callback.__code__.co_argcount > 0:
				self.update_code_callback(data)
			else:
				self.update_code_callback()
		return '', 204

	def send_update(self, data):
		self.logger.info("Sending update to all slaves")
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f'http://{ip}/update', json=data, timeout=2)
				self.logger.info("Sent update to %s", ip)
			except Exception as e:
				self.logger.error(f'Failed to send update to {ip}: {e}')
	
	def monitor(self):
		self.logger.info("Monitor thread started")
		while not self.stop_monitor_thread.is_set():
			try:
				if self.timeout != 0 and self.timeout_start+self.timeout < time.time():
					self.logger.info("Timeout reached, reinitializing")
					self.stop_monitor_thread.set()
					self.custom_status = False
					self.timeout = 0
					self.initialize()
					break
				elif self.config['role'] == "slave":
					parent_status = self.ping_raw_status(self.config['parent_addr'])
					if not self.config['slaves']:
						slaves = self.get_slaves(self.config['parent_addr'])
						if slaves:
							self.config['slaves'] = slaves
					if parent_status not in ['running', "waiting"] and not self.status == 'running':
						self.logger.warning('Parent down. Checking failover...')
						try:
							sleep_time = 5 * self.config['slaves'].index(self.config['self_addr'])
						except ValueError:
							sleep_time = 5
						time.sleep(sleep_time)
						if not self.any_main_running():
							self.logger.info("Promoting to active")
							self.promote_to_active()
			except Exception as e:
				self.logger.error('Error in monitor: %s', e)
			
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
			self.logger.warning("Failed to ping status of %s", ip)
			return 'DOWN'

	def ping_raw_status(self, ip):
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			return data['status']
		except Exception:
			self.logger.warning("Failed to ping raw status of %s", ip)
			return None

	def get_slaves(self, ip):
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			ip_list = data['slaves'] if self.config['parent_addr'] in data['slaves'] else [self.config['parent_addr']] + data['slaves']
			return ip_list
		except Exception:
			self.logger.warning("Failed to get slaves from %s", ip)
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
		self.logger.info("Promoting node to active")
		self.start_main_code()
		self.notify_slaves('reset')

	def notify_slaves(self, endpoint):
		self.logger.info("Notifying slaves at endpoint /%s", endpoint.lstrip("/"))
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				requests.post(f'http://{ip}/{endpoint.lstrip("/")}', timeout=2)
				self.logger.info("Notified %s", ip)
			except Exception:
				self.logger.error(f'Failed to notify {ip}')

	def start_main_code(self):
		self.logger.info('Starting main code...')
		self.status = 'running'
		if self.start_code_callback:
			if self.pass_flask_app:
				if not hasattr(self, 'app') or self.app is None:
					self.app = Flask(__name__)
				self.start_code_callback(self.app, self.config['self_addr'].split(':')[1])
			else:
				self.start_code_callback()

	def get_all_statuses(self):
		self.logger.info("Getting all statuses")
		res = []
		seen_ips = set()
		def add_status(ip, name, status):
			if ip not in seen_ips:
				res.append({'name': name, 'ip': ip, 'status': status})
				seen_ips.add(ip)
		add_status(self.config['self_addr'], self.config.get('name', 'Server'), self.status)
		ip_list = self.config['slaves']
		if self.config['role'] != 'master' and 'parent_addr' in self.config and self.config['parent_addr'] not in ip_list:
			ip_list = [self.config['parent_addr']] + ip_list
		for ip in ip_list:
			if ip == self.config['self_addr']:
				continue
			try:
				response = requests.get(f'http://{ip}/status', timeout=2)
				data = response.json()
				add_status(ip, data.get('name', 'Server'), data['status'])
			except Exception:
				self.logger.warning("Failed to get status from %s", ip)
				add_status(ip, 'Server', 'crashed')
		return res

	def stop_main_code(self, action):
		self.logger.info('Stopping main code...')
		self.status = 'waiting' if not self.custom_status else self.status
		if self.stop_code_callback:
			if self.stop_code_callback.__code__.co_argcount > 0:
				self.stop_code_callback(action)
			else:
				self.stop_code_callback()

	def run(self, app=None):
		self.logger.info("Running Lighthouse Flask app")
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