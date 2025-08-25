"""
PASCAL Agent Add-in for Fusion 360
Provides natural language CAD creation through LLM-powered conversation
"""

import adsk.core
import adsk.fusion
import adsk.cam
import traceback
import subprocess
import json
import uuid
import os
import sys
from pathlib import Path

# Add current directory to Python path for imports
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Import configuration
try:
    from config import *
except ImportError as e:
    # Fallback: define configuration directly
    print(f"Warning: Could not import config.py: {e}")
    print("Using fallback configuration...")
    
    # Fallback configuration
    DEBUG = True
    ADDIN_NAME = "AgentAddIn1"
    COMPANY_NAME = 'PASCAL'
    WORKSPACE_ID = 'FusionDesignEnvironment'
    PANEL_ID = 'SolidCreatePanel'
    CMD_ID = 'pascal_agent_cmd'
    CMD_NAME = 'PASCAL Agent'
    CMD_DESC = 'Chat, clarify, plan, and execute CAD steps safely.'
    PALETTE_ID = 'pascal_agent_palette'
    PALETTE_WIDTH = 460
    PALETTE_HEIGHT = 600
    
    # Paths
    HERE = current_dir
    EXTERNAL_DIR = HERE / 'external'
    HTML_FILE = HERE / 'palette.html'
    AGENT_SCRIPT = str(EXTERNAL_DIR / 'agent_runner.py')
    PYTHON_EXE = 'pythonw.exe'
    
    # LLM Configuration
    OPENAI_MODEL = "gpt-4o"
    MAX_RETRIES = 3
    RETRY_SLEEP_SECONDS = 0.5
    REQUEST_TIMEOUT = 180

# ============================================================
# Global State Management
# ============================================================

class AddinState:
    """Manages global state for the add-in"""
    
    def __init__(self):
        self.session_id = None
        self.last_actions = []
        self.last_sketch = None
        self.last_profile = None
        self.handlers = []

# Global state instance
_state = AddinState()

# ============================================================
# Fusion UI Management
# ============================================================

class FusionUI:
    """Handles Fusion 360 UI setup and management"""
    
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.ui = self.app.userInterface
    
    def setup_command(self):
        """Set up the main command button"""
        try:
            # Check if command already exists
            cmd_def = self.ui.commandDefinitions.itemById(CMD_ID)
            if not cmd_def:
                cmd_def = self.ui.commandDefinitions.addButtonDefinition(
                    CMD_ID, CMD_NAME, CMD_DESC
                )
            
            # Add command created handler
            on_created = CommandCreatedHandler()
            cmd_def.commandCreated.add(on_created)
            _state.handlers.append(on_created)
            
            # Try to add to panel with fallback options
            panel_added = False
            fallback_panels = [
                'SolidCreatePanel',
                'SolidModifyPanel', 
                'SolidInspectPanel',
                'SolidAssemblePanel'
            ]
            
            for panel_id in fallback_panels:
                try:
                    ws = self.ui.workspaces.itemById(WORKSPACE_ID)
                    if ws:
                        panel = ws.toolbarPanels.itemById(panel_id)
                        if panel and not panel.controls.itemById(CMD_ID):
                            panel.controls.addCommand(cmd_def)
                            panel_added = True
                            if DEBUG:
                                self.ui.messageBox(f"Command added to panel: {panel_id}", "Debug Info")
                            break
                except Exception as e:
                    if DEBUG:
                        self.ui.messageBox(f"Error trying panel {panel_id}: {e}", "Debug Info")
                    continue
            
            if not panel_added:
                if DEBUG:
                    self.ui.messageBox("Could not add command to any panel. Command created but not visible.", "Debug Info")
                    
        except Exception as e:
            if DEBUG:
                self.ui.messageBox(f"Error in setup_command: {e}", "Debug Info")
            raise
    
    def cleanup_command(self):
        """Clean up command and UI elements"""
        try:
            # Remove from panel - try multiple workspaces and panels
            workspaces_to_try = ['FusionDesignEnvironment', 'FusionSolidEnvironment', 'FusionModelEnvironment']
            panels_to_try = ['SolidCreatePanel', 'SolidModifyPanel', 'SolidInspectPanel', 'SolidAssemblePanel']
            
            for ws_id in workspaces_to_try:
                try:
                    ws = self.ui.workspaces.itemById(ws_id)
                    if ws:
                        for panel_id in panels_to_try:
                            try:
                                panel = ws.toolbarPanels.itemById(panel_id)
                                if panel:
                                    ctrl = panel.controls.itemById(CMD_ID)
                                    if ctrl:
                                        ctrl.deleteMe()
                                        if DEBUG:
                                            self.ui.messageBox(f"Removed command from {panel_id}", "Debug Info")
                            except Exception as e:
                                if DEBUG:
                                    self.ui.messageBox(f"Error removing from panel {panel_id}: {e}", "Debug Info")
                                continue
                except Exception as e:
                    if DEBUG:
                        self.ui.messageBox(f"Error accessing workspace {ws_id}: {e}", "Debug Info")
                    continue
            
            # Remove command definition
            try:
                cmd_def = self.ui.commandDefinitions.itemById(CMD_ID)
                if cmd_def:
                    cmd_def.deleteMe()
                    if DEBUG:
                        self.ui.messageBox("Removed command definition", "Debug Info")
            except Exception as e:
                if DEBUG:
                    self.ui.messageBox(f"Error removing command definition: {e}", "Debug Info")
            
            # Remove palette
            try:
                pal = self.ui.palettes.itemById(PALETTE_ID)
                if pal:
                    pal.deleteMe()
                    if DEBUG:
                        self.ui.messageBox("Removed palette", "Debug Info")
            except Exception as e:
                if DEBUG:
                    self.ui.messageBox(f"Error removing palette: {e}", "Debug Info")
                
        except Exception as e:
            if self.ui:
                self.ui.messageBox(f'Add-In cleanup failed:\n{traceback.format_exc()}')

