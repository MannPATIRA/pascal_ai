# D:\Desktop\Pascal_Addins\AgentAddIn1\external\test_runner.py
import os, json
from typing import List, Literal, Dict, Any
from pydantic import BaseModel, ValidationError, ConfigDict, Field
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ------------------ Pydantic schema (strict & safe) ------------------

StatusT = Literal["need_clarification", "planned", "ready_to_execute", "executing", "done"]

class Action(BaseModel):
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
    model_config = ConfigDict(extra="forbid")
    status: StatusT
    assistant_message: str = ""                         # default if model omits
    questions: List[str] = Field(default_factory=list)  # defaults
    plan: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    requires_confirmation: bool = False

# ------------------ System instructions ------------------

SYSTEM_ROLE = """
You are PASCAL Agent, a Fusion CAD assistant.

PIPELINE (and required keys):
1) If the request is ambiguous, ask short clarifying questions ONLY.
   Output:
     - status: "need_clarification"
     - questions: an array with >=1 specific, single-sentence questions
     - assistant_message: a one-sentence summary (not a question)
2) Once clear, output an ordered plan with brief rationale.
   Output:
     - status: "planned"
     - plan: numbered steps with 1-line rationale each
     - assistant_message: short summary of the plan
3) Convert the plan to allowed actions.
   Output:
     - status: "ready_to_execute"
     - actions: only from the allowed set below
     - requires_confirmation: true
     - assistant_message: short summary
4) Wait for confirmation (you never execute actions).
5) After host executes and reports back:
   Output:
     - status: "done"
     - assistant_message: short summary of what was executed

ALLOWED ACTIONS (exact names & params):
- create_sketch(plane: 'XY'|'YZ'|'XZ')
- add_rectangle(sketch_id: string, x1:number, y1:number, x2:number, y2:number)
- add_circle(sketch_id: string, cx:number, cy:number, r:number)
- extrude_last_profile(distance:number, operation:'NewBody'|'Cut'|'Join')
- add_text(plane:'XY'|'YZ'|'XZ', text:string, height:number, x:number, y:number)

UNITS: centimeters for sketch coordinates, text height, and extrude distance.
STRICT OUTPUT: Return ONE JSON object only with keys:
status, assistant_message, questions (if any), plan (if any), actions (if any), requires_confirmation (if any).
No prose outside JSON.
"""

USER_GUIDE = """
Ask clarifying questions until confident (put them in questions[]; do NOT put questions in assistant_message).
When planning: number steps and add one line of rationale each.
Actions must be minimal, consistent with the plan and units.
"""

# ------------------ Few-shot nudge for the model ------------------

EXAMPLE_NEED_CLARIFY = {
  "role": "system",
  "content": """FORMAT EXAMPLE (do not copy text; match structure):
{
  "status": "need_clarification",
  "assistant_message": "I need two details to proceed.",
  "questions": [
    "Should 2 cm refer to side length (2×2 cm) or 2 cm² area?",
    "Where should the square be positioned on the XY plane (e.g., centered at origin or specific coordinates)?"
  ],
  "plan": [],
  "actions": [],
  "requires_confirmation": false
}
"""}

# ------------------ Hardcoded test payload ------------------

payload = {
    "event": "user_message",
    "user_message": "make a 2 cm square on XY and extrude 1 cm"
}
# To test other phases:
# payload = {"event": "confirm_execute", "user_message": "OK to proceed"}
# payload = {"event": "execution_result", "user_message": '{"ok": true, "details": "simulated"}'}

# ------------------ Helpers ------------------

def coerce_defaults(d: dict) -> dict:
    d = dict(d)
    d.setdefault("assistant_message", "")
    d.setdefault("questions", [])
    d.setdefault("plan", [])
    d.setdefault("actions", [])
    d.setdefault("requires_confirmation", False)
    return d

def postprocess_reply(reply: AgentReply, user_text: str) -> AgentReply:
    """
    Fallbacks if the model forgets questions[] when status=need_clarification.
    - If assistant_message looks like a question, move it into questions[].
    - Otherwise create at least one sensible question from the request.
    """
    if reply.status == "need_clarification" and not reply.questions:
        # If assistant_message ends with a '?', treat it as a question
        am = (reply.assistant_message or "").strip()
        qs: List[str] = []
        if am.endswith("?"):
            qs.append(am)
            reply.assistant_message = "I need a detail to proceed."
        else:
            # Heuristics for common geometry clarifications
            t = user_text.lower()
            if "square" in t and "cm" in t:
                qs.append("Should 2 cm refer to side length (2×2 cm) or 2 cm² area?")
            qs.append("Where should the shape be positioned on the XY plane (e.g., centered at origin or specific coordinates)?")
        reply.questions = qs
    return reply

def call_model(messages) -> AgentReply:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    client = OpenAI(api_key=api_key)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",           # use a chat-completions model available to your account
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=messages
    )
    content = resp.choices[0].message.content  # JSON string

    try:
        raw = json.loads(content)
    except Exception as e:
        raise RuntimeError(f"Model did not return JSON: {e}\nRaw:\n{content}")

    raw = coerce_defaults(raw)

    try:
        parsed = AgentReply.model_validate(raw)
    except ValidationError as ve:
        raise RuntimeError(
            "Model returned JSON that failed validation.\n"
            f"Raw JSON:\n{json.dumps(raw, indent=2)}\n\nErrors:\n{ve}"
        )
    return parsed

# ------------------ Main ------------------

def main():
    messages = [
        {"role": "system", "content": SYSTEM_ROLE},
        {"role": "system", "content": USER_GUIDE},
        EXAMPLE_NEED_CLARIFY
    ]

    event = payload.get("event")
    if event == "user_message":
        messages.append({"role": "user", "content": payload.get("user_message", "").strip()})
    elif event == "confirm_execute":
        messages.append({"role": "user", "content": "User confirms: proceed with execution of proposed actions."})
    elif event == "execution_result":
        messages.append({"role": "user", "content": f"Execution result from Fusion host: {payload.get('user_message','')}"})
    else:
        messages.append({"role": "user", "content": payload.get("user_message", "").strip()})

    reply = call_model(messages)
    # Post-process to ensure questions[] isn’t empty when needed
    reply = postprocess_reply(reply, payload.get("user_message",""))
    print(json.dumps(reply.model_dump(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
