#!/usr/bin/env python

from autopkglib import Processor, ProcessorError
import os
import subprocess

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
		folder_path = self.env.get('path')
		for file_object in os.listdir(folder_path):
			file_object_path = os.path.join(folder_path, file_object)
			if os.path.exists(file_object_path):
				retcode = subprocess.call(['sudo', '/bin/rm', '-R', file_object_path])
				if retcode:
					raise ProcessorError('Error deleting %s' % (file_object_path))
				
				return

if __name__ == "__main__":
	PROCESSOR = PathCleaner()
	PROCESSOR.execute_shell()
