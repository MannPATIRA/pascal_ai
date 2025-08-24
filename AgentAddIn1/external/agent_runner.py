import os, sys, json, pathlib, traceback, re, time
from typing import List, Literal, Dict, Any
from pydantic import BaseModel, ValidationError, ConfigDict, Field
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# Config / State
# ============================================================

ROOT = pathlib.Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

DEV_MODE = False                   # set True only when running manually
DEV_SESSION_ID = "dev_session"
OPENAI_MODEL = "gpt-4o-mini"       # any chat-completions model you have
MAX_TRIES = 3                      # LLM retry attempts on bad format
RETRY_SLEEP_S = 0.5                # short backoff between retries

# ============================================================
# Pydantic reply schema (strict & safe)
# ============================================================

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
    assistant_message: str = ""
    questions: List[str] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    requires_confirmation: bool = False

# ============================================================
# Prompting
# ============================================================

SYSTEM_ROLE = """
You are PASCAL Agent, a Fusion CAD assistant.

PIPELINE (and required keys):
1) If the request is ambiguous, ask short clarifying questions ONLY.
   Output JSON:
     - status: "need_clarification"
     - questions: array with >=1 specific question strings
     - assistant_message: one-sentence summary (not a question)
2) Once clear, output an ordered plan with brief rationale.
   Output JSON:
     - status: "planned"
     - plan: numbered steps with 1-line rationale each
     - assistant_message: short summary of the plan
3) Convert the plan to allowed actions (below).
   Output JSON:
     - status: "ready_to_execute"
     - actions: only from the allowed set
     - requires_confirmation: true
     - assistant_message: short summary
4) Wait for confirmation (you never execute actions).
5) After host executes and reports back:
   Output JSON:
     - status: "done"
     - assistant_message: short summary of what was executed

ALLOWED ACTIONS (exact names & params):
- create_sketch(plane: 'XY'|'YZ'|'XZ')
- add_rectangle(sketch_id: string, x1:number, y1:number, x2:number, y2:number)
- add_circle(sketch_id: string, cx:number, cy:number, r:number)
- extrude_last_profile(distance:number, operation:'NewBody'|'Cut'|'Join')
- add_text(plane:'XY'|'YZ'|'XZ', text:string, height:number, x:number, y:number)

UNITS & NAMING:
- Use centimeters for all distances & sketch coordinates.
- Sketch IDs you propose must be "sk_0", "sk_1", ... in creation order.
- Use (0,0) origin when user gives no position and say so in plan.

STRICT OUTPUT:
Return ONE JSON object only, with keys:
status, assistant_message, questions (if any), plan (if any),
actions (if any), requires_confirmation (if any).
NO prose outside JSON. NO code fences. NO markdown.

STRICT STATE GATING:
- You NEVER claim geometry was created/extruded unless the host sent an "execution_result".
- For "user_message" / "confirm_execute" you only ask, plan, or propose actions.
- "done" is ONLY allowed when the last event was "execution_result".
"""

USER_GUIDE = """
Ask clarifying questions until confident (put them in questions[]; do NOT put questions in assistant_message).
When planning: number steps and add one line of rationale each.
Actions must match the plan and units precisely.
"""

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

# ============================================================
# Helpers: state, JSON repair/normalization
# ============================================================

def _state_path(session_id: str) -> pathlib.Path:
    return STATE_DIR / f"{session_id}.json"

def load_state(session_id: str):
    p = _state_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"session_id": session_id, "history": []}

