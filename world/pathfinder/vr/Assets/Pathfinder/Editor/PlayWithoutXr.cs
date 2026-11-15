using UnityEditor;
using UnityEditor.XR.Management;
using UnityEngine.XR.Management;
using UnityEngine;

namespace Pathfinder.Editor
{
    /// Pathfinder ▸ Dev ▸ Play Without XR: the next Play session skips XR initialisation (no Meta XR Simulator, no OpenXR
    /// session), and the setting is restored when Play stops. For a second Editor (a git worktree, SPEC §5 lanes) that
    /// must not start its own Simulator session next to the XR lane's, but still needs to verify runtime code
    /// (HTTP scene loading, glTFast, snapping) through `unity command eval`. Nothing is saved to the XR settings asset.
    [InitializeOnLoad]
    public static class PlayWithoutXr
    {
        const string Key = "Pathfinder.PlayWithoutXr";
        const string RestoreKey = "Pathfinder.PlayWithoutXr.Restore";

        static PlayWithoutXr() => EditorApplication.playModeStateChanged += OnPlayMode;

        public static bool Enabled
        {
            get => SessionState.GetBool(Key, false);
            set => SessionState.SetBool(Key, value);
        }

        [MenuItem("Pathfinder/Dev/Play Without XR")]
        static void Toggle() { Enabled = !Enabled; Debug.Log($"[Pathfinder] Play without XR: {Enabled}"); }

        [MenuItem("Pathfinder/Dev/Play Without XR", true)]
        static bool ToggleValidate() { Menu.SetChecked("Pathfinder/Dev/Play Without XR", Enabled); return true; }

        static XRGeneralSettings Settings =>
            XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Standalone);

        static void OnPlayMode(PlayModeStateChange change)
        {
            var s = Settings;
            if (s == null) return;
            if (change == PlayModeStateChange.ExitingEditMode && Enabled)
            {
                SessionState.SetBool(RestoreKey, s.InitManagerOnStart);
                s.InitManagerOnStart = false;
                Debug.Log("[Pathfinder] Play without XR: XR initialisation skipped for this session");
            }
            else if (change == PlayModeStateChange.EnteredEditMode && SessionState.GetBool(RestoreKey, false))
            {
                s.InitManagerOnStart = true;
                SessionState.EraseBool(RestoreKey);
            }
        }
    }
}
