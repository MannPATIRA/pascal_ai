"""
Very simple test to verify Fusion 360 can run Python scripts
"""

import adsk.core

def run(context):
    """Simple test function"""
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        ui.messageBox("Hello! This is a test message from the simple test script.", "Test")
    except Exception as e:
        # If we can't even show a message box, try to print
        print(f"Error: {e}")

def stop(context):
    """Cleanup function"""
    pass
