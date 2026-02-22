using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEditor;

#if UNITY_EDITOR

namespace SLCustomObjects.BlenderSupport
{
    internal class FaceEntry
    {
        public string        name;
        public string        primitiveTypeName;
        public string        colorHex;
        public bool          collidable;
        public bool          visible;
        public Vector3       position;
        public Vector3       rotation;
        public Vector3       scale;

        public PrimitiveType PrimitiveType
        {
            get
            {
                PrimitiveType t;
                return Enum.TryParse(primitiveTypeName, true, out t) ? t : PrimitiveType.Cube;
            }
        }

        public Color ParsedColor
        {
            get
            {
                if (string.IsNullOrEmpty(colorHex)) return Color.white;
                if (colorHex.Length == 8)
                {
                    try
                    {
                        float r = Convert.ToInt32(colorHex.Substring(0, 2), 16) / 255f;
                        float g = Convert.ToInt32(colorHex.Substring(2, 2), 16) / 255f;
                        float b = Convert.ToInt32(colorHex.Substring(4, 2), 16) / 255f;
                        float a = Convert.ToInt32(colorHex.Substring(6, 2), 16) / 255f;
                        return new Color(r, g, b, a);
                    }
                    catch { return Color.white; }
                }
                Color c;
                return ColorUtility.TryParseHtmlString("#" + colorHex, out c) ? c : Color.white;
            }
        }
    }

    public class SLCOBlenderImporter : EditorWindow
    {
        private const string WINDOW_TITLE = "SLCO Importer";
        private const string ADDON_AUTHOR = "aliberat";
        private const string MENU_PATH    = "Blender/Map Importer (.slco)";

        private string            filePath       = "";
        private bool              groupUnderRoot = true;
        private bool              autoSelectRoot = true;
        private bool              overrideColor  = false;
        private Color             globalColor    = Color.white;
        private bool              overrideType   = false;
        private PrimitiveType     globalType     = PrimitiveType.Cube;

        private int               activeTab      = 0;
        private List<FaceEntry>   loadedFaces    = new List<FaceEntry>();
        private string            exportTime     = "";
        private string            author         = "";
        private string            searchFilter   = "";
        private bool              sortAscending  = true;
        private List<string>      importLog      = new List<string>();
        private List<GameObject>  lastImported   = new List<GameObject>();
        private Vector2           scrollPreview;
        private Vector2           scrollLog;
        private bool              sectSettings   = true;
        private bool              sectActions    = true;

        private GUIStyle _styleTitle;
        private GUIStyle _styleLogOk;
        private GUIStyle _styleLogErr;
        private GUIStyle _styleLogInfo;
        private bool     _stylesReady = false;

        private static readonly string[] TabLabels = { "Import", "Preview", "Help" };

        [MenuItem(MENU_PATH)]
        public static void OpenWindow()
        {
            var w = GetWindow<SLCOBlenderImporter>(WINDOW_TITLE);
            w.minSize = new Vector2(500, 580);
        }

        private void EnsureStyles()
        {
            if (_stylesReady) return;
            _styleTitle = new GUIStyle(EditorStyles.boldLabel)
            {
                fontSize  = 14,
                alignment = TextAnchor.MiddleCenter,
            };
            _styleLogOk = new GUIStyle(EditorStyles.wordWrappedLabel)
            {
                normal = { textColor = new Color(0.3f, 0.9f, 0.3f) },
            };
            _styleLogErr = new GUIStyle(EditorStyles.wordWrappedLabel)
            {
                normal = { textColor = new Color(0.95f, 0.3f, 0.3f) },
            };
            _styleLogInfo = new GUIStyle(EditorStyles.wordWrappedLabel)
            {
                normal = { textColor = new Color(0.75f, 0.88f, 1f) },
            };
            _stylesReady = true;
        }

        private void OnGUI()
        {
            EnsureStyles();
            DrawHeader();
            activeTab = GUILayout.Toolbar(activeTab, TabLabels, GUILayout.Height(26));
            EditorGUILayout.Space(6);
            switch (activeTab)
            {
                case 0: DrawImportTab();  break;
                case 1: DrawPreviewTab(); break;
                case 2: DrawHelpTab();    break;
            }
        }

