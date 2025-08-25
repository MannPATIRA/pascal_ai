"""
Simple test script to verify the add-in can be loaded
Run this in Fusion 360's Python environment
"""

import sys
import traceback

def test_addin_load():
    """Test if the add-in can be loaded"""
    try:
        print("Testing add-in load...")
        
        # Test imports
        print("Testing imports...")
        import adsk.core
        import adsk.fusion
        print("✓ Fusion imports successful")
        
        # Test config import
        print("Testing config import...")
        from config import *
        print("✓ Config import successful")
        
        # Test file existence
        print("Testing file existence...")
        from pathlib import Path
        if HTML_FILE.exists():
            print(f"✓ HTML file exists: {HTML_FILE}")
        else:
            print(f"✗ HTML file missing: {HTML_FILE}")
            
        if Path(AGENT_SCRIPT).exists():
            print(f"✓ Agent script exists: {AGENT_SCRIPT}")
        else:
            print(f"✗ Agent script missing: {AGENT_SCRIPT}")
        
        # Test Fusion UI access
        print("Testing Fusion UI access...")
        app = adsk.core.Application.get()
        ui = app.userInterface
        print("✓ Fusion UI access successful")
        
        # Test workspace access
        print("Testing workspace access...")
        workspaces_to_try = ['FusionDesignEnvironment', 'FusionSolidEnvironment', 'FusionModelEnvironment']
        ws = None
        for ws_id in workspaces_to_try:
            ws = ui.workspaces.itemById(ws_id)
            if ws:
                print(f"✓ Workspace found: {ws_id}")
                break
        else:
            print("✗ No workspaces found")
            return False
            
        # Test panel access
        panels_to_try = ['SolidCreatePanel', 'SolidModifyPanel', 'SolidInspectPanel']
        for panel_name in panels_to_try:
            panel = ws.toolbarPanels.itemById(panel_name)
            if panel:
                print(f"✓ Panel found: {panel_name}")
                break
        else:
            print("✗ No panels found")
        
        print("Add-in load test completed!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    test_addin_load()
