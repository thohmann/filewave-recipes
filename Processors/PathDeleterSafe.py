#!/usr/bin/env python

from autopkglib import Processor
import os
import subprocess

__all__ = ["PathDeleterSafe"]

class PathDeleterSafe(Processor):
	'''Removes paths (files or directories) if they exist. Does not fail if paths don't exist. Uses sudo rm -rf for robust deletion of protected files.'''

	input_variables = {
		'path_list': {
			'required': True,
			'description': 'List of paths to remove',
		},
	}
	output_variables = {
	}

	description = __doc__

	def main(self):
		path_list = self.env.get('path_list')

		for path in path_list:
			if os.path.exists(path):
				try:
					proc = subprocess.Popen(
						['sudo', '/bin/rm', '-rf', path],
						stdout=subprocess.PIPE,
						stderr=subprocess.PIPE
					)
					stdout, stderr = proc.communicate()
					retcode = proc.returncode

					if retcode == 0:
						self.output('Removed path: %s' % path)
					else:
						self.output('Warning: Could not remove %s (return code: %d)' % (path, retcode))
						if stderr:
							self.output('stderr: %s' % stderr.decode('utf-8'))
						if stdout:
							self.output('stdout: %s' % stdout.decode('utf-8'))
				except Exception as e:
					self.output('Warning: Could not remove %s: %s' % (path, e))
			else:
				self.output('Path does not exist (skipping): %s' % path)

if __name__ == "__main__":
	PROCESSOR = PathDeleterSafe()
	PROCESSOR.execute_shell()