        private void DrawHeader()
        {
            EditorGUILayout.Space(6);
            GUILayout.Label("SCP:SL — Blender Map Importer", _styleTitle);
            GUILayout.Label($"Made by {ADDON_AUTHOR}", new GUIStyle(EditorStyles.centeredGreyMiniLabel) { fontSize = 11 });
            DrawHRule(new Color(0.3f, 0.3f, 0.3f));
            EditorGUILayout.Space(4);
        }

        private void DrawImportTab()
        {
            GUILayout.Label("File", EditorStyles.boldLabel);
            EditorGUILayout.BeginHorizontal();
            var np = EditorGUILayout.TextField(filePath);
            if (np != filePath) filePath = np;
            if (GUILayout.Button("Browse", GUILayout.Width(58))) PickFile();
            if (GUILayout.Button("Reload", GUILayout.Width(52)) && File.Exists(filePath)) LoadFile(filePath);
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.Space(6);

            sectSettings = EditorGUILayout.BeginFoldoutHeaderGroup(sectSettings, "  Settings");
            EditorGUILayout.EndFoldoutHeaderGroup();
            if (sectSettings)
            {
                EditorGUI.indentLevel++;
                groupUnderRoot = EditorGUILayout.Toggle("Group Under Root Object:", groupUnderRoot);
                autoSelectRoot = EditorGUILayout.Toggle("Select Root After Import:", autoSelectRoot);
                overrideColor  = EditorGUILayout.Toggle("Override All Colors:", overrideColor);
                if (overrideColor)
                    globalColor = EditorGUILayout.ColorField(new GUIContent("Color:"), globalColor, true, true, true);
                overrideType = EditorGUILayout.Toggle("Override All Primitive Types:", overrideType);
                if (overrideType)
                    globalType = (PrimitiveType)EditorGUILayout.EnumPopup("Type:", globalType);
                EditorGUI.indentLevel--;
            }

            EditorGUILayout.Space(8);

            if (loadedFaces.Count > 0)
                EditorGUILayout.HelpBox($"Ready: {loadedFaces.Count} face-cubes loaded.", MessageType.Info);
            else
                EditorGUILayout.HelpBox("Browse and select a .slco file to begin.", MessageType.None);

            EditorGUILayout.Space(6);

            GUI.enabled = loadedFaces.Count > 0;
            GUI.backgroundColor = loadedFaces.Count > 0 ? new Color(0.15f, 0.8f, 0.15f) : new Color(0.45f, 0.45f, 0.45f);
            var btnStyle = new GUIStyle(GUI.skin.button) { fontSize = 14, fontStyle = FontStyle.Bold };
            if (GUILayout.Button("  IMPORT", btnStyle, GUILayout.Height(42)))
                RunImport();
            GUI.backgroundColor = Color.white;
            GUI.enabled = true;

            EditorGUILayout.Space(6);

            sectActions = EditorGUILayout.BeginFoldoutHeaderGroup(sectActions, "  Post-Import Actions");
            EditorGUILayout.EndFoldoutHeaderGroup();
            if (sectActions && lastImported.Count > 0)
            {
                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Select All", GUILayout.Height(24)))
                    Selection.objects = lastImported.Where(g => g != null).Cast<UnityEngine.Object>().ToArray();
                if (GUILayout.Button("Delete Last Import", GUILayout.Height(24)))
                {
                    foreach (var go in lastImported)
                        if (go != null) DestroyImmediate(go);
                    lastImported.Clear();
                    Log("Last import deleted.");
                }
                if (GUILayout.Button("Ping Root", GUILayout.Height(24)))
                {
                    var root = lastImported.FirstOrDefault(g => g != null);
                    if (root) EditorGUIUtility.PingObject(root);
                }
                EditorGUILayout.EndHorizontal();
                GUILayout.Label($"{lastImported.Count(g => g != null)} objects in scene.", EditorStyles.miniLabel);
            }

            EditorGUILayout.Space(6);
            DrawHRule(new Color(0.2f, 0.2f, 0.2f));
            GUILayout.Label("Log", EditorStyles.boldLabel);

            scrollLog = EditorGUILayout.BeginScrollView(scrollLog, GUILayout.Height(130));
            foreach (var line in importLog)
            {
                var s = line.StartsWith("  OK")   ? _styleLogOk
                      : line.StartsWith("  FAIL") ? _styleLogErr
                      : _styleLogInfo;
                GUILayout.Label(line, s);
            }
            EditorGUILayout.EndScrollView();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Clear Log",         GUILayout.Height(20))) importLog.Clear();
            if (GUILayout.Button("Copy to Clipboard", GUILayout.Height(20)))
                EditorGUIUtility.systemCopyBuffer = string.Join("\n", importLog);
            EditorGUILayout.EndHorizontal();
        }

