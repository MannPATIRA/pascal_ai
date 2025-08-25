"""
Agent Runner for PASCAL Fusion Add-in
Handles LLM communication and conversation management
"""

import os
import sys
import json
import pathlib
import traceback
import re
import time
from typing import List, Literal, Dict, Any, Optional
from pydantic import BaseModel, ValidationError, ConfigDict, Field
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================
# Configuration
# ============================================================

ROOT = pathlib.Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

# LLM Configuration
OPENAI_MODEL = "gpt-4o"
MAX_TRIES = 3
RETRY_SLEEP_S = 0.5

# ============================================================
# Data Models
# ============================================================

StatusT = Literal["need_clarification", "planned", "ready_to_execute", "executing", "done"]

class Action(BaseModel):
    """Represents a single Fusion action to execute"""
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "create_sketch",
        "add_rectangle", 
        "add_circle",
        "extrude_last_profile",
        "add_text"
    ]
    params: Dict[str, Any]

class AgentReply(BaseModel):
    """Response from the LLM agent"""
    model_config = ConfigDict(extra="forbid")
    status: StatusT
    assistant_message: str = ""
    questions: List[str] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    requires_confirmation: bool = False

# ============================================================
# Prompts and System Messages
# ============================================================

SYSTEM_PROMPT = """
You are PASCAL Agent, a Fusion CAD assistant.

WORKFLOW:
1. CLARIFY: If request is ambiguous, ask specific questions
   - status: "need_clarification"
   - questions: array of specific questions
   - assistant_message: brief summary

2. PLAN & ACTIONS: Once clear, create numbered steps AND executable actions
   - status: "ready_to_execute"
   - plan: numbered steps with 1-line rationale each
   - actions: executable Fusion actions (REQUIRED)
   - requires_confirmation: true
   - assistant_message: plan summary

3. EXECUTE: Wait for user confirmation, then execute
   - status: "executing" (during execution)
   - status: "done" (after execution result)

CRITICAL: You MUST generate actions[] when the request is clear. Do not stop at planning.

ALLOWED ACTIONS:
- create_sketch(plane: 'XY'|'YZ'|'XZ')
- add_rectangle(sketch_id: string, x1:number, y1:number, x2:number, y2:number)
- add_circle(sketch_id: string, cx:number, cy:number, r:number)
- extrude_last_profile(distance:number, operation:'NewBody'|'Cut'|'Join')
- add_text(plane:'XY'|'YZ'|'XZ', text:string, height:number, x:number, y:number)

UNITS & CONVENTIONS:
- Use centimeters for all distances
- Sketch IDs: "sk_0", "sk_1", ... in creation order
- Default position: (0,0) origin when not specified
- For squares: if user says "20 mm sides", use x1=-1, y1=-1, x2=1, y2=1 (2cm square)
- For extrude: distance should be in cm (e.g., 30mm = 3cm)

EXTRUDE NOTES:
- Always use "NewBody" operation unless specifically cutting or joining
- The profile must be from a closed sketch (rectangle, circle, etc.)
- Distance must be positive and in centimeters

OUTPUT FORMAT:
Return ONLY a JSON object with keys:
status, assistant_message, questions (if any), plan (if any),
actions (if any), requires_confirmation (if any)

EXAMPLES:
For "20 mm sides in XY plane":
{
  "status": "ready_to_execute",
  "assistant_message": "I will create a 2cm square centered at origin on XY plane.",
  "plan": ["1. Create sketch on XY plane", "2. Add 2cm square centered at origin"],
  "actions": [
    {"action": "create_sketch", "params": {"plane": "XY"}},
    {"action": "add_rectangle", "params": {"sketch_id": "sk_0", "x1": -1, "y1": -1, "x2": 1, "y2": 1}}
  ],
  "requires_confirmation": true
}
"""

# ============================================================
# State Management
# ============================================================