# ============================================================
# Event Handlers
# ============================================================

class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Handles command creation event"""
    
    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            # Generate new session ID
            _state.session_id = str(uuid.uuid4())
            
            # Create or get palette
            ui = adsk.core.Application.get().userInterface
            pal = ui.palettes.itemById(PALETTE_ID)
            if not pal:
                pal = ui.palettes.add(
                    PALETTE_ID, 'PASCAL Agent', 
                    HTML_FILE.as_uri(), True, True, True, 
                    PALETTE_WIDTH, PALETTE_HEIGHT
                )
                
                # Add HTML event handler
                on_html = PaletteHTMLHandler()
                pal.incomingFromHTML.add(on_html)
                _state.handlers.append(on_html)
            
            pal.isVisible = True
            
            # Send welcome message
            send_to_html({
                "status": "need_clarification",
                "assistant_message": "Hi! Tell me what you want to create. I'll ask questions, plan steps, and prepare actions safely."
            })
            
        except Exception as e:
            send_to_html({
                "status": "need_clarification",
                "assistant_message": f"Command creation failed:\n{traceback.format_exc()}"
            })

class PaletteHTMLHandler(adsk.core.HTMLEventHandler):
    """Handles messages from HTML palette"""
    
    def notify(self, args: adsk.core.HTMLEventArgs):
        try:
            # Only handle our specific events
            if args.action != 'agent_event':
                return
            
            # Parse event data
            data_json = args.data or "{}"
            data = json.loads(data_json)
            event = (data.get("event") or "").strip()
            user_message = (data.get("user_message") or "").strip()
            
            # Acknowledge receipt
            send_to_html({
                "assistant_message": f"↘ received {event}",
                "questions": [], "plan": [], "actions": []
            })
            
            # Handle different event types
            if event == 'user_message':
                handle_agent_event("user_message", user_message)
            elif event == 'confirm_execute':
                handle_agent_event("confirm_execute", "OK to proceed")
            else:
                send_to_html({
                    "status": "need_clarification",
                    "assistant_message": f"Unsupported event '{event}'."
                })
                
        except Exception as e:
            send_to_html({
                "status": "need_clarification",
                "assistant_message": f"HTML parsing error:\n{traceback.format_exc()}"
            })

# ============================================================
# Agent Communication
# ============================================================

class AgentCommunicator:
    """Handles communication with the external agent process"""
    
    @staticmethod
    def call_agent(event: str, user_message: str) -> dict:
        """Call the external agent process"""
        try:
            payload = {"event": event, "user_message": user_message}
            
            # Set up subprocess for Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags |= subprocess.CREATE_NO_WINDOW
            
            # Call external process
            completed = subprocess.run(
                [PYTHON_EXE, AGENT_SCRIPT, _state.session_id, json.dumps(payload)],
                capture_output=True, text=True, shell=False, timeout=REQUEST_TIMEOUT,
                startupinfo=startupinfo, creationflags=creationflags
            )
            
            # Handle process errors
            if completed.returncode != 0:
                return {
                    "status": "need_clarification",
                    "assistant_message": f"Agent returned code {completed.returncode}.\nSTDERR:\n{(completed.stderr or '').strip()}"
                }
            
            # Parse response
            output = (completed.stdout or "").strip()
            try:
                return json.loads(output or "{}")
            except Exception as e:
                return {
                    "status": "need_clarification",
                    "assistant_message": f"Agent JSON decode failed: {e}\nRaw:\n{output[:600]}"
                }
                
        except Exception as e:
            return {
                "status": "need_clarification",
                "assistant_message": f"Agent call failed: {e}"
            }

# ============================================================
# Fusion Action Execution
# ============================================================

class FusionActionExecutor:
    """Executes Fusion 360 actions"""
    
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.design = adsk.fusion.Design.cast(self.app.activeProduct)
        if not self.design:
            raise RuntimeError("No active Fusion design")
        self.root = self.design.rootComponent
    
    def execute_actions(self, actions: list) -> tuple[bool, str]:
        """Execute a list of Fusion actions"""
        try:
            sketch_context = {}
            last_profile = None
            made_geometry = False
            
            for idx, action in enumerate(actions):
                action_name = action.get("action")
                params = action.get("params", {})
                
                if action_name == "create_sketch":
                    success = self._create_sketch(params, sketch_context, idx)
                    if success:
                        made_geometry = True
                        # Don't set last_profile here - wait for geometry
                
                elif action_name == "add_rectangle":
                    success = self._add_rectangle(params, sketch_context)
                    if success:
                        made_geometry = True
                        last_profile = self._get_last_profile(_state.last_sketch)
                        if DEBUG:
                            ui = adsk.core.Application.get().userInterface
                            ui.messageBox(f"Rectangle created, profile: {last_profile is not None}", "Debug")
                
                elif action_name == "add_circle":
                    success = self._add_circle(params, sketch_context)
                    if success:
                        made_geometry = True
                        last_profile = self._get_last_profile(_state.last_sketch)
                        if DEBUG:
                            ui = adsk.core.Application.get().userInterface
                            ui.messageBox(f"Circle created, profile: {last_profile is not None}", "Debug")
                
                elif action_name == "extrude_last_profile":
                    # Try to use the tracked profile first, then fall back to finding it
                    profile_to_extrude = last_profile or _state.last_profile
                    success = self._extrude_profile(params, profile_to_extrude)
                    if success:
                        made_geometry = True
                
                elif action_name == "add_text":
                    success = self._add_text(params)
                    if success:
                        made_geometry = True
            
            # Fit view if geometry was created
            if made_geometry:
                try:
                    self.app.activeViewport.fit()
                except:
                    pass
            
            return True, "All actions executed successfully."
            
        except Exception as e:
            return False, f"Execution error: {e}\n{traceback.format_exc()}"
    
    def _create_sketch(self, params: dict, context: dict, idx: int) -> bool:
        """Create a new sketch"""
        plane_map = {
            "XY": self.root.xYConstructionPlane,
            "YZ": self.root.yZConstructionPlane,
            "XZ": self.root.xZConstructionPlane
        }
        
        plane = plane_map.get(params.get("plane", "XY"))
        if not plane:
            return False
        
        sketch = self.root.sketches.add(plane)
        try:
            sketch.isVisible = True
        except:
            pass
        
        context[f"sk_{idx}"] = sketch
        _state.last_sketch = sketch
        return True
    
    def _add_rectangle(self, params: dict, context: dict) -> bool:
        """Add a rectangle to a sketch"""
        sketch = context.get(params.get("sketch_id")) or _state.last_sketch
        if not sketch:
            sketch = self._create_fallback_sketch()
        
        x1, y1 = float(params["x1"]), float(params["y1"])
        x2, y2 = float(params["x2"]), float(params["y2"])
        
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(x1, y1, 0),
            adsk.core.Point3D.create(x2, y2, 0)
        )
        
        _state.last_sketch = sketch
        return True
    
    def _add_circle(self, params: dict, context: dict) -> bool:
        """Add a circle to a sketch"""
        sketch = context.get(params.get("sketch_id")) or _state.last_sketch
        if not sketch:
            sketch = self._create_fallback_sketch()
        
        cx, cy, r = float(params["cx"]), float(params["cy"]), float(params["r"])
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(cx, cy, 0), r
        )
        
        _state.last_sketch = sketch
        return True
    
    def _extrude_profile(self, params: dict, profile) -> bool:
        """Extrude a profile"""
        try:
            # Find profile if not provided
            if not profile:
                profile = self._find_recent_profile()
            
            if not profile:
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox("No profile found to extrude. Make sure you have a valid sketch with geometry.", "Extrude Error")
                return False
            
            # Get parameters
            distance = float(params.get("distance", 1.0))
            operation = params.get("operation", "NewBody")
            
            # Validate distance
            if distance <= 0:
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox(f"Invalid distance: {distance}. Must be positive.", "Extrude Error")
                return False
            
            # Map operation string to Fusion enum
            operation_map = {
                "NewBody": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                "Cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
                "Join": adsk.fusion.FeatureOperations.JoinFeatureOperation
            }
            
            op = operation_map.get(operation, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            
            # Create extrude feature
            ext_feats = self.root.features.extrudeFeatures
            dval = adsk.core.ValueInput.createByReal(distance)
            
            # Create input and set parameters
            ext_input = ext_feats.createInput(profile, op)
            ext_input.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(dval), adsk.fusion.ExtentDirections.PositiveExtentDirection)
            
            # Add the feature
            ext_feat = ext_feats.add(ext_input)
            
            if ext_feat:
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox(f"Successfully extruded profile by {distance}cm", "Extrude Success")
                return True
            else:
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox("Failed to create extrude feature", "Extrude Error")
                return False
                
        except Exception as e:
            if DEBUG:
                ui = adsk.core.Application.get().userInterface
                ui.messageBox(f"Extrude error: {str(e)}", "Extrude Error")
            return False
    
    def _add_text(self, params: dict) -> bool:
        """Add text to a sketch"""
        plane_map = {
            "XY": self.root.xYConstructionPlane,
            "YZ": self.root.yZConstructionPlane,
            "XZ": self.root.xZConstructionPlane
        }
        
        plane = plane_map.get(params.get("plane", "XY"))
        if not plane:
            return False
        
        sketch = self.root.sketches.add(plane)
        try:
            sketch.isVisible = True
        except:
            pass
        
        text = str(params.get("text", ""))
        height = float(params.get("height", 1.0))
        x, y = float(params.get("x", 0)), float(params.get("y", 0))
        
        text_input = sketch.sketchTexts.createInput(
            text, height, adsk.core.Point3D.create(x, y, 0)
        )
        sketch.sketchTexts.add(text_input)
        
        _state.last_sketch = sketch
        return True
    
    def _create_fallback_sketch(self):
        """Create a fallback sketch if none exists"""
        if _state.last_sketch:
            return _state.last_sketch
        
        sketch = self.root.sketches.add(self.root.xYConstructionPlane)
        try:
            sketch.isVisible = True
        except:
            pass
        _state.last_sketch = sketch
        return sketch
    
    def _get_last_profile(self, sketch) -> adsk.fusion.Profile:
        """Get the last profile from a sketch"""
        if sketch and sketch.profiles.count > 0:
            profile = sketch.profiles.item(sketch.profiles.count - 1)
            _state.last_profile = profile
            return profile
        return None
    
    def _find_recent_profile(self) -> adsk.fusion.Profile:
        """Find the most recent profile from any sketch"""
        try:
            # First try the cached profile
            if _state.last_profile:
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox("Using cached profile", "Profile Debug")
                return _state.last_profile
            
            # Search through sketches in reverse order
            sketches = self.root.sketches
            if DEBUG:
                ui = adsk.core.Application.get().userInterface
                ui.messageBox(f"Searching {sketches.count} sketches for profiles", "Profile Debug")
            
            for i in range(sketches.count - 1, -1, -1):
                sketch = sketches.item(i)
                if DEBUG:
                    ui = adsk.core.Application.get().userInterface
                    ui.messageBox(f"Checking sketch {i}: {sketch.profiles.count} profiles", "Profile Debug")
                
                if sketch.profiles.count > 0:
                    profile = sketch.profiles.item(sketch.profiles.count - 1)
                    _state.last_profile = profile
                    if DEBUG:
                        ui.messageBox(f"Found profile in sketch {i}", "Profile Debug")
                    return profile
            
            if DEBUG:
                ui = adsk.core.Application.get().userInterface
                ui.messageBox("No profiles found in any sketch", "Profile Debug")
            return None
            
        except Exception as e:
            if DEBUG:
                ui = adsk.core.Application.get().userInterface
                ui.messageBox(f"Error finding profile: {str(e)}", "Profile Error")
            return None

# ============================================================
# Main Event Handler
# ============================================================

def handle_agent_event(event: str, user_message: str):
    """Main event handler for agent communication"""
    global _state
    
    # Get agent response
    reply = AgentCommunicator.call_agent(event, user_message)
    send_to_html(reply)
    
    # Cache actions if present
    if isinstance(reply.get("actions"), list) and reply["actions"]:
        _state.last_actions = reply["actions"]
    
    # Handle execution confirmation
    if event == "confirm_execute":
        actions = reply.get("actions") or _state.last_actions or []
        
        if not actions:
            # Try to force action generation with a more specific prompt
            force_payload = {
                "event": "force_actions", 
                "user_message": f"Generate executable Fusion actions for: {user_message}. Use default values: plane=XY, position=(0,0), size=2cm if not specified."
            }
            force_reply = AgentCommunicator.call_agent("force_actions", force_payload["user_message"])
            
            if isinstance(force_reply.get("actions"), list) and force_reply["actions"]:
                actions = force_reply["actions"]
                _state.last_actions = actions
                send_to_html({
                    "status": "ready_to_execute",
                    "assistant_message": "Generated actions from your request. Executing now.",
                    "questions": [], "plan": [], "actions": actions,
                    "requires_confirmation": True
                })
            else:
                # Still no actions - create default actions based on user input
                default_actions = []
                user_lower = user_message.lower()
                
                if "square" in user_lower or "rectangle" in user_lower:
                    default_actions = [
                        {"action": "create_sketch", "params": {"plane": "XY"}},
                        {"action": "add_rectangle", "params": {"sketch_id": "sk_0", "x1": -1, "y1": -1, "x2": 1, "y2": 1}}
                    ]
                elif "circle" in user_lower:
                    default_actions = [
                        {"action": "create_sketch", "params": {"plane": "XY"}},
                        {"action": "add_circle", "params": {"sketch_id": "sk_0", "cx": 0, "cy": 0, "r": 1}}
                    ]
                
                if default_actions:
                    actions = default_actions
                    _state.last_actions = actions
                    send_to_html({
                        "status": "ready_to_execute",
                        "assistant_message": "Using default actions based on your request. Executing now.",
                        "questions": [], "plan": [], "actions": actions,
                        "requires_confirmation": True
                    })
                else:
                    # Still no actions - ask for clarification
                    send_to_html({
                        "status": "need_clarification",
                        "assistant_message": "I couldn't generate actions. Please be more specific about what you want to create.",
                        "questions": [
                            "What shape do you want to create (square, circle, rectangle)?",
                            "What size (e.g., 2cm, 20mm)?",
                            "Which plane (XY, YZ, XZ)?"
                        ],
                        "plan": [], "actions": [], "requires_confirmation": False
                    })
                    return
        
        # Execute actions
        try:
            executor = FusionActionExecutor()
            success, details = executor.execute_actions(actions)
        except Exception as e:
            success, details = False, f"Failed to create executor: {e}"
        
        # Report execution result
        result_msg = json.dumps({"ok": success, "details": details})
        final_reply = AgentCommunicator.call_agent("execution_result", result_msg)
        send_to_html(final_reply)

# ============================================================
# Utility Functions
# ============================================================

def send_to_html(payload: dict):
    """Send data to HTML palette"""
    try:
        ui = adsk.core.Application.get().userInterface
        pal = ui.palettes.itemById(PALETTE_ID)
        if pal:
            pal.sendInfoToHTML('agent_reply', json.dumps(payload))
    except:
        # Swallow errors to prevent UI crashes
        pass

# ============================================================
# Add-in Entry Points
# ============================================================

def run(context):
    """Add-in startup function"""
    try:
        # Debug output
        if DEBUG:
            ui = adsk.core.Application.get().userInterface
            ui.messageBox("PASCAL Agent Add-in starting...", "Debug Info")
        
        # Basic validation - only check for critical files
        critical_errors = []
        if not HTML_FILE.exists():
            critical_errors.append(f"HTML file not found: {HTML_FILE}")
        if not Path(AGENT_SCRIPT).exists():
            critical_errors.append(f"Agent script not found: {AGENT_SCRIPT}")
        
        if critical_errors:
            ui = adsk.core.Application.get().userInterface
            error_msg = "Critical errors:\n" + "\n".join(critical_errors)
            ui.messageBox(error_msg, "PASCAL Agent - Critical Errors")
            return
        
        # Set up UI - simplified version
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface
            
            # Create command definition
            cmd_def = ui.commandDefinitions.itemById(CMD_ID)
            if not cmd_def:
                cmd_def = ui.commandDefinitions.addButtonDefinition(
                    CMD_ID, CMD_NAME, CMD_DESC
                )
            
            # Add command created handler
            on_created = CommandCreatedHandler()
            cmd_def.commandCreated.add(on_created)
            _state.handlers.append(on_created)
            
            # Try to add to any available panel
            try:
                # Try multiple workspaces
                workspaces_to_try = ['FusionDesignEnvironment', 'FusionSolidEnvironment', 'FusionModelEnvironment']
                ws = None
                for ws_id in workspaces_to_try:
                    ws = ui.workspaces.itemById(ws_id)
                    if ws:
                        if DEBUG:
                            ui.messageBox(f"Found workspace: {ws_id}", "Debug Info")
                        break
                
                if ws:
                    # Try multiple panels
                    panels_to_try = ['SolidCreatePanel', 'SolidModifyPanel', 'SolidInspectPanel']
                    for panel_name in panels_to_try:
                        try:
                            panel = ws.toolbarPanels.itemById(panel_name)
                            if panel:
                                panel.controls.addCommand(cmd_def)
                                if DEBUG:
                                    ui.messageBox(f"Successfully added to {panel_name}", "Debug Info")
                                break
                        except:
                            continue
                else:
                    if DEBUG:
                        ui.messageBox("No workspaces found", "Debug Info")
            except Exception as e:
                if DEBUG:
                    ui.messageBox(f"Error adding to panel: {e}", "Debug Info")
            
            # Debug output for successful startup
            if DEBUG:
                ui.messageBox("PASCAL Agent Add-in loaded successfully!", "Debug Info")
                
        except Exception as e:
            ui = adsk.core.Application.get().userInterface
            ui.messageBox(f"Error setting up UI: {e}", "Debug Info")
            raise
        
    except Exception as e:
        try:
            ui = adsk.core.Application.get().userInterface
            ui.messageBox(f'Add-In startup failed:\n{traceback.format_exc()}')
        except:
            # If we can't even show an error message, just pass
            pass

def stop(context):
    """Add-in shutdown function"""
    try:
        fusion_ui = FusionUI()
        fusion_ui.cleanup_command()
    except Exception as e:
        ui = adsk.core.Application.get().userInterface
        ui.messageBox(f'Add-In shutdown failed:\n{traceback.format_exc()}')