        private void DrawPreviewTab()
        {
            if (loadedFaces.Count == 0)
            {
                EditorGUILayout.HelpBox("No file loaded.", MessageType.Info);
                return;
            }

            EditorGUILayout.BeginVertical(EditorStyles.helpBox);
            EditorGUILayout.LabelField("File:",        Path.GetFileName(filePath), EditorStyles.miniLabel);
            EditorGUILayout.LabelField("Face-Cubes:",  loadedFaces.Count.ToString(), EditorStyles.miniLabel);
            EditorGUILayout.LabelField("Exported at:", exportTime, EditorStyles.miniLabel);
            EditorGUILayout.LabelField("Author:",      author, EditorStyles.miniLabel);
            EditorGUILayout.EndVertical();

            EditorGUILayout.Space(4);

            EditorGUILayout.BeginHorizontal();
            searchFilter = EditorGUILayout.TextField(searchFilter, EditorStyles.toolbarSearchField);
            if (GUILayout.Button(sortAscending ? "A-Z" : "Z-A", GUILayout.Width(36)))
                sortAscending = !sortAscending;
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.Space(4);

            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
            GUILayout.Label("Name",     EditorStyles.toolbarButton, GUILayout.Width(180));
            GUILayout.Label("Type",     EditorStyles.toolbarButton, GUILayout.Width(70));
            GUILayout.Label("Scale",    EditorStyles.toolbarButton, GUILayout.Width(140));
            GUILayout.Label("Color",    EditorStyles.toolbarButton, GUILayout.Width(46));
            EditorGUILayout.EndHorizontal();

            var filtered = GetFiltered(searchFilter, sortAscending);
            scrollPreview = EditorGUILayout.BeginScrollView(scrollPreview);
            bool odd = false;
            foreach (var f in filtered)
            {
                var oldBg = GUI.backgroundColor;
                GUI.backgroundColor = odd ? new Color(0.87f, 0.87f, 0.87f) : Color.white;
                EditorGUILayout.BeginHorizontal(GUI.skin.box);
                GUILayout.Label(f.name,                           GUILayout.Width(180));
                GUILayout.Label(f.primitiveTypeName ?? "Cube",    GUILayout.Width(70));
                GUILayout.Label(V3S(f.scale),                     GUILayout.Width(140));
                var prevBg = GUI.backgroundColor;
                GUI.backgroundColor = f.ParsedColor;
                GUILayout.Label("", GUI.skin.button, GUILayout.Width(28), GUILayout.Height(16));
                GUI.backgroundColor = prevBg;
                EditorGUILayout.EndHorizontal();
                GUI.backgroundColor = oldBg;
                odd = !odd;
            }
            EditorGUILayout.EndScrollView();
            GUILayout.Label($"Showing {filtered.Count} / {loadedFaces.Count}", EditorStyles.centeredGreyMiniLabel);
        }

