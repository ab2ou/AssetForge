# Third-party software

AssetForge does not ship any third-party code. It runs inside Blender and uses these libraries:

| software | used for | licence | how it gets there |
|---|---|---|---|
| [Blender](https://www.blender.org) 5.2 (`bpy`, `bmesh`, `mathutils`, OpenVDB voxel remesh, Cycles) | everything | GPL-2.0-or-later | installed by the user |
| [NumPy](https://numpy.org) | geometry maths | BSD-3-Clause | bundled with Blender |
| [PyMeshLab](https://github.com/cnr-isti-vclab/PyMeshLab) | QEM low poly, repairs, Taubin smoothing, mesh measures | GPL-3.0 | `setup_forge.py` installs it into `pylibs/` |
| [MeshLib](https://meshlib.io) (optional) | alternative voxel engine (`high_cleanup.engine = "meshlib"`) | proprietary dual licence: free for non-commercial and educational use, commercial licence otherwise | only with `setup_forge.py --meshlib` |

Reference data in `weapon_profiles.json` cites its sources next to each range (for example wiktenauer.com for
historical sword dimensions and published anthropometry for hand sizes).