def save_state(session_id: str, data: dict):
    _state_path(session_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def strip_code_fences(text: str) -> str:
    if not text:
        return text
    # remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE|re.DOTALL)
    return text.strip()

def extract_json_object(text: str) -> str:
    """
    Try to extract the first balanced {...} block from text.
    """
    s = strip_code_fences(text)
    start = s.find('{')
    if start == -1:
        return s  # let it fail later
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return s[start:i+1]
    return s  # fallback; may still be invalid

def coerce_defaults(d: dict) -> dict:
    d = dict(d)
    d.setdefault("assistant_message", "")
    d.setdefault("questions", [])
    d.setdefault("plan", [])
    d.setdefault("actions", [])
    d.setdefault("requires_confirmation", False)
    return d

def normalize_types(raw: dict) -> dict:
    """
    Make best-effort coercions so Pydantic can validate.
    - questions: str -> [str] (split lines)
    - plan: str -> [str] (split lines/numbers)
    - actions: str -> try json.loads
    - status: fallback to need_clarification if unknown
    """
    out = dict(raw)

    # status
    if out.get("status") not in {"need_clarification","planned","ready_to_execute","executing","done"}:
        out["status"] = "need_clarification"

    # questions
    q = out.get("questions")
    if isinstance(q, str):
        # split on lines or question marks
        lines = [s.strip() for s in re.split(r"[\r\n]+|(?<=\?)\s+", q) if s.strip()]
        out["questions"] = lines
    elif not isinstance(q, list):
        out["questions"] = []

    # plan
    p = out.get("plan")
    if isinstance(p, str):
        # split numbered list; keep lines
        items = [s.strip(" -\t") for s in re.split(r"[\r\n]+", p) if s.strip()]
        out["plan"] = items
    elif not isinstance(p, list):
        out["plan"] = []

    # actions
    a = out.get("actions")
    if isinstance(a, str):
        try:
            out["actions"] = json.loads(a)
        except Exception:
            out["actions"] = []
    elif not isinstance(a, list):
        out["actions"] = []

    # requires_confirmation
    rc = out.get("requires_confirmation")
    if isinstance(rc, str):
        out["requires_confirmation"] = rc.strip().lower() in {"true","yes","1"}
    elif not isinstance(rc, bool):
        out["requires_confirmation"] = False

    return out

def filter_allowed_actions(raw: dict) -> dict:
    allowed = {"create_sketch","add_rectangle","add_circle","extrude_last_profile","add_text"}
    actions = raw.get("actions", [])
    if isinstance(actions, list):
        filtered = []
        for a in actions:
            if isinstance(a, dict) and a.get("action") in allowed:
                filtered.append(a)
        raw["actions"] = filtered
    else:
        raw["actions"] = []
    return raw

def postprocess_reply(reply: AgentReply, user_text: str) -> AgentReply:
    """
    Ensure questions[] exists when we need clarification; move a question out of assistant_message if needed.
    """
    if reply.status == "need_clarification" and not reply.questions:
        am = (reply.assistant_message or "").strip()
        qs: List[str] = []
        if am.endswith("?"):
            qs.append(am)
            reply.assistant_message = "I need a detail to proceed."
        else:
            t = (user_text or "").lower()
            if "square" in t and ("cm" in t or "mm" in t):
                qs.append("Should the stated size refer to side length (e.g., 2 cm per side) or area?")
            qs.append("Where should the geometry be positioned on the XY plane (e.g., centered at origin or specific coordinates)?")
        reply.questions = qs
    return reply

def is_confirmation_text(t: str) -> bool:
    t = (t or '').strip().lower()
    if not t:
        return False
    # be generous—common confirmations
    confirmations = {
        "yes","y","ok","okay","sure","proceed","confirm","go ahead",
        "looks good","sounds good","do it","yes do it","alright","yep","yeah"
    }
    return t in confirmations or t.startswith("yes") or t.startswith("ok")

CONFIRM_QUESTION = "Are you happy with this plan? Reply 'yes' to proceed to execution, or describe any changes."

# ============================================================
# LLM call with retries / correction
# ============================================================

def ask_model_with_retries(messages) -> AgentReply:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    client = OpenAI(api_key=api_key)

    errors_for_model = None
    content_prev = None

    for attempt in range(1, MAX_TRIES+1):
        # Build attempt-specific messages
        attempt_msgs = list(messages)
        if attempt > 1:
            # Correction turn: tell the model what went wrong and ask for corrected JSON
            fix_block = {
                "role": "system",
                "content": (
                    "Your previous reply did not strictly match the required JSON schema. "
                    "You must return ONLY a single JSON object with the required keys. "
                    "Do not include markdown, code fences, or explanations."
                )
            }
            attempt_msgs.append(fix_block)
            if content_prev:
                attempt_msgs.append({"role":"user","content": f"Previous output:\n{content_prev}"})
            if errors_for_model:
                attempt_msgs.append({"role":"user","content": f"Schema/validation errors:\n{errors_for_model}"})

        # Call model
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=attempt_msgs
        )
        content = resp.choices[0].message.content or ""
        content_prev = content

        # Try to parse/repair/normalize/validate
        try:
            raw_text = extract_json_object(content)
            parsed = json.loads(raw_text)
        except Exception as e:
            errors_for_model = f"JSON parse error: {e}\nRaw: {content[:500]}"
            time.sleep(RETRY_SLEEP_S)
            continue

        parsed = coerce_defaults(parsed)
        parsed = normalize_types(parsed)
        parsed = filter_allowed_actions(parsed)

        try:
            obj = AgentReply.model_validate(parsed)
            return obj
        except ValidationError as ve:
            errors_for_model = str(ve)
            time.sleep(RETRY_SLEEP_S)
            continue

    # After MAX_TRIES, return a safe clarification message instead of crashing
    fallback = {
        "status":"need_clarification",
        "assistant_message": "I had trouble producing a valid plan. Please restate your request with sizes, plane, and position.",
        "questions":[
            "What exact sizes (with units)?",
            "Which plane (XY, YZ, XZ)?",
            "Where should it be positioned (e.g., centered at origin or specific coordinates)?"
        ],
        "plan":[], "actions":[], "requires_confirmation": False
    }
    return AgentReply.model_validate(fallback)

