#!/usr/bin/env python

from autopkglib import Processor, ProcessorError
import os

__all__ = ["PathCHOWN"]

class PathCHOWN(Processor):
	'''Changes path owner'''

	input_variables = {
		'path': {
			'required': True,
			'description': 'Name of filename resource',
		},
		'user': {
			'required': True,
			'description': 'chown uid E.g. "0,501,..."'
		},
		'group': {
			'required': True,
			'description': 'chown gid. E.g. "0,20,80,..."'
		},
	}
	output_variables = {
	}

	def main(self):
		path = self.env.get('path')
		user = self.env.get('user')
		group = self.env.get('group')
		if os.path.exists(path):
			owner = user + ':' + group
			cmd = ['sudo', 'chown', '-R', owner, path]
			proc = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			
			'''for root, dirs, files in os.walk(path):
				for momo in dirs:
					os.lchown(os.path.join(root, momo), int(os.getenv('SUDO_UID')), int(os.getenv('SUDO_UID')))
				for momo in files:
					os.lchown(os.path.join(root, momo), int(os.getenv('SUDO_UID')), int(os.getenv('SUDO_UID')))'''
	
if __name__ == "__main__":
	PROCESSOR = PathCHOWN()
	PROCESSOR.execute_shell()