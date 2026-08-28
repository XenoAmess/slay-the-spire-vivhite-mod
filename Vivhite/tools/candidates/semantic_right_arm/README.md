# Semantic near-arm graybox candidate

This isolated candidate freezes the screen-right, camera-near arm consumer before any paid generation.
The side is the character's anatomical **left** arm; the old `*_right` suffix in the split builder is
screen-space only.

The production granularity is deliberately two attachments:

1. `upper_arm`, pivoting at the shoulder and drawn behind the torso's shoulder sleeve/armhole;
2. one continuous `forearm_hand`, pivoting at the elbow and drawn over the upper arm and torso.

The palm remains an internal deform/VFX bone, not a separate wrist attachment. This keeps elbow motion
while removing the highest-risk wrist seam. `consumer-contract.json` freezes the 0018 source hash,
landmarks, hidden overlap budgets, draw order, and nine setup/action/death extremes. The `.spjson` is a
no-art Spine 4.2.43 test skeleton; this directory intentionally contains no PNG or atlas.

Build, validate, and render the hidden Vulkan diagnostic contact sheet from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/art/candidates/semantic_right_arm/Invoke-SemanticRightArmGraybox.ps1
```

The renderer writes only to `.work/semantic-right-arm/`. Nothing here is deployable or connected to the
runtime skin. There is currently no dedicated native-transparent production upper-arm or forearm-hand
source in the repository; 0018/0022 are flattened whole-body evidence, and 0054 is only the adjacent
torso sleeve candidate.
