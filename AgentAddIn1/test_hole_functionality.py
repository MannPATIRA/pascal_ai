"""
Test script for hole creation functionality
This script creates a simple block and then adds various types of holes to test the functionality
"""

import adsk.core
import adsk.fusion
import traceback

def run(context):
    """Test hole creation functionality"""
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        
        # Get the active design
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('No active design found.')
            return
        
        root = design.rootComponent
        
        # Create a simple block first
        ui.messageBox('Creating a test block...')
        
        # Create sketch on XY plane
        sketch = root.sketches.add(root.xYConstructionPlane)
        
        # Add a rectangle
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(-2, -2, 0),
            adsk.core.Point3D.create(2, 2, 0)
        )
        
        # Extrude the rectangle to create a block
        profile = sketch.profiles.item(0)
        ext_feats = root.features.extrudeFeatures
        ext_input = ext_feats.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        ext_input.setOneSideExtent(
            adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(1)),
            adsk.fusion.ExtentDirections.PositiveExtentDirection
        )
        ext_feat = ext_feats.add(ext_input)
        
        if not ext_feat:
            ui.messageBox('Failed to create test block.')
            return
        
        ui.messageBox('Test block created successfully! Now testing hole creation...')
        
        # Test 1: Simple hole
        ui.messageBox('Creating simple hole...')
        success = create_simple_hole(root)
        if not success:
            ui.messageBox('Simple hole creation failed.')
            return
        
        # Test 2: Counterbore hole
        ui.messageBox('Creating counterbore hole...')
        success = create_counterbore_hole(root)
        if not success:
            ui.messageBox('Counterbore hole creation failed.')
            return
        
        # Test 3: Countersink hole
        ui.messageBox('Creating countersink hole...')
        success = create_countersink_hole(root)
        if not success:
            ui.messageBox('Countersink hole creation failed.')
            return
        
        ui.messageBox('All hole tests completed successfully!')
        
    except:
        ui.messageBox('Test failed:\n{}'.format(traceback.format_exc()))

def create_simple_hole(root):
    """Create a simple hole"""
    try:
        # Get target face (top face of the block)
        bodies = root.bRepBodies
        if bodies.count == 0:
            return False
        
        body = bodies.item(0)
        faces = body.faces
        
        # Find the top face (highest Z value)
        top_face = None
        max_z = -999999
        
        for i in range(faces.count):
            face = faces.item(i)
            if face.boundingBox.maxPoint.z > max_z:
                max_z = face.boundingBox.maxPoint.z
                top_face = face
        
        if not top_face:
            return False
        
        # Create simple hole
        hole_feats = root.features.holeFeatures
        hole_input = hole_feats.createInput(top_face, adsk.fusion.FeatureOperations.CutFeatureOperation)
        
        # Set position (center of the face)
        hole_input.setPositionByPoint(adsk.core.Point3D.create(0, 0, 1))
        
        # Set hole parameters
        hole_input.setSimpleHoleDiameter(adsk.core.ValueInput.createByReal(0.5))  # 5mm diameter
        hole_input.setSimpleHoleDepth(adsk.core.ValueInput.createByReal(0.8))     # 8mm depth
        hole_input.setSimpleHoleDepthType(adsk.fusion.HoleDepthTypes.BlindHoleDepthType)
        
        # Create the hole
        hole_feat = hole_feats.add(hole_input)
        return hole_feat is not None
        
    except:
        return False

def create_counterbore_hole(root):
    """Create a counterbore hole"""
    try:
        # Get target face
        bodies = root.bRepBodies
        if bodies.count == 0:
            return False
        
        body = bodies.item(0)
        faces = body.faces
        
        # Find the top face
        top_face = None
        max_z = -999999
        
        for i in range(faces.count):
            face = faces.item(i)
            if face.boundingBox.maxPoint.z > max_z:
                max_z = face.boundingBox.maxPoint.z
                top_face = face
        
        if not top_face:
            return False
        
        # Create counterbore hole
        hole_feats = root.features.holeFeatures
        hole_input = hole_feats.createInput(top_face, adsk.fusion.FeatureOperations.CutFeatureOperation)
        
        # Set position (offset from center)
        hole_input.setPositionByPoint(adsk.core.Point3D.create(1, 1, 1))
        
        # Set counterbore parameters
        hole_input.setCounterboreHoleDiameter(adsk.core.ValueInput.createByReal(0.3))  # 3mm hole
        hole_input.setCounterboreHoleDepth(adsk.core.ValueInput.createByReal(0.8))     # 8mm depth
        hole_input.setCounterboreDiameter(adsk.core.ValueInput.createByReal(0.6))     # 6mm counterbore
        hole_input.setCounterboreDepth(adsk.core.ValueInput.createByReal(0.2))        # 2mm counterbore depth
        hole_input.setCounterboreHoleDepthType(adsk.fusion.HoleDepthTypes.BlindHoleDepthType)
        
        # Create the hole
        hole_feat = hole_feats.add(hole_input)
        return hole_feat is not None
        
    except:
        return False

def create_countersink_hole(root):
    """Create a countersink hole"""
    try:
        # Get target face
        bodies = root.bRepBodies
        if bodies.count == 0:
            return False
        
        body = bodies.item(0)
        faces = body.faces
        
        # Find the top face
        top_face = None
        max_z = -999999
        
        for i in range(faces.count):
            face = faces.item(i)
            if face.boundingBox.maxPoint.z > max_z:
                max_z = face.boundingBox.maxPoint.z
                top_face = face
        
        if not top_face:
            return False
        
        # Create countersink hole
        hole_feats = root.features.holeFeatures
        hole_input = hole_feats.createInput(top_face, adsk.fusion.FeatureOperations.CutFeatureOperation)
        
        # Set position (offset from center)
        hole_input.setPositionByPoint(adsk.core.Point3D.create(-1, -1, 1))
        
        # Set countersink parameters
        hole_input.setCountersinkHoleDiameter(adsk.core.ValueInput.createByReal(0.4))  # 4mm hole
        hole_input.setCountersinkHoleDepth(adsk.core.ValueInput.createByReal(0.8))     # 8mm depth
        hole_input.setCountersinkDiameter(adsk.core.ValueInput.createByReal(0.8))     # 8mm countersink
        hole_input.setCountersinkAngle(adsk.core.ValueInput.createByReal(82.0))       # 82° angle
        hole_input.setCountersinkHoleDepthType(adsk.fusion.HoleDepthTypes.BlindHoleDepthType)
        
        # Create the hole
        hole_feat = hole_feats.add(hole_input)
        return hole_feat is not None
        
    except:
        return False
