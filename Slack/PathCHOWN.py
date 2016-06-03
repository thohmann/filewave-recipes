#!/usr/bin/env python

from autopkglib import Processor, ProcessorError
import os
import subprocess

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
			retcode = subprocess.call(['sudo', '/usr/sbin/chown', '-R', owner, path])
			if retcode:
				raise ProcessorError('Error setting owner (chown %s) for %s' % (owner, path))

			return
				
if __name__ == "__main__":
	PROCESSOR = PathCHOWN()
	PROCESSOR.execute_shell()