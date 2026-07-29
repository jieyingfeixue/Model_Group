# LH Capture Orientation and Depth Audit

Audit date: 2026-06-12

Inputs:

- Dataset: `L:/LH_data_all_sensor`
- Depth export summary: `L:/LH_data_all_sensor_annotations_depth/depth_dataset_summary.json`
- Machine-readable orientation report: `temp/capture_orientation_audit.json`

## Confirmed correction

- `4_29/with_cameras_capture_20260429_165854`
  - Manual image/map inspection confirms a 180 degree camera direction error.
  - Applied camera heading correction: `+180 deg`.
  - This capture has no MAT and no BIN, so the correction fixes map direction/FOV
    but cannot create radar depth.

## Annotated captures with no radar source

These captures have annotations but contain neither MAT nor BIN. Point-cloud
projection and radar-derived metric depth are therefore unavailable:

- `20260429_161943`: 315 frames, 2,619 boxes, depth coverage 0%
- `20260429_165854`: 474 frames, 5,197 boxes, depth coverage 0%
- `20260429_165931`: 253 frames, 1,428 boxes, depth coverage 0%
- `20260429_185909`: 282 frames, 1,294 boxes, depth coverage 0%
- `20260429_195137`: 150 frames, 296 boxes, depth coverage 0%

## Radar exists but exported depth is zero

These captures have MAT and BIN data. Zero depth indicates a matching,
visibility, map-prior, or depth-generation failure rather than missing radar:

- `20260508_171129_1`: 77 MAT, 1 BIN, 220 frames, 325 boxes
- `20260509_113036`: 142 MAT, 1 BIN, 223 frames, 782 boxes
- `20260509_113112_3`: 144 MAT, 1 BIN, 344 frames, 891 boxes
- `20260509_113138_2`: 126 MAT, 1 BIN, 335 frames, 978 boxes
- `20260509_133549`: 167 MAT, 1 BIN, 385 frames, 1,142 boxes
- `20260509_133633`: 166 MAT, 1 BIN, 430 frames, 1,436 boxes

## Very low depth coverage

- `20260430_150023`: 6.87%
- `20260430_150451`: 6.52%
- `20260509_143912`: 9.15%
- `20260509_173327`: 4.15%
- `20260509_180142`: 3.66%

## Orientation candidates requiring visual review

Trajectory course is only a diagnostic: a UAV can fly sideways or backwards,
so these are not automatically corrected. The strongest segment-level
180-degree candidates are:

- `20260430_101120`
  - `segment_001_000110.000_000120.000`
  - `segment_002_000180.000_000191.000`
- `20260430_191146`
  - `segment_001_000273.000_000281.000`
  - `segment_004_000040.000_000086.000` (weaker, about 146.5 degrees)
- `20260508_171129_1`
  - `segment_004_000117.000_000190.000`
  - `segment_005_000199.000_000244.000`
- `20260509_113112_3`
  - `segment_000_000000.000_000123.000`

Capture-wide correction is unsafe for these candidates because other segments
inside the same capture may be normal or show sideways flight.

## Additional source-data gaps

The following 2026-06-08 captures currently have BIN but no converted MAT:

- `20260608_125137`
- `20260608_130656`
- `20260608_143004`
- `20260608_152116`

The following 2026-06-08 captures contain neither MAT nor BIN:

- `20260608_162452`
- `20260608_174907`
- `20260608_174950`