        private void DrawHelpTab()
        {
            EditorGUILayout.HelpBox(
                "HOW IT WORKS\n\n" +
                "In Blender:\n" +
                "  1. Model anything — monkey, house, car\n" +
                "  2. Select all (A)\n" +
                "  3. N-panel  ->  Map Exporter  ->  EXPORT (.slco)\n\n" +
                "  Every face of your mesh becomes ONE cube.\n" +
                "  The cube is placed at the face center,\n" +
                "  rotated to match the face normal,\n" +
                "  and scaled to the face dimensions.\n\n" +
                "In Unity:\n" +
                "  1. Open  Blender  ->  Map Importer (.slco)\n" +
                "  2. Select the .slco file\n" +
                "  3. Click IMPORT\n\n" +
                "  Each face becomes a PrimitiveComponent.\n" +
                "  Fully SCP:SL compatible.",
                MessageType.None);

            EditorGUILayout.Space(6);
            EditorGUILayout.HelpBox(
                "TIP: Enable 'Merge Quads' in Blender\n" +
                "to reduce cube count and get cleaner results.\n\n" +
                "TIP: Adjust 'Face Thickness' for how deep\n" +
                "each cube goes into the surface.",
                MessageType.Info);

            EditorGUILayout.Space(6);
            EditorGUILayout.LabelField($"Made by {ADDON_AUTHOR}", EditorStyles.boldLabel);
        }

        private void PickFile()
        {
            string p = EditorUtility.OpenFilePanel("Select .slco file", "", "slco");
            if (!string.IsNullOrEmpty(p)) { filePath = p; LoadFile(p); }
        }

        private void LoadFile(string path)
        {
            loadedFaces.Clear();
            if (!File.Exists(path)) { Log("File not found: " + path); return; }
            try
            {
                string json = File.ReadAllText(path, Encoding.UTF8);
                loadedFaces  = ParseFaces(json);
                exportTime   = ReadStr(json, "export_time");
                author       = ReadStr(json, "author");
                activeTab    = 1;
                Log($"Loaded {loadedFaces.Count} face-cubes from: {Path.GetFileName(path)}");
                Repaint();
            }
            catch (Exception e) { Log("Parse error: " + e.Message); }
        }

        private void RunImport()
        {
            importLog.Clear();
            lastImported.Clear();

            Log($"Importing {loadedFaces.Count} face-cubes...");

            Undo.SetCurrentGroupName("SLCO Import");
            int undoGroup = Undo.GetCurrentGroup();

            GameObject root = null;
            if (groupUnderRoot)
            {
                root = new GameObject(Path.GetFileNameWithoutExtension(filePath) + "_SLCO");
                Undo.RegisterCreatedObjectUndo(root, "SLCO Root");
                lastImported.Add(root);
            }

            int ok = 0, fail = 0;

            for (int i = 0; i < loadedFaces.Count; i++)
            {
                var face = loadedFaces[i];

                EditorUtility.DisplayProgressBar(
                    "SLCO Import",
                    $"Creating cube {i + 1} / {loadedFaces.Count}",
                    (float)i / loadedFaces.Count
                );

                try
                {
                    var go = SpawnFaceCube(face);
                    if (root != null) go.transform.SetParent(root.transform, true);
                    lastImported.Add(go);
                    ok++;
                }
                catch (Exception e) { fail++; Log($"  FAIL  {face.name}: {e.Message}"); }
            }

            EditorUtility.ClearProgressBar();
            Undo.CollapseUndoOperations(undoGroup);

            if (autoSelectRoot && root != null)
            {
                Selection.activeGameObject = root;
                SceneView.FrameLastActiveSceneView();
            }

            Log($"  OK  Done! {ok} cubes created, {fail} failed.");
        }

        private GameObject SpawnFaceCube(FaceEntry face)
        {
            PrimitiveType finalType  = overrideType  ? globalType  : face.PrimitiveType;
            Color         finalColor = overrideColor ? globalColor : face.ParsedColor;

            string     prefabPath = $"Assets/Resources/Blocks/Primitives/{finalType}.prefab";
            GameObject prefab     = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);

            GameObject go;
            if (prefab != null)
                go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            else
                go = GameObject.CreatePrimitive(finalType);

            go.name = face.name;

            var pc        = go.GetComponent<PrimitiveComponent>() ?? go.AddComponent<PrimitiveComponent>();
            go.tag        = finalType.ToString();
            pc.Color      = finalColor;
            pc.Collidable = face.collidable;
            pc.Visible    = face.visible;

            go.transform.localPosition    = face.position;
            go.transform.localEulerAngles = face.rotation;
            go.transform.localScale       = face.scale;

            Undo.RegisterCreatedObjectUndo(go, "SLCO Cube");
            return go;
        }

