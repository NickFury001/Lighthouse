import json, time, threading, requests
from flask import Flask, jsonify, request
from waitress import serve
from threading import Event
import logging

class Lighthouse: 
	"""
	Lighthouse is a distributed node controller for master-slave failover and status management.

	Args:
		config_path (str): Path to the configuration JSON file.
		pass_flask_app (bool, optional): Whether to pass the Flask app to the callback. Defaults to False.
		interval (int, optional): Monitor thread interval in seconds. Defaults to 5.
	"""
	def __init__(self, config_path, pass_flask_app = False, interval = 5):
		"""
		Initializes the Lighthouse node, loads configuration, and sets up logging and callbacks.

		Args:
			config_path (str): Path to the configuration JSON file.
			pass_flask_app (bool, optional): Whether to pass the Flask app to the callback. Defaults to False.
			interval (int, optional): Monitor thread interval in seconds. Defaults to 5.
		"""
		logging.basicConfig(
			level=logging.INFO,
			format="%(asctime)s [%(levelname)s] %(message)s",
		)
		self.logger = logging.getLogger("Lighthouse")
		self.config = self.load_config(config_path)
		self.pass_flask_app = pass_flask_app
		self.stop_monitor_thread = threading.Event()
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
		"""
		Registers a function to be called when starting the main code.

		Args:
			func (callable): The function to call.

		Returns:
			callable: The registered function.
		"""
		self.start_code_callback = func
		return func
	
	def stop_callback(self, func):
		"""
		Registers a function to be called when stopping the main code.

		Args:
			func (callable): The function to call.

		Returns:
			callable: The registered function.
		"""
		self.stop_code_callback = func
		return func
	
	def update_callback(self, func):
		"""
		Registers a function to be called when updating the main code.

		Args:
			func (callable): The function to call.

		Returns:
			callable: The registered function.
		"""
		self.update_code_callback = func
		return func

	def initialize(self):
		"""
		Initializes the node based on its role (master or slave), starts monitor thread if needed.
		"""
		self.logger.info("Initializing Lighthouse node with role '%s'", self.config.get('role'))
		if self.config['role'] == 'master' and self.timeout == 0:
			self.sync_from_slaves()
			self.notify_slaves("reset")
			self.start_main_code()
		elif not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
			self.stop_monitor_thread.clear()
			self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
			self.monitor_thread.start()
	
	def sync_from_slaves(self):
		"""
		Attempts to synchronize state from slave nodes.
		"""
		for ip in self.config['slaves']:
			if ip == self.config['self_addr']:
				continue
			try:
				resp = requests.get(f'http://{ip}/sync', timeout=2)
				data = resp.json()
				if data.get('last_update'):
					self.logger.info("Synced state from slave %s", ip)
					if self.update_code_callback:
						self.update_code_callback(data['last_update'])
					break
			except Exception as e:
				self.logger.error(f"Failed to sync from slave {ip}: {e}")

	def load_config(self, path):
		"""
		Loads configuration from a JSON file.

		Args:
			path (str): Path to the configuration file.

		Returns:
			dict: The loaded configuration.
		"""
		self.logger.info("Loading config from %s", path)
		with open(path, 'r') as f:
			return json.load(f)
	
	def register_routes(self):
		"""
		Registers Flask routes for status, reset, stop, update, and sync endpoints.
		"""
		self.logger.info("Registering Flask routes")
		self.app.add_url_rule("/status", "status", self.get_status, methods=["GET"])
		self.app.add_url_rule("/reset", "reset", self.reset, methods=["POST"])
		self.app.add_url_rule("/stop", "stop", self.stop, methods=["POST"])
		self.app.add_url_rule("/update", "update", self.update, methods=["POST"])
		self.app.add_url_rule("/sync", "sync", self.sync, methods=["GET"])

	def set_temp_status(self, status_msg = "stopped temporarily", timeout = 60):
		"""
		Sets a temporary status for the node and stops the main code for a timeout period.

		Args:
			status_msg (str, optional): The temporary status message. Defaults to "stopped temporarily".
			timeout (int, optional): Timeout in seconds. Defaults to 60.
		"""
		self.logger.warning("Setting temporary status: '%s' for %ds", status_msg, timeout)
		self.custom_status = True
		self.status = status_msg
		self.timeout_start = time.time()
		self.timeout = timeout
		self.stop_main_code("stop")

	def get_status(self):
		"""
		Returns the current status of the node as a JSON response.

		Returns:
			Response: Flask JSON response with name, status, and slaves.
		"""
		self.logger.debug("Status requested")
		return jsonify({
			'name': self.config['name'] if 'name' in self.config else 'Server',
			'status': self.status,
			'slaves': self.config['slaves']
		})

	def reset(self):
		"""
		Handles the /reset endpoint. Stops main code and reinitializes the node.

		Returns:
			Response: Empty response with status 204.
		"""
		self.logger.info("Reset endpoint called")
		self.stop_main_code("reset")
		self.initialize()
		return '', 204

	def stop(self):
		"""
		Handles the /stop endpoint. Stops the main code.

		Returns:
			Response: Empty response with status 204.
		"""
		self.logger.info("Stop endpoint called")
		self.stop_main_code("stop")
		return '', 204

	def sync(self):
		"""
		Handles the /sync endpoint. Returns the last update as JSON.

		Returns:
			Response: Flask JSON response with last_update.
		"""
		self.logger.debug("Sync endpoint called")
		return jsonify({'last_update': self.last_update}), 200

	def update(self):
		"""
		Handles the /update endpoint. Updates the node's state with provided data.

		Returns:
			Response: Empty response with status 204.
		"""
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
		"""
		Sends an update to all slave nodes.

		Args:
			data (dict): The update data to send.
		"""
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
		"""
		Monitor thread for failover and status checking. Promotes to active if needed.
		"""
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
		"""
		Pings a node for its status.

		Args:
			ip (str): The IP address to ping.

		Returns:
			str: 'UP', 'IDLE', or 'DOWN' depending on the node's status.
		"""
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
		"""
		Pings a node and returns its raw status string.

		Args:
			ip (str): The IP address to ping.

		Returns:
			str or None: The status string or None if failed.
		"""
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			return data['status']
		except Exception:
			self.logger.warning("Failed to ping raw status of %s", ip)
			return None

	def get_slaves(self, ip):
		"""
		Gets the list of slave IPs from a node.

		Args:
			ip (str): The IP address to query.

		Returns:
			list: List of slave IPs.
		"""
		try:
			res = requests.get(f'http://{ip}/status', timeout=2)
			data = res.json()
			ip_list = data['slaves'] if self.config['parent_addr'] in data['slaves'] else [self.config['parent_addr']] + data['slaves']
			return ip_list
		except Exception:
			self.logger.warning("Failed to get slaves from %s", ip)
			return []

	def any_main_running(self):
		"""
		Checks if any main node is running among the slaves or parent.

		Returns:
			bool: True if any node is running, False otherwise.
		"""
		ip_list = self.config['slaves'] if self.config['role'] == 'master' or ('parent_addr' in self.config and self.config['parent_addr'] in self.config['slaves']) else [self.config['parent_addr']] + self.config['slaves']
		for ip in ip_list:
			if ip == self.config['self_addr']:
				continue
			if self.ping_status(ip) == 'UP':
				return True
		return False

	def promote_to_active(self):
		"""
		Promotes this node to active (running) status and notifies slaves.
		"""
		self.logger.info("Promoting node to active")
		self.start_main_code()
		self.notify_slaves('reset')

	def notify_slaves(self, endpoint):
		"""
		Notifies all slave nodes at a given endpoint.

		Args:
			endpoint (str): The endpoint to notify (e.g., 'reset').
		"""
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
		"""
		Starts the main code, sets status to 'running', and calls the start callback.
		"""
		self.logger.info('Starting main code...')
		self.status = 'running'
		if self.start_code_callback:
			if self.pass_flask_app:
				if not hasattr(self, 'app') or self.app is None:
					self.app = Flask(__name__)
				port = self.config['self_addr'].rsplit(':', 1)[1]
				self.start_code_callback(self.app, port)
			else:
				self.start_code_callback()

	def get_all_statuses(self):
		"""
		Gets the status of all nodes (self, slaves, and parent if applicable).

		Returns:
			list: List of dicts with name, ip, and status for each node.
		"""
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
		"""
		Stops the main code and sets status to 'waiting' unless a custom status is set.

		Args:
			action (str): The action that triggered the stop (e.g., 'stop', 'reset').
		"""
		self.logger.info('Stopping main code...')
		self.status = 'waiting' if not self.custom_status else self.status
		if self.stop_code_callback:
			if self.stop_code_callback.__code__.co_argcount > 0:
				self.stop_code_callback(action)
			else:
				self.stop_code_callback()

	def run(self, app=None):
		"""
		Runs the Flask app and starts the Lighthouse node.

		Args:
			app (Flask, optional): An existing Flask app instance. If None, a new one is created.
		"""
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