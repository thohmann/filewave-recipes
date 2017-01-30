#!/usr/bin/env python

from autopkglib import Processor, ProcessorError
import os
import subprocess
import getpass

__all__ = ["PathCleaner"]

class PathCleaner(Processor):
	'''Deletes content of folder path'''

	input_variables = {
		'path': {
			'required': True,
			'description': 'Name of filename resource',
		},
	}
	output_variables = {
	}

	def main(self):
		path = self.env.get('path')
		if os.path.exists(path):
			retcode = subprocess.call(['sudo', '/bin/rm', '-R', path + '/*'])
			if retcode:
				raise ProcessorError('Error cleaning Path %s' % (path))

			return
				
if __name__ == "__main__":
	PROCESSOR = PathCleaner()
	PROCESSOR.execute_shell()
