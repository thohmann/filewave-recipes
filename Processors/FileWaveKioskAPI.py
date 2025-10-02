#!/usr/bin/env python3

import requests
import json
import re
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import sys


fw_url = 'https://filewave.burda.com/api'
id_tag = '{ID}'
kiosk_options_path = f'/payloads/internal/payloads/{id_tag}/options'
kiosk_icon_path = f'/payloads/internal/payloads/{id_tag}/icon'
api_token = 'e2I0ODQ3ZmQ3LWM0M2EtNGNmNC1hNWY3LTAxYzdhMzU1NmI3NH0='
#
# Helpers
#

def get_fw_url(suffix: str, id: str) -> str:
	return f'{fw_url}{suffix}'.replace(id_tag, id)
		
#
# FW API Calls
#

def get_kiosk_options(id: str) -> Optional[Tuple[str, str]]:
	request_url = get_fw_url(kiosk_options_path, id)
	request_headers = {'Authorization': api_token, 'Content-Type': 'application/json'}
	
	response = requests.get(url=request_url, headers=request_headers, timeout=15)
	if response.status_code != 200:
		return None
	
	result = response.json()
	title = result['kiosk_title']
	description = result['kiosk_description']
	description = re.sub('<[^<]+?>', '', description).strip()  # kiosk_description is a HTML string... stripping all tags to make it readable
	
	return title, description

def set_kiosk_options(id: str, title: str, description: str) -> bool:
	request_url = get_fw_url(kiosk_options_path, test_fileset_id)
	request_headers = {'Authorization': api_token, 'Content-Type': 'application/json'}
	body = {'kiosk_title': title, 'kiosk_description': description}
	
	response = requests.patch(url=request_url, headers=request_headers, json=body, timeout=15)
	if response.status_code != 200:
		print(f'Error code: {response.status_code}. Content: {response.content}')
		return False
	
	return True

def get_kiosk_icon(id: str) -> Optional[Path]:
	image_content_types_and_suffix = {
		'image/png': 'png', 
		'image/jpeg': 'jpg'
	}
	
	request_url = get_fw_url(kiosk_icon_path, id)
	request_headers = {'Authorization': api_token, 'Content-Type': 'application/json'}
	
	response = requests.get(url=request_url, headers=request_headers, timeout=15)
	if response.status_code != 200:
		return None
	
	content_type = response.headers.get('Content-Type')
	if content_type in image_content_types_and_suffix.keys():
		suffix = image_content_types_and_suffix[content_type]
		now = datetime.now().isoformat(sep='_', timespec='seconds').replace(':', '-')
		image_path = Path.home() / 'Desktop' / f'Kiosk Image {now}.{suffix}'
		
		with open(image_path, 'wb') as file:
			file.write(response.content)
		
		return image_path
	
	return None
	
def set_kiosk_icon(id: str, icon_path: Path) -> bool:
	image_content_types_and_suffix = {
		'image/png': 'png', 
		'image/jpeg': 'jpg'
	}
	suffix = icon_path.suffix[1:]
	if suffix not in image_content_types_and_suffix.values():
		print(f'Invalid kiosk icon suffix: {suffix}.')
		return False
	content_type = [t for t, s in image_content_types_and_suffix.items() if s == suffix][0]
		
	request_url = get_fw_url(kiosk_icon_path, id)
	request_headers = {
		'Authorization': api_token, 'Content-Type': content_type,
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
	
# ---------------------------- main ---------------------------------
	
if __name__ == '__main__':
	test_fileset_id = '2140381296'
	title = description = ''
	
	print(f'Reading kiosk data from fileset ID: {test_fileset_id}:')

	options = get_kiosk_options(test_fileset_id)
	if options is not None:
		title, description = options
		print(f'  Title: {title}.')	
		print(f'  Desctiption: {description}.')
	else:
		print('  Error: No kiosk options retrieved. Exiting.')
		sys.exit(1)
	
	
	icon_path = get_kiosk_icon(test_fileset_id)
	if icon_path is not None:
		print(f'  Icon saved to {icon_path}.')
	else:
		print('  Error: No kiosk icon retrieved. Exiting.')
		sys.exit(1)
	
	print('\nFor testing purposes, you might want to add some modifications to the downloaded image. Hit return to continue.')
	input()
	
	print(f'Writing kiosk data to fileset ID: {test_fileset_id}:')
	
	now = datetime.now().isoformat()
	new_title = f'{title} | TEST {now}'
	new_description = f'{description} | TEST {now}'

	success = set_kiosk_options(test_fileset_id, new_title, new_description)
	if success:
		print(f'  Title set to {new_title}.')
		print(f'  Description set to {new_description}.')
	else:
		print('  Error: Couldn’t set kiosk options. Exiting.')
		sys.exit(1)
	
	success = set_kiosk_icon(test_fileset_id, icon_path)
	if success:
		print(f'  Icon set to this file’s contents: {icon_path}.')
	else:
		print('  Error: Couldn’t set kiosk icon. Exiting.')
		sys.exit(1)
	
	print('Done.')
	sys.exit(0)