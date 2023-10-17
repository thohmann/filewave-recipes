#!/usr/bin/python

import os
import subprocess

from autopkglib import Processor, ProcessorError

__all__ = ["ExternalScriptRunner"]

class ExternalScriptRunner(Processor):
	"""Runs external scripts."""
	input_variables = {
		"EXT_SCRIPT_PATH": {
			"required": True,
			"description": "Path to external script.",
		},
		"EXT_SCRIPT_ARGS": {
			"required": False,
			"description": ("Optional array of arguments "
				"for external script."),
		},
	}
	output_variables = {
		"ext_script_output": {
			"description": "Output of script.",
		},
		 "ext_script_status": {
			"description": "Success status of script.",
		},
   }

	description = __doc__
	
	def main(self):        
		
		# Run external script at path defined in EXT_SCRIPT_PATH with arguments provided in EXT_SCRIPT_ARGS.
		command = [self.env["EXT_SCRIPT_PATH"]]
		command.extend(self.env["EXT_SCRIPT_ARGS"])
		args_oneline = ' '.join(map(str, self.env["EXT_SCRIPT_ARGS"]))

		try:
			proc = subprocess.Popen(
				command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			(out, err_out) = proc.communicate()
		except OSError as err:
			raise ProcessorError(
				"Script '%s' execution failed with error code %d: %s" 
				% (self.env["EXT_SCRIPT_PATH"], err.errno, err.strerror))
		self.env['ext_script_status'] = proc.returncode
		if proc.returncode != 0:
			self.output("Output: %s" % out)
			raise ProcessorError(
				"Script '%s' failed with err_out: '%s'\nOutput: %s" % (self.env["EXT_SCRIPT_PATH"], err_out, out))
		
		print("Script '%s' was run successfully!\nArguments sent:\n'%s'\nOutput: %s" % (self.env["EXT_SCRIPT_PATH"], args_oneline, out))	
		self.output("Script '%s' was run successfully!\nArguments sent:\n'%s'\nOutput: %s" % (self.env["EXT_SCRIPT_PATH"], args_oneline, out))
		ext_script_output = out
		ext_script_status = proc.returncode

if __name__ == "__main__":
	processor = ExternalScriptRunner()
	processor.execute_shell()