# ============================================================
# Conversation scaffolding / argv
# ============================================================

def build_messages_from_state(state: dict, event: str, user_message: str):
    msgs = [
        {"role": "system", "content": SYSTEM_ROLE},
        {"role": "system", "content": USER_GUIDE},
        EXAMPLE_NEED_CLARIFY
    ]
    for turn in state.get("history", [])[-8:]:
        if isinstance(turn, dict) and "role" in turn and "content" in turn:
            msgs.append(turn)

    if event == "user_message":
        msgs.append({"role":"user","content": user_message})
    elif event == "confirm_execute":
        msgs.append({"role":"user","content":"User confirms: proceed with execution of proposed actions."})
    elif event == "execution_result":
        msgs.append({"role":"user","content": f"Execution result from Fusion host: {user_message}"})
    else:
        msgs.append({"role":"user","content": user_message})
    return msgs

def parse_payload_from_argv():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: agent_runner.py <session_id> <json_payload | ->"}))
        sys.exit(2)
    session_id = sys.argv[1]
    raw = sys.argv[2]
    try:
        if raw == "-":
            payload = json.loads(sys.stdin.read())
        elif raw.endswith(".json") and pathlib.Path(raw).exists():
            payload = json.loads(pathlib.Path(raw).read_text(encoding="utf-8"))
        else:
            payload = json.loads(raw)
    except Exception as e:
        print(json.dumps({
            "status":"need_clarification",
            "assistant_message": f"Could not parse payload: {e}",
            "questions":[], "plan":[], "actions":[], "requires_confirmation": False
        }))
        sys.exit(3)
    return session_id, payload

# ============================================================
# Main
# ============================================================

