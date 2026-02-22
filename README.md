# Blender-Support-WORK-IN-PROGRESS-

SL Custom Objects – Blender → Unity (Beta)

⚠ This project is still in BETA and under active development.
Features may change, bugs can exist, and things are still being improved.

🎯 Goal

Convert any Blender mesh (example: monkey, house, or custom models) into a fully SCP:SL–compatible structure using PrimitiveComponent (Cube) blocks only.

No MeshFilter, no MeshRenderer — only primitives, so it works with SL Custom Objects.

🔧 How it works

You create a model in Blender

The exporter reads the mesh exactly as you modeled it

Each face (polygon) is converted into one Cube

Cubes are generated with:

Position → face center

Scale → real face size

Rotation → calculated from the face normal

The final result is a model that looks the same, but is entirely built from cubes and 100% SCP:SL compatible.

🧠 Rotation & smoothness fix

Earlier Project had issues where cubes appeared rotated randomly.
This was caused by inconsistent face rotation (roll/twist).

Fixed in the current beta:

A consistent reference tangent is used for every face

All cubes facing the same direction are aligned correctly

The structure now looks smooth and stable, not “exploded”

⚠ Beta limitations

Performance depends on face count (high-poly meshes = many cubes)

Not optimized yet for very complex models

API and workflow may change

Some edge cases may still behave incorrectly

📦 Result

Monkey test → smooth cube-based shape

Houses / rooms / walls → clean and stable

Fully compatible with SL Custom Objects

What you build in Blender is what you get in Unity

🛠 Tools used

Modeling: Blender

Import & scene setup: Unity

Target system: SCP:SL Custom Objects

Made by @𝕮𝖍𝖆𝖔𝖘-𝕴𝖓𝖘𝖚𝖗𝖌𝖊𝖓𝖈𝖞 

🧪 Beta version – more features coming soon and fixing issues with importing**


Video: https://www.youtube.com/watch?v=uakCikEKSOs
