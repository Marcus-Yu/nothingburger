using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace Pathfinder.Editor
{
    /// Batch-mode build of the Quest APK, for `unity build --execute-method Pathfinder.Editor.CiBuild.Android`.
    /// Does what the README's manual steps do: Wire Main Scene, then a Development Android build of the scenes in
    /// Build Settings. Output path: `-buildOutput <path>` (default Builds/Pathfinder.apk). `-skipWire` leaves the
    /// committed scene as it is.
    public static class CiBuild
    {
        public static void Android()
        {
            var args = Environment.GetCommandLineArgs();
            string output = "Builds/Pathfinder.apk";
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-buildOutput") output = args[i + 1];

            if (!args.Contains("-skipWire"))
            {
                var wired = MainSceneBuilder.Wire();
                Debug.Log($"CiBuild: Wire Main Scene -> {wired}");
            }

            var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = output,
                target = BuildTarget.Android,
                targetGroup = BuildTargetGroup.Android,
                options = BuildOptions.Development,
            });
            var s = report.summary;
            Debug.Log($"CiBuild: {s.result}, {s.totalErrors} errors, {s.totalSize / (1024 * 1024)} MB, {s.totalTime.TotalMinutes:0.0} min -> {s.outputPath}");
            if (s.result != BuildResult.Succeeded) EditorApplication.Exit(1);
        }
    }
}