def main():
    try:
        # -------- Input & session --------
        if DEV_MODE:
            session_id = DEV_SESSION_ID
            payload = {"event": "user_message", "user_message": "make a 2 cm square on XY and extrude 1 cm"}
        else:
            session_id, payload = parse_payload_from_argv()

        event = payload.get("event", "user_message")
        user_message = (payload.get("user_message") or "").strip()

        # -------- State & gating --------
        state = load_state(session_id)
        last_status = state.get("last_status")
        plan_confirmed = (event == "user_message" and is_confirmation_text(user_message) and last_status == "planned")

        # -------- Build messages --------
        messages = build_messages_from_state(state, event, user_message)

        # If the user just approved the plan, force “convert plan → actions”
        if plan_confirmed:
            messages.append({
                "role": "user",
                "content": (
                    "User approves the plan. Convert the previously proposed plan into actions now. "
                    "Return ONLY JSON with status='ready_to_execute', actions[], requires_confirmation=true, "
                    "and a short assistant_message. Do not ask more questions."
                )
            })

        # -------- Ask model (robust: retries/repair inside) --------
        reply: AgentReply = ask_model_with_retries(messages)

        # If still only planned after an approval, force a 2nd pass that MUST produce actions
        if plan_confirmed and (reply.status != "ready_to_execute" or not reply.actions):
            messages2 = list(messages)
            messages2.append({
                "role": "user",
                "content": (
                    "You MUST now output actions[]. If any detail is missing, assume defaults: "
                    "plane=XY, position=(0,0), units=cm (convert mm→cm by /10). "
                    "Return ONLY JSON with status='ready_to_execute', actions[], requires_confirmation=true."
                )
            })
            reply2 = ask_model_with_retries(messages2)
            if reply2.actions:
                reply = reply2

        # In a planned reply, always add a clear confirm question
        if reply.status == "planned":
            qs = list(reply.questions or [])
            if all(q.strip().lower() != CONFIRM_QUESTION.lower() for q in qs):
                qs.append(CONFIRM_QUESTION)
            reply.questions = qs

        # State gating: never claim “done” unless host sent execution_result
        if event != "execution_result" and reply.status == "done":
            if reply.actions:
                reply.status = "ready_to_execute"
                reply.requires_confirmation = True
                if not reply.assistant_message:
                    reply.assistant_message = "Plan prepared; ready to execute when you confirm."
            else:
                reply.status = "planned"
                if not reply.assistant_message:
                    reply.assistant_message = "Plan prepared. Confirm to proceed, or describe changes."

        # Ensure ready state asks for confirmation
        if reply.status == "ready_to_execute" and not reply.requires_confirmation:
            reply.requires_confirmation = True

        # If user clicked Confirm and model forgot actions, reuse last prepared actions
        if event == "confirm_execute" and not reply.actions:
            prev_actions = state.get("last_actions") or []
            if prev_actions:
                try:
                    reply.actions = [Action.model_validate(a) for a in prev_actions]
                    reply.status = "ready_to_execute"
                    reply.requires_confirmation = True
                    if not reply.assistant_message:
                        reply.assistant_message = "Using previously prepared actions. Proceeding to execution."
                except Exception:
                    pass

        # Final polish (ensures questions[] when needed, etc.)
        reply = postprocess_reply(reply, user_message)

        # -------- Persist breadcrumbs --------
        state["last_status"] = reply.status
        if reply.actions:
            state["last_actions"] = [a.model_dump() for a in reply.actions]

        state["history"].append({
            "role": "user",
            "content": user_message if event == "user_message" else f"[{event}] {user_message}"
        })
        state["history"].append({
            "role": "assistant",
            "content": json.dumps(reply.model_dump(), ensure_ascii=False)
        })
        save_state(session_id, state)

        # -------- Output --------
        print(json.dumps(reply.model_dump(), ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "status": "need_clarification",
            "assistant_message": f"LLM agent error: {e}\n{traceback.format_exc()}",
            "questions": [],
            "plan": [],
            "actions": [],
            "requires_confirmation": False
        }))


if __name__ == "__main__":
    main()
