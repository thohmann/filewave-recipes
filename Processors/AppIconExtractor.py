#!/usr/bin/env python3

"""
AppIconExtractor.py

AutoPkg Processor that extracts an app icon and converts it to PNG format.
Can also be used standalone without AutoPkg.
"""

import os
import subprocess
import sys

__all__ = ["AppIconExtractor"]


# Fallback classes for standalone usage
try:
    from autopkglib import Processor, ProcessorError
except ImportError:
    class ProcessorError(Exception):
        """Custom exception for processor errors when AutoPkg is not available"""
        pass

    class Processor:
        """Minimal Processor base class for standalone usage"""
        description = ""
        input_variables = {}
        output_variables = {}
        env = {}

        def output(self, msg):
            """Print output message"""
            print(msg)

        def execute_shell(self):
            """Minimal shell execution for standalone usage"""
            import argparse
            parser = argparse.ArgumentParser(description=self.description)
            for key, value in self.input_variables.items():
                required = value.get("required", False)
                default = value.get("default")
                help_text = value.get("description", "")
                parser.add_argument(
                    f"--{key}",
                    required=required,
                    default=default,
                    help=help_text
                )
            args = parser.parse_args()
            self.env = vars(args)
            self.main()


class AppIconExtractor(Processor):
    """
    Extracts the app icon from a macOS application bundle and converts it to PNG format.
    """

    description = __doc__
    input_variables = {
        "app_path": {
            "required": True,
            "description": "Path to the .app bundle (e.g., /Applications/MyApp.app)",
        },
        "output_dir": {
            "required": True,
            "description": "Directory where the PNG icon will be saved",
        },
        "icon_size": {
            "required": False,
            "description": "Size of the output icon in pixels (default: 256)",
            "default": "256",
        },
        "output_filename": {
            "required": False,
            "description": (
                "Output filename (without extension). "
                "If not provided, uses the app name."
            ),
        },
    }
    output_variables = {
        "icon_path": {
            "description": "Path to the created PNG icon file",
        },
    }

    def main(self):
        app_path = self.env.get("app_path")
        output_dir = self.env.get("output_dir")
        icon_size = self.env.get("icon_size", "256")
        output_filename = self.env.get("output_filename")

        # Validate app_path
        if not os.path.exists(app_path):
            raise ProcessorError(f"App path does not exist: {app_path}")

        if not app_path.endswith(".app"):
            raise ProcessorError(f"Provided path is not an app bundle: {app_path}")

        # Get app name if output_filename not provided
        if not output_filename:
            app_name = os.path.basename(app_path).replace(".app", "")
            output_filename = app_name

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Find the icon file in the app bundle
        info_plist_path = os.path.join(app_path, "Contents", "Info.plist")

        # Try to get icon name from Info.plist
        icon_file = None
        if os.path.exists(info_plist_path):
            try:
                import plistlib
                with open(info_plist_path, "rb") as f:
                    info_plist = plistlib.load(f)
                    icon_name = info_plist.get("CFBundleIconFile", "")
                    if icon_name:
                        # Remove .icns extension if present
                        if not icon_name.endswith(".icns"):
                            icon_name = f"{icon_name}.icns"
                        icon_file = os.path.join(
                            app_path, "Contents", "Resources", icon_name
                        )
            except Exception as e:
                self.output(f"Could not read Info.plist: {e}")

        # Fallback: look for common icon names
        if not icon_file or not os.path.exists(icon_file):
            resources_dir = os.path.join(app_path, "Contents", "Resources")
            if os.path.exists(resources_dir):
                # Try common icon names
                for icon_name in ["AppIcon.icns", "app.icns", "icon.icns"]:
                    potential_icon = os.path.join(resources_dir, icon_name)
                    if os.path.exists(potential_icon):
                        icon_file = potential_icon
                        break

                # If still not found, find first .icns file
                if not icon_file or not os.path.exists(icon_file):
                    for file in os.listdir(resources_dir):
                        if file.endswith(".icns"):
                            icon_file = os.path.join(resources_dir, file)
                            break

        if not icon_file or not os.path.exists(icon_file):
            raise ProcessorError(
                f"Could not find icon file in app bundle: {app_path}"
            )

        self.output(f"Found icon file: {icon_file}")

        # Output path for PNG
        output_path = os.path.join(output_dir, f"{output_filename}.png")

        # Step 1: Convert icns to png
        self.output(f"Converting {icon_file} to PNG...")
        try:
            subprocess.run(
                [
                    "sips",
                    "-s",
                    "format",
                    "png",
                    icon_file,
                    "--out",
                    output_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise ProcessorError(
                f"Failed to convert icon to PNG: {e.stderr}"
            )

        # Step 2: Resize the PNG
        self.output(f"Resizing PNG to {icon_size}x{icon_size}...")
        try:
            subprocess.run(
                [
                    "sips",
                    output_path,
                    "-z",
                    icon_size,
                    icon_size,
                    "--out",
                    output_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise ProcessorError(
                f"Failed to resize PNG: {e.stderr}"
            )

        self.output(f"Successfully created icon: {output_path}")
        self.env["icon_path"] = output_path


if __name__ == "__main__":
    processor = AppIconExtractor()
    processor.execute_shell()
