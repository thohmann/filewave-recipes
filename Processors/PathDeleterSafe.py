#!/usr/bin/env python

from autopkglib import Processor
import os
import shutil

__all__ = ["PathDeleterSafe"]

class PathDeleterSafe(Processor):
	'''Removes paths (files or directories) if they exist. Does not fail if paths don't exist.'''

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
					if os.path.isdir(path):
						shutil.rmtree(path, ignore_errors=True)
						self.output('Removed directory: %s' % path)
					else:
						os.remove(path)
						self.output('Removed file: %s' % path)
				except Exception as e:
					self.output('Warning: Could not remove %s: %s' % (path, e))
			else:
				self.output('Path does not exist (skipping): %s' % path)

if __name__ == "__main__":
	PROCESSOR = PathDeleterSafe()
	PROCESSOR.execute_shell()