        private List<FaceEntry> ParseFaces(string json)
        {
            var result = new List<FaceEntry>();
            int start  = json.IndexOf("\"objects\"");
            if (start < 0) throw new Exception("'objects' not found.");

            int i = start;
            while (i < json.Length)
            {
                int bs = json.IndexOf('{', i);
                if (bs < 0) break;
                int depth = 0, be = bs;
                for (int k = bs; k < json.Length; k++)
                {
                    if (json[k] == '{') depth++;
                    else if (json[k] == '}') { depth--; if (depth == 0) { be = k; break; } }
                }
                if (be == bs) break;

                string block = json.Substring(bs, be - bs + 1);
                if (block.Contains("\"name\""))
                {
                    var entry = new FaceEntry
                    {
                        name              = ReadStr(block, "name"),
                        primitiveTypeName = ReadStr(block, "primitive"),
                        colorHex          = ReadStr(block, "color"),
                        collidable        = ReadBool(block, "collidable", true),
                        visible           = ReadBool(block, "visible",    true),
                        position          = ReadVec3(block, "position"),
                        rotation          = ReadVec3(block, "rotation"),
                        scale             = ReadVec3(block, "scale"),
                    };
                    if (entry.scale == Vector3.zero) entry.scale = Vector3.one;
                    result.Add(entry);
                }
                i = be + 1;
            }
            return result;
        }

        private List<FaceEntry> GetFiltered(string filter, bool asc)
        {
            var result = string.IsNullOrEmpty(filter)
                ? new List<FaceEntry>(loadedFaces)
                : loadedFaces.Where(o => o.name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0).ToList();
            result.Sort((a, b) => asc
                ? string.Compare(a.name, b.name, StringComparison.Ordinal)
                : string.Compare(b.name, a.name, StringComparison.Ordinal));
            return result;
        }

        static string ReadStr(string json, string key)
        {
            int i = json.IndexOf("\"" + key + "\""); if (i < 0) return "";
            int col  = json.IndexOf(':', i); if (col < 0) return "";
            int next = col + 1;
            while (next < json.Length && json[next] == ' ') next++;
            if (next >= json.Length || json[next] != '"') return "";
            int q2 = json.IndexOf('"', next + 1); if (q2 < 0) return "";
            return json.Substring(next + 1, q2 - next - 1);
        }

        static bool ReadBool(string json, string key, bool fallback)
        {
            int i = json.IndexOf("\"" + key + "\""); if (i < 0) return fallback;
            int col = json.IndexOf(':', i); if (col < 0) return fallback;
            int s = col + 1;
            while (s < json.Length && json[s] == ' ') s++;
            if (s + 3 < json.Length && json.Substring(s, 4) == "true")  return true;
            if (s + 4 < json.Length && json.Substring(s, 5) == "false") return false;
            return fallback;
        }

        static Vector3 ReadVec3(string json, string key)
        {
            int i = json.IndexOf("\"" + key + "\""); if (i < 0) return Vector3.zero;
            int open  = json.IndexOf('[', i);
            int close = json.IndexOf(']', open);
            if (open < 0 || close < 0) return Vector3.zero;
            var parts = json.Substring(open + 1, close - open - 1).Split(',');
            if (parts.Length < 3) return Vector3.zero;
            float x = 0, y = 0, z = 0;
            var ic = System.Globalization.CultureInfo.InvariantCulture;
            var ns = System.Globalization.NumberStyles.Float;
            float.TryParse(parts[0].Trim(), ns, ic, out x);
            float.TryParse(parts[1].Trim(), ns, ic, out y);
            float.TryParse(parts[2].Trim(), ns, ic, out z);
            return new Vector3(x, y, z);
        }

        static string V3S(Vector3 v) => $"({v.x:F2}, {v.y:F2}, {v.z:F2})";

        static void DrawHRule(Color col)
        {
            var rect = EditorGUILayout.GetControlRect(false, 1f);
            EditorGUI.DrawRect(rect, col);
            EditorGUILayout.Space(3);
        }

        private void Log(string msg)
        {
            importLog.Add(msg);
            Debug.Log("[SLCOImporter] " + msg);
            Repaint();
        }
    }
}

#endif
