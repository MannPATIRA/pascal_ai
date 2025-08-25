# PASCAL Agent Add-in for Fusion 360

A natural language CAD creation add-in for Autodesk Fusion 360 that uses LLM-powered conversation to create geometry through a structured workflow.

## Overview

The PASCAL Agent Add-in allows users to describe what they want to create in natural language. The system then:

1. **Clarifies** ambiguous requests by asking specific questions
2. **Plans** the creation steps with rationale
3. **Generates** executable Fusion 360 actions
4. **Executes** the actions safely in Fusion 360
5. **Reports** back the results

## Architecture

### Core Components

```
AgentAddIn1/
├── AgentAddIn1.py          # Main Fusion add-in entry point
├── config.py               # Centralized configuration
├── palette.html            # User interface
├── external/
│   ├── agent_runner.py     # LLM processing engine
│   ├── external_requirements.txt
│   └── state/              # Conversation state storage
└── commands/               # Additional Fusion commands (unused)
```

### Key Classes

#### Fusion Side (`AgentAddIn1.py`)
- **`AddinState`**: Manages global state (session ID, last actions, etc.)
- **`FusionUI`**: Handles Fusion 360 UI setup and management
- **`AgentCommunicator`**: Communicates with external agent process
- **`FusionActionExecutor`**: Executes Fusion 360 API calls

#### Agent Side (`agent_runner.py`)
- **`StateManager`**: Manages conversation state persistence
- **`LLMClient`**: Handles OpenAI API communication
- **`ConversationHandler`**: Orchestrates conversation flow

## Workflow

### 1. User Input
User types natural language request in HTML palette:
```
"Create a 2cm square on the XY plane and extrude it 1cm"
```

### 2. Clarification Phase
If request is ambiguous, agent asks specific questions:
```
Status: need_clarification
Questions:
- Should 2cm refer to side length or area?
- Where should the square be positioned?
```

### 3. Planning Phase
Agent creates numbered plan with rationale:
```
Status: planned
Plan:
1. Create sketch on XY plane
2. Add 2cm x 2cm rectangle at origin
3. Extrude rectangle 1cm to create solid
```

### 4. Action Generation
Agent converts plan to executable Fusion actions:
```
Status: ready_to_execute
Actions:
- create_sketch(plane: "XY")
- add_rectangle(sketch_id: "sk_0", x1: -1, y1: -1, x2: 1, y2: 1)
- extrude_last_profile(distance: 1, operation: "NewBody")
```

### 5. Execution
User confirms, system executes actions in Fusion 360 and reports results.

## Configuration

### Required Setup

1. **Environment Variables**:
   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   ```

2. **Python Environment**:
   - Create virtual environment in `external/external_venv/`
   - Install requirements from `external/external_requirements.txt`

3. **File Paths**:
   - Update paths in `config.py` if needed
   - Ensure `palette.html` exists in add-in root

### Configuration Validation

The add-in validates configuration on startup:
- Checks for required files
- Validates Python executable path
- Confirms OpenAI API key is set

## Supported Actions

The agent can execute these Fusion 360 actions:

### Sketch Operations
- `create_sketch(plane: "XY"|"YZ"|"XZ")`
- `add_rectangle(sketch_id: string, x1: number, y1: number, x2: number, y2: number)`
- `add_circle(sketch_id: string, cx: number, cy: number, r: number)`
- `add_text(plane: "XY"|"YZ"|"XZ", text: string, height: number, x: number, y: number)`

### Feature Operations
- `extrude_last_profile(distance: number, operation: "NewBody"|"Cut"|"Join")`

## Installation

1. **Clone/Download** the add-in to Fusion 360's add-ins directory
2. **Set Environment Variable**:
   ```bash
   set OPENAI_API_KEY=your_key_here
   ```
3. **Install Dependencies**:
   ```bash
   cd AgentAddIn1/external
   python -m venv external_venv
   external_venv\Scripts\activate
   pip install -r external_requirements.txt
   ```
4. **Load in Fusion 360**:
   - Open Fusion 360
   - Go to Design → Add-Ins → Scripts and Add-Ins
   - Browse to add-in folder and select `AgentAddIn1.py`

## Usage

1. **Start the Add-in**: Click the "PASCAL Agent" button in the Solid Create panel
2. **Chat Interface**: A palette opens with a chat interface
3. **Describe Your Request**: Type what you want to create in natural language
4. **Answer Questions**: Respond to any clarification questions
5. **Review Plan**: Check the generated plan and actions
6. **Execute**: Click "Proceed & Execute" to create the geometry

## Error Handling

The system includes comprehensive error handling:

- **LLM Communication**: Retry logic with fallback responses
- **Fusion API**: Graceful handling of API failures
- **State Management**: Robust conversation state persistence
- **UI Errors**: Non-crashing error display in chat interface

## Development

### Code Organization

The refactored code follows these principles:

- **Separation of Concerns**: Each class has a single responsibility
- **Configuration Centralization**: All settings in `config.py`
- **Error Handling**: Comprehensive error handling at each layer
- **Documentation**: Clear docstrings and comments
- **Type Hints**: Python type annotations for better code clarity

### Adding New Actions

To add new Fusion 360 actions:

1. **Update Data Models** in `agent_runner.py`:
   ```python
   class Action(BaseModel):
       action: Literal[
           "create_sketch",
           "add_rectangle",
           "add_circle",
           "extrude_last_profile",
           "add_text",
           "your_new_action"  # Add here
       ]
   ```

2. **Update System Prompt** in `agent_runner.py`:
   ```python
   ALLOWED ACTIONS:
   - your_new_action(param1: type, param2: type)
   ```

3. **Implement Execution** in `FusionActionExecutor`:
   ```python
   def _your_new_action(self, params: dict) -> bool:
       # Implementation here
       return True
   ```

4. **Add to Execution Loop** in `execute_actions()`:
   ```python
   elif action_name == "your_new_action":
       success = self._your_new_action(params)
   ```

## Troubleshooting

### Common Issues

1. **"Python executable not found"**:
   - Check path in `config.py`
   - Ensure virtual environment is created

2. **"OPENAI_API_KEY not set"**:
   - Set environment variable
   - Restart Fusion 360

3. **"Agent returned code 1"**:
   - Check Python dependencies are installed
   - Verify virtual environment activation

4. **"No active Fusion design"**:
   - Create or open a design in Fusion 360
   - Ensure you're in the Design workspace

### Debug Mode

Set `DEBUG = True` in `config.py` for additional logging and error information.

## License

This project is provided as-is for educational and development purposes.

## Contributing

When contributing to this project:

1. Follow the existing code organization patterns
2. Add comprehensive error handling
3. Update documentation for new features
4. Test thoroughly in Fusion 360 environment