class StateManager:
    """Manages conversation state and persistence"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state_path = STATE_DIR / f"{session_id}.json"
    
    def load(self) -> dict:
        """Load conversation state from file"""
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"session_id": self.session_id, "history": []}
    
    def save(self, data: dict):
        """Save conversation state to file"""
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), 
            encoding="utf-8"
        )
    
    def add_turn(self, role: str, content: str):
        """Add a conversation turn to history"""
        state = self.load()
        state["history"].append({"role": role, "content": content})
        self.save(state)
    
    def get_recent_history(self, max_turns: int = 8) -> List[dict]:
        """Get recent conversation history"""
        state = self.load()
        return state.get("history", [])[-max_turns:]

# ============================================================
# LLM Communication
# ============================================================

class LLMClient:
    """Handles communication with OpenAI API"""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")
        self.client = OpenAI(api_key=api_key)
    
    def _build_messages(self, history: List[dict], event: str, user_message: str) -> List[dict]:
        """Build message list for OpenAI API"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        
        # Add conversation history
        for turn in history:
            if isinstance(turn, dict) and "role" in turn and "content" in turn:
                messages.append(turn)
        
        # Add current event
        if event == "user_message":
            messages.append({"role": "user", "content": user_message})
        elif event == "confirm_execute":
            messages.append({"role": "user", "content": "User confirms: proceed with execution"})
        elif event == "execution_result":
            messages.append({"role": "user", "content": f"Execution result: {user_message}"})
        elif event == "force_actions":
            messages.append({
                "role": "user", 
                "content": "Convert the plan into actions now. Return JSON with status='ready_to_execute'"
            })
        
        return messages
    
    def _parse_and_validate_response(self, content: str) -> AgentReply:
        """Parse and validate LLM response"""
        # Extract JSON from response
        json_text = self._extract_json(content)
        
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        
        # Normalize and validate
        parsed = self._normalize_response(parsed)
        
        try:
            return AgentReply.model_validate(parsed)
        except ValidationError as e:
            raise ValueError(f"Validation error: {e}")
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON object from text"""
        # Remove code fences
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), 
                     flags=re.IGNORECASE|re.DOTALL)
        
        # Find first balanced {...} block
        start = text.find('{')
        if start == -1:
            return text
        
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
        
        return text
    
    def _normalize_response(self, data: dict) -> dict:
        """Normalize response data for validation"""
        normalized = {
            "status": data.get("status", "need_clarification"),
            "assistant_message": data.get("assistant_message", ""),
            "questions": self._normalize_list(data.get("questions")),
            "plan": self._normalize_list(data.get("plan")),
            "actions": self._normalize_actions(data.get("actions")),
            "requires_confirmation": bool(data.get("requires_confirmation", False))
        }
        
        # Validate status
        valid_statuses = {"need_clarification", "planned", "ready_to_execute", "executing", "done"}
        if normalized["status"] not in valid_statuses:
            normalized["status"] = "need_clarification"
        
        return normalized
    
    def _normalize_list(self, value) -> List[str]:
        """Normalize list fields"""
        if isinstance(value, str):
            return [s.strip() for s in re.split(r"[\r\n]+", value) if s.strip()]
        elif isinstance(value, list):
            return [str(item).strip() for item in value if item]
        return []
    
    def _normalize_actions(self, value) -> List[dict]:
        """Normalize actions field"""
        if isinstance(value, list):
            return [action for action in value if isinstance(action, dict) and "action" in action]
        return []
    
    def call_with_retries(self, messages: List[dict]) -> AgentReply:
        """Call LLM with retry logic"""
        last_error = None
        
        for attempt in range(MAX_TRIES):
            try:
                # Add correction message if retrying
                if attempt > 0:
                    messages.append({
                        "role": "system",
                        "content": "Your previous response was invalid. Return ONLY a valid JSON object."
                    })
                
                response = self.client.chat.completions.create(
                    model=OPENAI_MODEL,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=messages
                )
                
                content = response.choices[0].message.content or ""
                return self._parse_and_validate_response(content)
                
            except Exception as e:
                last_error = e
                if attempt < MAX_TRIES - 1:
                    time.sleep(RETRY_SLEEP_S)
        
        # Return fallback response after all retries
        return AgentReply(
            status="need_clarification",
            assistant_message="I had trouble processing your request. Please restate with specific details.",
            questions=[
                "What exact sizes (with units)?",
                "Which plane (XY, YZ, XZ)?", 
                "Where should it be positioned?"
            ]
        )

# ============================================================
# Conversation Handler
# ============================================================

class ConversationHandler:
    """Handles the conversation flow and state transitions"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state_manager = StateManager(session_id)
        self.llm_client = LLMClient()
    
    def _is_confirmation(self, text: str) -> bool:
        """Check if user text is a confirmation"""
        text = text.strip().lower()
        confirmations = {
            "yes", "y", "ok", "okay", "sure", "proceed", "confirm", 
            "go ahead", "looks good", "sounds good", "do it"
        }
        return text in confirmations or text.startswith("yes") or text.startswith("ok")
    
    def _ensure_confirmation_question(self, reply: AgentReply) -> AgentReply:
        """Add confirmation question to planned responses"""
        if reply.status == "planned":
            # If we only have a plan but no actions, force action generation
            if not reply.actions:
                reply.status = "ready_to_execute"
                reply.requires_confirmation = True
                # Try to generate actions from the plan
                if reply.plan:
                    # Simple action generation based on plan
                    actions = []
                    for i, step in enumerate(reply.plan):
                        if "sketch" in step.lower() and "xy" in step.lower():
                            actions.append({"action": "create_sketch", "params": {"plane": "XY"}})
                        elif "rectangle" in step.lower() or "square" in step.lower():
                            actions.append({"action": "add_rectangle", "params": {"sketch_id": "sk_0", "x1": -1, "y1": -1, "x2": 1, "y2": 1}})
                        elif "circle" in step.lower():
                            actions.append({"action": "add_circle", "params": {"sketch_id": "sk_0", "cx": 0, "cy": 0, "r": 1}})
                        elif "extrude" in step.lower():
                            actions.append({"action": "extrude_last_profile", "params": {"distance": 1, "operation": "NewBody"}})
                    reply.actions = actions
            else:
                confirm_q = "Are you happy with this plan? Reply 'yes' to proceed to execution."
                if confirm_q not in reply.questions:
                    reply.questions.append(confirm_q)
        return reply
    
    def _handle_plan_confirmation(self, user_message: str, last_status: str) -> bool:
        """Check if user is confirming a plan"""
        return (self._is_confirmation(user_message) and last_status == "planned")
    
    def _force_action_generation(self, messages: List[dict]) -> AgentReply:
        """Force the LLM to generate actions from plan"""
        messages.append({
            "role": "user",
            "content": (
                "Convert the plan into actions now. Use defaults if needed: "
                "plane=XY, position=(0,0), units=cm. "
                "Return JSON with status='ready_to_execute', actions[], requires_confirmation=true."
            )
        })
        return self.llm_client.call_with_retries(messages)
    
    def process_event(self, event: str, user_message: str) -> AgentReply:
        """Process a conversation event and return response"""
        # Load state
        state = self.state_manager.load()
        last_status = state.get("last_status")
        
        # Build messages
        history = self.state_manager.get_recent_history()
        messages = self.llm_client._build_messages(history, event, user_message)
        
        # Handle plan confirmation
        if self._handle_plan_confirmation(user_message, last_status):
            messages.append({
                "role": "user",
                "content": "User approves the plan. Convert to actions now."
            })
        
        # Get LLM response
        reply = self.llm_client.call_with_retries(messages)
        
        # Handle plan confirmation edge cases
        if (self._handle_plan_confirmation(user_message, last_status) and 
            reply.status != "ready_to_execute"):
            reply = self._force_action_generation(messages)
        
        # Add confirmation question if needed
        reply = self._ensure_confirmation_question(reply)
        
        # State gating - prevent invalid status transitions
        if event != "execution_result" and reply.status == "done":
            if reply.actions:
                reply.status = "ready_to_execute"
                reply.requires_confirmation = True
            else:
                reply.status = "planned"
        
        # Ensure confirmation is required for ready state
        if reply.status == "ready_to_execute":
            reply.requires_confirmation = True
        
        # Save state
        state["last_status"] = reply.status
        if reply.actions:
            state["last_actions"] = [action.model_dump() for action in reply.actions]
        
        self.state_manager.add_turn("user", user_message)
        self.state_manager.add_turn("assistant", json.dumps(reply.model_dump()))
        
        return reply

