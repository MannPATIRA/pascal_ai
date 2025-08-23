# TextRunner.py
import adsk.core, adsk.fusion, adsk.cam, traceback, subprocess

# === EDIT THESE TWO PATHS ===
PYTHON_EXE     = r"D:\Desktop\Pascal_Addins\Pascal_Addin_1\TextRunner\venv\Scripts\python.exe"
EXTERNAL_SCRIPT = r"C:\Users\Sanuka1\Desktop\external\external_runner.py"
# ============================

# UI placement (Solid workspace → Create panel)
WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID     = 'SolidCreatePanel'

CMD_ID          = 'text_runner_cmd'
CMD_NAME        = 'Run External Script'
CMD_DESCRIPTION = 'Pass text to an external Python and run it.'

_handlers = []  # prevent GC of event handlers


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        # Create the command definition (button)
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_DESCRIPTION
            )

        # Hook commandCreated
        on_created = _CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        # Add the button to a panel
        ws = ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        if panel:
            existing = panel.controls.itemById(CMD_ID)
            if not existing:
                panel.controls.addCommand(cmd_def)
        else:
            ui.messageBox(f"Toolbar panel '{PANEL_ID}' not found.")

    except:
        if ui:
            ui.messageBox('Add-In start failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        # Remove button from panel
        ws = ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()

        # Remove the command definition
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

    except:
        if ui:
            ui.messageBox('Add-In stop failed:\n{}'.format(traceback.format_exc()))


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command

            # Dialog inputs
            inputs = cmd.commandInputs
            inputs.addStringValueInput('userText', 'Text to send', '')

            # Hook execute
            on_execute = _CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

        except:
            adsk.core.Application.get().userInterface.messageBox(
                'commandCreated failed:\n{}'.format(traceback.format_exc())
            )


class _CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs):
        ui = None
        try:
            app = adsk.core.Application.get()
            ui  = app.userInterface

            # Grab the user text
            inputs = args.firingEvent.sender.commandInputs
            text_in = inputs.itemById('userText').value if inputs.itemById('userText') else ''

            # === Run your external Python ===
            completed = subprocess.run(
                [PYTHON_EXE, EXTERNAL_SCRIPT, text_in],
                capture_output=True,
                text=True,
                shell=False
            )

            out = (completed.stdout or '').strip()
            err = (completed.stderr or '').strip()

            # Show what the external script returned
            ui.messageBox(
                f"External finished (code {completed.returncode}).\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err or '(none)'}"
            )

            # === Make a visible change in the model using the result ===
            # We’ll add sketch text with whatever came back on STDOUT.
            if out:
                design = adsk.fusion.Design.cast(app.activeProduct)
                if not design:
                    ui.messageBox('No active Fusion design to modify.')
                    return

                root = design.rootComponent
                sketches = root.sketches
                xy = root.xYConstructionPlane
                sk = sketches.add(xy)

                # Add text at origin; height ~1 cm (Fusion internal units = cm)
                texts = sk.sketchTexts
                inp = texts.createInput(out, adsk.core.Point3D.create(0, 0, 0), 1.0)
                texts.add(inp)

        except:
            if ui:
                ui.messageBox('execute failed:\n{}'.format(traceback.format_exc()))