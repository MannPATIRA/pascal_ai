# Hole Creation Functionality

## Overview

The PASCAL Agent add-in now supports creating holes in existing solid bodies. This functionality allows users to create three types of holes:

1. **Simple Holes** - Basic cylindrical holes
2. **Counterbore Holes** - Holes with a larger diameter at the top
3. **Countersink Holes** - Holes with a conical recess at the top

## Supported Actions

### `create_hole` Action

**Parameters:**
- `diameter` (number): Hole diameter in centimeters (required)
- `depth` (number): Hole depth in centimeters (required)
- `x` (number): X coordinate of hole center (default: 0)
- `y` (number): Y coordinate of hole center (default: 0)
- `z` (number): Z coordinate of hole center (default: 0)
- `hole_type` (string): Type of hole - "simple", "counterbore", or "countersink" (default: "simple")

**Optional Parameters for Counterbore:**
- `counterbore_diameter` (number): Counterbore diameter in centimeters (auto-calculated if not provided)
- `counterbore_depth` (number): Counterbore depth in centimeters (auto-calculated if not provided)

**Optional Parameters for Countersink:**
- `countersink_diameter` (number): Countersink diameter in centimeters (auto-calculated if not provided)
- `countersink_angle` (number): Countersink angle in degrees (default: 82°)

## Usage Examples

### Natural Language Commands

1. **Simple Hole:**
   ```
   "Create a 5mm hole in the center of the block"
   ```

2. **Counterbore Hole:**
   ```
   "Add a counterbore hole with 3mm diameter and 6mm counterbore at position (1,1)"
   ```

3. **Countersink Hole:**
   ```
   "Create a countersink hole with 4mm diameter and 82 degree angle at (-1,-1)"
   ```

4. **Multiple Holes:**
   ```
   "Create a block and add three holes: a simple 5mm hole in the center, a counterbore hole at (1,1), and a countersink hole at (-1,-1)"
   ```

### Generated Actions Examples

**Simple Hole:**
```json
{
  "action": "create_hole",
  "params": {
    "diameter": 0.5,
    "depth": 1.0,
    "x": 0,
    "y": 0,
    "z": 1,
    "hole_type": "simple"
  }
}
```

**Counterbore Hole:**
```json
{
  "action": "create_hole",
  "params": {
    "diameter": 0.3,
    "depth": 0.8,
    "x": 1,
    "y": 1,
    "z": 1,
    "hole_type": "counterbore",
    "counterbore_diameter": 0.6,
    "counterbore_depth": 0.2
  }
}
```

**Countersink Hole:**
```json
{
  "action": "create_hole",
  "params": {
    "diameter": 0.4,
    "depth": 0.8,
    "x": -1,
    "y": -1,
    "z": 1,
    "hole_type": "countersink",
    "countersink_diameter": 0.8,
    "countersink_angle": 82.0
  }
}
```

## Technical Implementation

### Fusion 360 API Usage

The hole creation uses the following Fusion 360 API components:

1. **HoleFeatures Collection:**
   ```python
   hole_feats = root.features.holeFeatures
   ```

2. **Hole Input Creation:**
   ```python
   hole_input = hole_feats.createInput(target_face, adsk.fusion.FeatureOperations.CutFeatureOperation)
   ```

3. **Position Setting:**
   ```python
   hole_input.setPositionByPoint(adsk.core.Point3D.create(x, y, z))
   ```

4. **Hole Type Configuration:**
   - **Simple:** `setSimpleHoleDiameter()`, `setSimpleHoleDepth()`
   - **Counterbore:** `setCounterboreHoleDiameter()`, `setCounterboreDiameter()`, `setCounterboreDepth()`
   - **Countersink:** `setCountersinkHoleDiameter()`, `setCountersinkDiameter()`, `setCountersinkAngle()`

### Face Selection Logic

The system automatically selects the appropriate face for hole creation:

1. **Body Detection:** Finds the first available solid body
2. **Face Selection:** Searches for faces at the target Z level
3. **Fallback:** Uses the first available face if no face is found at the target Z level

## Testing

### Manual Testing

1. **Run the Test Script:**
   - Load `test_hole_functionality.py` in Fusion 360
   - Run the script to create a test block with three different hole types

2. **Test via PASCAL Agent:**
   ```
   "Create a 4cm x 4cm x 2cm block and add a 1cm hole in the center"
   ```

3. **Test Different Hole Types:**
   ```
   "Add a counterbore hole with 5mm diameter and 10mm counterbore at position (1,0)"
   ```

### Expected Results

- **Simple Hole:** Clean cylindrical hole with specified diameter and depth
- **Counterbore Hole:** Hole with larger diameter recess at the top
- **Countersink Hole:** Hole with conical recess at the top

## Error Handling

The system includes comprehensive error handling:

1. **Parameter Validation:**
   - Diameter and depth must be positive
   - All measurements in centimeters

2. **Face Selection:**
   - Requires existing solid body
   - Graceful fallback if target face not found

3. **API Errors:**
   - Detailed error messages for debugging
   - Graceful failure handling

## Limitations

1. **Face Selection:** Currently uses simplified face selection logic
2. **Position Constraints:** Holes must be placed on existing faces
3. **Body Requirements:** Requires at least one solid body in the design

## Future Enhancements

1. **Smart Face Selection:** More sophisticated face selection based on geometry
2. **Pattern Holes:** Support for creating hole patterns (linear, circular)
3. **Threaded Holes:** Support for threaded hole creation
4. **Hole Tables:** Automatic generation of hole tables for documentation

## Troubleshooting

### Common Issues

1. **"No suitable face found" Error:**
   - Ensure you have a solid body in the design
   - Check that the hole position is on a face of the body

2. **"Invalid hole parameters" Error:**
   - Verify diameter and depth are positive numbers
   - Ensure all measurements are in centimeters

3. **Hole Creation Fails:**
   - Check that the target face is large enough for the hole
   - Verify the hole position is within the face boundaries

### Debug Mode

Enable debug mode in `config.py` to see detailed error messages:
```python
DEBUG = True
```
