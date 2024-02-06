#!/usr/local/autopkg/python

from autopkglib import Processor, ProcessorError

import requests
from pathlib import Path
from typing import Optional

class FilewaveKioskImporter(Processor):
	fw_url = 'https://filewave.burda.com/api'
	id_tag = '{ID}'
	kiosk_options_url = f'/payloads/internal/payloads/{id_tag}/options'
	kiosk_icon_url = f'/payloads/internal/payloads/{id_tag}/icon'
	api_token = 'e2I0ODQ3ZmQ3LWM0M2EtNGNmNC1hNWY3LTAxYzdhMzU1NmI3NH0='
	
	input_variables = {
		'fileset_id': {
			'required': True,
			'description': 'Fileset ID of the Fileset that should be edited.',
		},
		'kiosk_title': {
			'required': True,
			'description': 'Title shown in kiosk ',
		},
		'kiosk_description': {
			'required': False,
			'description': 'Description text shown in kiosk '
		},
		'kiosk_icon_path': {
			'required': False,
			'description': 'Path to the icon shown in kiosk'
		},
		
	}
	output_variables = {
	}
	
	def main(self):
			fileset_id = self.env.get('fileset_id')
			kiosk_title = self.env.get('kiosk_title')
			kiosk_description = self.env.get('kiosk_description')
			kiosk_icon_path = Path(self.env.get('kiosk_icon_path'))
		
			retcode_options = self.set_kiosk_options(fileset_id, kiosk_title, kiosk_description)
			if not retcode_options:
				raise ProcessorError("Error: Couldn’t set kiosk options.")
				
			retcode_icon = self.set_kiosk_icon(fileset_id, kiosk_icon_path)
			if not retcode_icon:
				raise ProcessorError("Error: Couldn’t set kiosk icon.")
				
	def get_fw_url(self, suffix: str, id: str) -> str:
		return f'{self.fw_url}{suffix}'.replace(self.id_tag, id)
	
	def set_kiosk_icon(self, id: str, icon_path: Path) -> bool:
		image_content_types_and_suffix = {
			'image/png': 'png', 
			'image/jpeg': 'jpg'
		}
		suffix = icon_path.suffix[1:]
		if suffix not in image_content_types_and_suffix.values():
			print(f'Invalid kiosk icon suffix: {suffix}.')
			return False
		content_type = [t for t, s in image_content_types_and_suffix.items() if s == suffix][0]
		
		request_url = self.get_fw_url(self.kiosk_icon_url, id)
		request_headers = {
			'Authorization': self.api_token, 'Content-Type': content_type,
			'Content-Disposition': f'attachment; filename={icon_path.name}'
		}
		image_data: Optional[bytes] = None
		with open(icon_path, mode='rb') as file:
			image_data = file.read()
			
			
		response = requests.patch(url=request_url, headers=request_headers, data=image_data, timeout=15)
		if response.status_code != 200:
			print(f'Error code: {response.status_code}. Content: {response.content}')
			return False
		
		return True
	
	def set_kiosk_options(self, id: str, title: str, description: str) -> bool:
		request_url = self.get_fw_url(self.kiosk_options_url, id)
		request_headers = {'Authorization': self.api_token, 'Content-Type': 'application/json'}
		body = {'kiosk_title': title, 'kiosk_description': description}
		
		response = requests.patch(url=request_url, headers=request_headers, json=body, timeout=15)
		if response.status_code != 200:
			print(f'Error code: {response.status_code}. Content: {response.content}')
			return False
		
		return True
	
		
		
if __name__ == "__main__":
	PROCESSOR = FilewaveKioskImporter()
	PROCESSOR.execute_shell()
	