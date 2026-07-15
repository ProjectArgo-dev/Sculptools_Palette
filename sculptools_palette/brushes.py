# sculptools_palette/brushes.py
# Catalogue of all built-in Blender 4.5 sculpt brushes.
# Format: (display_name, bpy_data_name, asset_library_name, icon)
#
# NOTE: Blender 4.5 removed all BRUSH_* icons from UILayout.operator().
# We use generic icons grouped by brush category instead.

BRUSHES = [
    # --- Primary sculpting ---
    ("Draw",                "Draw",                         "Draw",                         "STYLUS_PRESSURE"),
    ("Draw Sharp",          "Draw Sharp",                   "Draw Sharp",                   "STYLUS_PRESSURE"),
    ("Clay",                "Clay",                         "Clay",                         "MESH_UVSPHERE"),
    ("Clay Strips",         "Clay Strips",                  "Clay Strips",                  "MESH_UVSPHERE"),
    ("Clay Thumb",          "Clay Thumb",                   "Clay Thumb",                   "MESH_UVSPHERE"),
    ("Layer",               "Layer",                        "Layer",                        "ALIGN_TOP"),
    ("Inflate",             "Inflate/Deflate",              "Inflate/Deflate",              "SPHERECURVE"),
    ("Blob",                "Blob",                         "Blob",                         "SPHERECURVE"),
    ("Crease Sharp",        "Crease Sharp",                 "Crease Sharp",                 "SHARPCURVE"),
    ("Crease Polish",       "Crease Polish",                "Crease Polish",                "SMOOTHCURVE"),
    ("Sharpen",             "Sharpen",                      "Sharpen",                      "SHARPCURVE"),
    ("Trim",                "Trim",                         "Trim",                         "MOD_DECIM"),
    # --- Smoothing & flattening ---
    ("Smooth",              "Smooth",                       "Smooth",                       "SMOOTHCURVE"),
    ("Flatten",             "Flatten/Contrast",             "Flatten/Contrast",             "MESH_PLANE"),
    ("Fill",                "Fill/Deepen",                  "Fill/Deepen",                  "TRIA_UP"),
    ("Scrape",              "Scrape/Fill",                  "Scrape/Fill",                  "MOD_DECIM"),
    ("Scrape Multi",        "Scrape Multiplane",            "Scrape Multiplane",            "MOD_DECIM"),
    ("Plateau",             "Plateau",                      "Plateau",                      "MESH_PLANE"),
    # --- Grab & deform ---
    ("Grab",                "Grab",                         "Grab",                         "HAND"),
    ("Grab 2D",             "Grab 2D",                      "Grab 2D",                      "HAND"),
    ("Grab Silhouette",     "Grab Silhouette",              "Grab Silhouette",              "HAND"),
    ("Elastic Grab",        "Elastic Grab",                 "Elastic Grab",                 "HAND"),
    ("Snake Hook",          "Snake Hook",                   "Snake Hook",                   "CURVE_BEZCURVE"),
    ("Elastic Snake Hook",  "Elastic Snake Hook",           "Elastic Snake Hook",           "CURVE_BEZCURVE"),
    ("Thumb",               "Thumb",                        "Thumb",                        "TRIA_RIGHT"),
    ("Pose",                "Pose",                         "Pose",                         "ARMATURE_DATA"),
    ("Nudge",               "Nudge",                        "Nudge",                        "ARROW_LEFTRIGHT"),
    ("Twist",               "Twist",                        "Twist",                        "DRIVER_ROTATIONAL_DIFFERENCE"),
    ("Pull",                "Pull",                         "Pull",                         "TRIA_UP"),
    ("Relax Slide",         "Relax Slide",                  "Relax Slide",                  "SMOOTHCURVE"),
    ("Relax Pinch",         "Relax Pinch",                  "Relax Pinch",                  "SMOOTHCURVE"),
    ("Pinch",               "Pinch/Magnify",                "Pinch/Magnify",                "ZOOM_IN"),
    ("Boundary",            "Boundary",                     "Boundary",                     "MESH_DATA"),
    # --- Cloth ---
    ("Cloth Drag",          "Drag Cloth",                   "Drag Cloth",                   "MOD_CLOTH"),
    ("Cloth Grab",          "Grab Cloth",                   "Grab Cloth",                   "MOD_CLOTH"),
    ("Cloth Grab Planar",   "Grab Planar Cloth ",           "Grab Planar Cloth ",           "MOD_CLOTH"),
    ("Cloth Grab Random",   "Grab Random Cloth",            "Grab Random Cloth",            "MOD_CLOTH"),
    ("Cloth Inflate",       "Inflate Cloth",                "Inflate Cloth",                "MOD_CLOTH"),
    ("Cloth Push",          "Push Cloth",                   "Push Cloth",                   "MOD_CLOTH"),
    ("Cloth Expand",        "Expand/Contract Cloth",        "Expand/Contract Cloth",        "MOD_CLOTH"),
    ("Cloth Stretch",       "Stretch/Move Cloth",           "Stretch/Move Cloth",           "MOD_CLOTH"),
    ("Cloth Bend",          "Bend/Twist Cloth",             "Bend/Twist Cloth",             "MOD_CLOTH"),
    ("Cloth Bend Bound.",   "Bend Boundary Cloth",          "Bend Boundary Cloth",          "MOD_CLOTH"),
    ("Cloth Twist Bound.",  "Twist Boundary Cloth",         "Twist Boundary Cloth",         "MOD_CLOTH"),
    ("Cloth Pinch Folds",   "Pinch Folds Cloth",            "Pinch Folds Cloth",            "MOD_CLOTH"),
    ("Cloth Pinch Point",   "Pinch Point Cloth",            "Pinch Point Cloth",            "MOD_CLOTH"),
    # --- Smear & paint ---
    ("Smear",               "Smear",                        "Smear",                        "BRUSH_DATA"),
    ("Airbrush",            "Airbrush",                     "Airbrush",                     "BRUSH_DATA"),
    ("Density",             "Density",                      "Density",                      "BRUSH_DATA"),
    # --- Masking & face sets ---
    ("Mask",                "Mask",                         "Mask",                         "MOD_MASK"),
    ("Face Set Paint",      "Face Set Paint",               "Face Set Paint",               "FACE_MAPS"),
    # --- Multires ---
    ("Erase Multires",      "Erase Multires Displacement",  "Erase Multires Displacement",  "MOD_MULTIRES"),
    ("Smear Multires",      "Smear Multires Displacement",  "Smear Multires Displacement",  "MOD_MULTIRES"),
]
