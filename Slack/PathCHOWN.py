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
		'userid': {
			'required': True,
			'description': 'chown uid E.g. "0,501,..."'
		},
		'groupid': {
			'required': True,
			'description': 'chown gid. E.g. "0,20,80,..."'
		},
	}
	output_variables = {
	}

	def main(self):
		path = self.env.get('path')
		uid = self.env.get('userid')
		gid = self.env.get('groupid')
		if os.path.exists(path):
			for root, dirs, files in os.walk(path):
				for momo in dirs:
					os.lchown(os.path.join(root, momo), int(os.getenv('SUDO_UID')), int(os.getenv('SUDO_UID')))
				for momo in files:
					os.lchown(os.path.join(root, momo), int(os.getenv('SUDO_UID')), int(os.getenv('SUDO_UID')))
	
if __name__ == "__main__":
	PROCESSOR = PathCHOWN()
	PROCESSOR.execute_shell()