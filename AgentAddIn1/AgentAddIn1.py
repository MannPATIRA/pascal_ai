import adsk.core, adsk.fusion, adsk.cam, traceback, subprocess, json, uuid, os
from pathlib import Path

WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID     = 'SolidCreatePanel'
CMD_ID       = 'pascal_agent_cmd'
CMD_NAME     = 'PASCAL Agent'
CMD_DESC     = 'Chat, clarify, plan, and execute CAD steps safely.'
PALETTE_ID   = 'pascal_agent_palette'

_LAST_ACTIONS = []
_GLOBAL_LAST_SKETCH = None
_GLOBAL_LAST_PROFILE = None


# === SET THESE PATHS ===
HERE        = Path(__file__).resolve().parent
HTML        = (HERE / 'palette.html').as_uri()
PYTHON_EXE  = str(HERE / 'external' / 'external_venv' / 'Scripts' / 'pythonw.exe')  # adjust
AGENT       = str(HERE / 'external' / 'agent_runner.py')                             # adjust
# =======================

_handlers = []
SESSION_ID = None

def run(context):
    ui=None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)

        on_created = _CommandCreated()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        ws = ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(cmd_def)
    except:
        if ui:
            ui.messageBox('Add-In start failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    ui=None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        ws = ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl: ctrl.deleteMe()
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def: cmd_def.deleteMe()
        pal = ui.palettes.itemById(PALETTE_ID)
        if pal: pal.deleteMe()
    except:
        if ui:
            ui.messageBox('Add-In stop failed:\n{}'.format(traceback.format_exc()))

class _CommandCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            global SESSION_ID
            SESSION_ID = str(uuid.uuid4())

            ui = adsk.core.Application.get().userInterface
            pal = ui.palettes.itemById(PALETTE_ID)
            if not pal:
                pal = ui.palettes.add(PALETTE_ID, 'PASCAL Agent', HTML, True, True, True, 460, 600)
                on_html = _PaletteHTML()
                pal.incomingFromHTML.add(on_html)
                _handlers.append(on_html)
            pal.isVisible = True

            _send_to_html({"status":"need_clarification",
                           "assistant_message":"Hi! Tell me what you want to add/change. I’ll ask questions, plan steps, and prepare actions safely."})
        except:
            # Do not close palette; just surface error in the chat
            _send_to_html({"status":"need_clarification","assistant_message":"commandCreated failed:\n"+traceback.format_exc()})

class _PaletteHTML(adsk.core.HTMLEventHandler):
    def notify(self, args: adsk.core.HTMLEventArgs):
        try:
            # Only react to our explicit channel
            if args.action != 'agent_event':
                return
            data_json = args.data or "{}"
            data = json.loads(data_json)
            ev   = (data.get("event") or "").strip()
            text = (data.get("user_message") or "").strip()

            # ACK back to the palette so you see the round trip
            _send_to_html({"assistant_message": f"↘ received {ev}", "questions": [], "plan": [], "actions": []})

            if ev == 'user_message':
                _handle_agent_event("user_message", text)
            elif ev == 'confirm_execute':
                _handle_agent_event("confirm_execute", "OK to proceed")
            else:
                _send_to_html({"status":"need_clarification","assistant_message":f"Unsupported event '{ev}'."})

        except:
            _send_to_html({"status":"need_clarification","assistant_message":"HTML→Fusion parse error:\n"+traceback.format_exc()})

def _send_to_html(payload: dict):
    try:
        ui = adsk.core.Application.get().userInterface
        pal = ui.palettes.itemById(PALETTE_ID)
        if pal:
            pal.sendInfoToHTML('agent_reply', json.dumps(payload))
    except:
        # Last-resort: swallow; never crash UI thread
        pass

def _call_agent(event: str, user_message: str) -> dict:
    try:
        payload = {"event": event, "user_message": user_message}

        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags |= subprocess.CREATE_NO_WINDOW

        completed = subprocess.run(
            [PYTHON_EXE, AGENT, SESSION_ID, json.dumps(payload)],
            capture_output=True, text=True, shell=False, timeout=180,
            startupinfo=startupinfo, creationflags=creationflags
        )
        if completed.returncode != 0:
            return {"status":"need_clarification",
                    "assistant_message": f"Agent returned code {completed.returncode}.\nSTDERR:\n{(completed.stderr or '').strip()}"}
        out = (completed.stdout or "").strip()
        try:
            return json.loads(out or "{}")
        except Exception as e:
            return {"status":"need_clarification","assistant_message": f"Agent JSON decode failed: {e}\nRaw:\n{out[:600]}"}
    except Exception as e:
        return {"status":"need_clarification","assistant_message": f"Agent call failed: {e}"}

def _handle_agent_event(event: str, user_message: str):
    global _LAST_ACTIONS

    # 1) Ask the agent & display whatever it said
    reply = _call_agent(event, user_message)
    _send_to_html(reply)

    # Cache actions if they arrived
    if isinstance(reply.get("actions"), list) and reply["actions"]:
        _LAST_ACTIONS = reply["actions"]

    # 2) On confirm, ensure we *really* have actions; else force-convert plan → actions
    if event == "confirm_execute":
        actions = reply.get("actions") or _LAST_ACTIONS or []

        if not actions:
            # Try one forced conversion turn
            force = _call_agent("force_actions", "")
            if isinstance(force.get("actions"), list) and force["actions"]:
                actions = force["actions"]
                _LAST_ACTIONS = actions
                # (optional) show what we're about to run
                _send_to_html({
                    "status": "ready_to_execute",
                    "assistant_message": "Received executable actions from the plan. Executing now.",
                    "questions": [],
                    "plan": [],
                    "actions": actions,
                    "requires_confirmation": True
                })
            else:
                # Still no actions — do not execute. Ask user to clarify.
                _send_to_html({
                    "status": "need_clarification",
                    "assistant_message": "I couldn’t get executable actions from the plan. Please restate the size, plane (XY/YZ/XZ), and position.",
                    "questions": [
                        "What exact sizes (with units)?",
                        "Which plane (XY, YZ, XZ)?",
                        "Where should it be positioned (center/origin or coordinates)?"
                    ],
                    "plan": [],
                    "actions": [],
                    "requires_confirmation": False
                })
                return

        # 3) We have actions — run them
        ok, details = _execute_actions(actions)

        # 4) Report execution result to agent and show final reply
        result_msg = json.dumps({"ok": ok, "details": details})
        final = _call_agent("execution_result", result_msg)
        _send_to_html(final)

def _execute_actions(actions):
    try:
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            return False, "No active Fusion design."
        root = design.rootComponent

        global _GLOBAL_LAST_SKETCH, _GLOBAL_LAST_PROFILE

        ctx = {"sketches": {}}
        last_profile = None
        made_geometry = False

        def _fallback_sketch():
            global _GLOBAL_LAST_SKETCH
            if _GLOBAL_LAST_SKETCH:
                return _GLOBAL_LAST_SKETCH
            sk = root.sketches.add(root.xYConstructionPlane)
            try: sk.isVisible = True
            except: pass
            _GLOBAL_LAST_SKETCH = sk
            return sk

        def _find_recent_profile():
            # try in-memory last; then scan sketches newest→oldest
            if _GLOBAL_LAST_PROFILE:
                return _GLOBAL_LAST_PROFILE
            sketches = root.sketches
            for i in range(sketches.count-1, -1, -1):
                sk = sketches.item(i)
                if sk.profiles.count > 0:
                    return sk.profiles.item(sk.profiles.count - 1)
            return None

        for idx, a in enumerate(actions):
            name = a.get("action")
            p = a.get("params", {})

            if name == "create_sketch":
                plane = {"XY":root.xYConstructionPlane, "YZ":root.yZConstructionPlane, "XZ":root.xZConstructionPlane}.get(p.get("plane","XY"))
                if not plane: return False, f"Unknown plane: {p.get('plane')}"
                sk = root.sketches.add(plane)
                try: sk.isVisible = True
                except: pass
                sk_id = f"sk_{idx}"
                ctx["sketches"][sk_id] = sk
                _GLOBAL_LAST_SKETCH = sk
                last_profile = sk.profiles.item(sk.profiles.count-1) if sk.profiles.count>0 else None
                made_geometry = True

            elif name == "add_rectangle":
                sk = ctx["sketches"].get(p.get("sketch_id")) or _fallback_sketch()
                x1,y1 = float(p["x1"]), float(p["y1"])
                x2,y2 = float(p["x2"]), float(p["y2"])
                sk.sketchCurves.sketchLines.addTwoPointRectangle(
                    adsk.core.Point3D.create(x1, y1, 0),
                    adsk.core.Point3D.create(x2, y2, 0)
                )
                if sk.profiles.count > 0:
                    last_profile = sk.profiles.item(sk.profiles.count - 1)
                    _GLOBAL_LAST_PROFILE = last_profile
                _GLOBAL_LAST_SKETCH = sk
                made_geometry = True

            elif name == "add_circle":
                sk = ctx["sketches"].get(p.get("sketch_id")) or _fallback_sketch()
                cx,cy,r = float(p["cx"]), float(p["cy"]), float(p["r"])
                sk.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(cx,cy,0), r)
                if sk.profiles.count > 0:
                    last_profile = sk.profiles.item(sk.profiles.count - 1)
                    _GLOBAL_LAST_PROFILE = last_profile
                _GLOBAL_LAST_SKETCH = sk
                made_geometry = True

            elif name == "extrude_last_profile":
                prof = last_profile or _find_recent_profile()
                if not prof:
                    return False, "No closed profile available to extrude."
                dist = float(p["distance"])
                op   = p.get("operation","NewBody")
                extFeats = root.features.extrudeFeatures
                dval = adsk.core.ValueInput.createByReal(dist)
                opmap = {
                    "NewBody": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                    "Cut":     adsk.fusion.FeatureOperations.CutFeatureOperation,
                    "Join":    adsk.fusion.FeatureOperations.JoinFeatureOperation
                }
                extInput = extFeats.createInput(prof, opmap.get(op, adsk.fusion.FeatureOperations.NewBodyFeatureOperation))
                extInput.setOneSideExtent(dval, adsk.fusion.ExtentDirections.PositiveExtentDirection)
                extFeats.add(extInput)
                made_geometry = True

            elif name == "add_text":
                plane = {"XY":root.xYConstructionPlane, "YZ":root.yZConstructionPlane, "XZ":root.xZConstructionPlane}.get(p.get("plane","XY"))
                if not plane: return False, f"Unknown plane: {p.get('plane')}"
                sk = root.sketches.add(plane)
                try: sk.isVisible = True
                except: pass
                inp = sk.sketchTexts.createInput(str(p.get("text","")), float(p.get("height",1.0)), adsk.core.Point3D.create(float(p.get("x",0)), float(p.get("y",0)), 0))
                sk.sketchTexts.add(inp)
                _GLOBAL_LAST_SKETCH = sk
                made_geometry = True

            else:
                # ignore unknown actions silently
                continue

        try:
            if made_geometry:
                app.activeViewport.fit()
        except: pass

        return True, "All actions executed."
    except Exception as e:
        return False, f"Execution error: {e}\n{traceback.format_exc()}"
