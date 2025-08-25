# Configuration for AgentAddIn1
# Centralized settings for the Fusion Add-in

import os
import pathlib
from pathlib import Path

# ============================================================
# Add-in Configuration
# ============================================================

# Debug mode - set to False for production
DEBUG = False

# Add-in identification
ADDIN_NAME = os.path.basename(os.path.dirname(__file__))
COMPANY_NAME = 'PASCAL'

# UI Configuration
WORKSPACE_ID = 'FusionDesignEnvironment'
PANEL_ID = 'SolidCreatePanel'
CMD_ID = 'pascal_agent_cmd'
CMD_NAME = 'PASCAL Agent'
CMD_DESC = 'Chat, clarify, plan, and execute CAD steps safely.'
PALETTE_ID = 'pascal_agent_palette'

# Palette dimensions
PALETTE_WIDTH = 460
PALETTE_HEIGHT = 600

# ============================================================
# External Agent Configuration
# ============================================================

# Paths (relative to add-in root)
HERE = Path(__file__).resolve().parent
EXTERNAL_DIR = HERE / 'external'
HTML_FILE = HERE / 'palette.html'

# Python environment - try multiple possible paths
PYTHON_EXE = None
AGENT_SCRIPT = str(EXTERNAL_DIR / 'agent_runner.py')

# Try to find Python executable
possible_python_paths = [
    str(EXTERNAL_DIR / 'external_venv' / 'Scripts' / 'pythonw.exe'),
    str(EXTERNAL_DIR / 'external_venv' / 'Scripts' / 'python.exe'),
    'pythonw.exe',  # Fallback to system Python
    'python.exe'    # Fallback to system Python
]

for path in possible_python_paths:
    if Path(path).exists():
        PYTHON_EXE = path
        break

# If no Python found, use a default
if not PYTHON_EXE:
    PYTHON_EXE = 'pythonw.exe'

# LLM Configuration
OPENAI_MODEL = "gpt-4o"
MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 0.5
REQUEST_TIMEOUT = 180

# ============================================================
# State Management
# ============================================================

STATE_DIR = EXTERNAL_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)

# ============================================================
# Validation
# ============================================================

def validate_config():
    """Validate that all required files and paths exist"""
    errors = []
    warnings = []
    
    # Critical files that must exist
    if not HTML_FILE.exists():
        errors.append(f"HTML file not found: {HTML_FILE}")
    
    if not Path(AGENT_SCRIPT).exists():
        errors.append(f"Agent script not found: {AGENT_SCRIPT}")
    
    # Non-critical warnings
    if not Path(PYTHON_EXE).exists():
        warnings.append(f"Python executable not found: {PYTHON_EXE}")
    
    if not os.getenv("OPENAI_API_KEY"):
        warnings.append("OPENAI_API_KEY environment variable not set")
    
    return errors, warnings