# ============================================================
# Main Entry Point
# ============================================================

def main():
    """Main entry point for the agent runner"""
    try:
        # Parse command line arguments
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: agent_runner.py <session_id> <json_payload | ->"}))
            sys.exit(2)
        
        session_id = sys.argv[1]
        raw_payload = sys.argv[2]
        
        # Parse payload
        try:
            if raw_payload == "-":
                payload = json.loads(sys.stdin.read())
            elif raw_payload.endswith(".json") and pathlib.Path(raw_payload).exists():
                payload = json.loads(pathlib.Path(raw_payload).read_text())
            else:
                payload = json.loads(raw_payload)
        except Exception as e:
            print(json.dumps({
                "status": "need_clarification",
                "assistant_message": f"Could not parse payload: {e}",
                "questions": [], "plan": [], "actions": [], "requires_confirmation": False
            }))
            sys.exit(3)
        
        # Process event
        event = payload.get("event", "user_message")
        user_message = payload.get("user_message", "").strip()
        
        handler = ConversationHandler(session_id)
        reply = handler.process_event(event, user_message)
        
        # Output response
        print(json.dumps(reply.model_dump(), ensure_ascii=False))
        
    except Exception as e:
        print(json.dumps({
            "status": "need_clarification",
            "assistant_message": f"Agent error: {e}",
            "questions": [], "plan": [], "actions": [], "requires_confirmation": False
        }))

if __name__ == "__main__":
    main()
