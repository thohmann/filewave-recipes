#!/usr/bin/env python

from autopkglib import Processor, ProcessorError
import subprocess
import os

__all__ = ["ModeChanger"]

class ModeChanger(Processor):
	'''Changes file modes'''

	input_variables = {
		'path': {
			'required': True,
			'description': 'Name of filename resource',
		},
		'mode': {
			'required': True,
			'description': 'chmod(1) mode string to apply to file. E.g. "o-w"'
		},
	}
	output_variables = {
	}

	def main(self):
		path = self.env.get('path')
		mode = self.env.get('mode')

		retcode = subprocess.call(['/bin/chmod','-R', mode, path])
		if retcode:
			raise ProcessorError('Error setting mode (chmod %s) for %s' % (mode, path))

		return
