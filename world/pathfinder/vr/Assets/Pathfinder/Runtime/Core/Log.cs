using System;
using System.Globalization;
using UnityEngine;

namespace Pathfinder.Core
{
    /// Project logging. Acceptance checks use one grep-able line each (SPEC §7):
    /// <c>[Pathfinder.Check] M2.tape.window value=1.5003 expected=1.500 tol=0.010 PASS</c>
    public static class Log
    {
        public static void Info(string message) => Debug.Log($"[Pathfinder] {message}");
        public static void Warn(string message) => Debug.LogWarning($"[Pathfinder] {message}");
        public static void Error(string message) => Debug.LogError($"[Pathfinder] {message}");

        public static bool Check(string id, double value, double expected, double tolerance)
        {
            bool pass = Math.Abs(value - expected) <= tolerance;
            Debug.Log(FormatCheck(id, value, expected, tolerance, pass));
            return pass;
        }

        public static bool Check(string id, bool pass, string detail)
        {
            Debug.Log($"[Pathfinder.Check] {id} {detail} {(pass ? "PASS" : "FAIL")}");
            return pass;
        }

        public static string FormatCheck(string id, double value, double expected, double tolerance, bool pass)
        {
            var c = CultureInfo.InvariantCulture;
            return $"[Pathfinder.Check] {id} value={value.ToString("0.0000", c)} expected={expected.ToString("0.000", c)} " +
                   $"tol={tolerance.ToString("0.000", c)} {(pass ? "PASS" : "FAIL")}";
        }
    }
}
