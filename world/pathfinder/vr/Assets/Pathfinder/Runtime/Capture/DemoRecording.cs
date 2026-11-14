using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace Pathfinder.Capture
{
    /// One hand in one sample of a demonstration.
    public struct DemoHand
    {
        public Vector3 p;
        public Quaternion q;
        /// 0 (open) to 1 (closed): controller trigger or grip, or the hand's strongest pinch.
        public float grip;
        /// Newtons from a force glove; negative when no glove measured it.
        public float forceN;
        public bool tracked;
    }

    public struct DemoSample
    {
        public float t;
        public Vector3 headP;
        public Quaternion headQ;
        public DemoHand left, right;
    }

    /// A demonstration as the backend's `POST /demos` takes it (`capture.recording/1`, read by the capture stream's
    /// processing). Positions are metres and rotations x, y, z, w quaternions in `frame`: "scene" is the loaded scan's
    /// own frame (glTF: right-handed, +Y up), "room" is the headset's tracking space when no scan is loaded, converted
    /// to the same handedness. Pure data and text: no scene access, so it runs in EditMode tests.
    public class DemoRecording
    {
        public const string Schema = "capture.recording/1";

        public string id, kind = "path", chore = "", site = "", frame = "scene", hand = "right", input = "hands", glove;
        public float rateHz = 30f;
        public float? floorY;
        public bool hasAnchor, anchorHasNormal;
        public Vector3 anchorP, anchorNormal;
        public string anchorLabel;
        public readonly List<DemoSample> samples = new List<DemoSample>(1024);

        public float Duration => samples.Count < 2 ? 0f : samples[samples.Count - 1].t - samples[0].t;

        /// Unity (left-handed) → glTF (right-handed): mirror X, as glTFast does for the scan's meshes.
        public static Vector3 ToGltf(Vector3 v) => new Vector3(-v.x, v.y, v.z);

        /// The same mirror for a rotation: a reflection across the YZ plane flips the y and z parts.
        public static Quaternion ToGltf(Quaternion q) => new Quaternion(q.x, -q.y, -q.z, q.w);

        public string ToJson()
        {
            var sb = new StringBuilder(256 + samples.Count * 330);
            sb.Append("{\"schema\":\"").Append(Schema).Append("\",\"id\":").Append(Str(id))
              .Append(",\"kind\":").Append(Str(kind)).Append(",\"chore\":").Append(Str(chore))
              .Append(",\"site\":").Append(Str(site)).Append(",\"frame\":").Append(Str(frame))
              .Append(",\"rate_hz\":").Append(Num(rateHz)).Append(",\"hand\":").Append(Str(hand))
              .Append(",\"floor_y\":").Append(floorY.HasValue ? Num(floorY.Value) : "null")
              .Append(",\"device\":{\"headset\":").Append(Str(SystemInfo.deviceModel)).Append(",\"input\":").Append(Str(input))
              .Append(",\"glove\":").Append(glove == null ? "null" : Str(glove)).Append("},\"anchor\":");
            if (!hasAnchor) sb.Append("null");
            else
            {
                sb.Append("{\"p\":").Append(Vec(anchorP)).Append(",\"normal\":").Append(anchorHasNormal ? Vec(anchorNormal) : "null")
                  .Append(",\"label\":").Append(anchorLabel == null ? "null" : Str(anchorLabel)).Append('}');
            }
            sb.Append(",\"samples\":[");
            for (int i = 0; i < samples.Count; i++)
            {
                var s = samples[i];
                if (i > 0) sb.Append(',');
                sb.Append("{\"t\":").Append(Num(s.t)).Append(",\"head\":{\"p\":").Append(Vec(s.headP)).Append(",\"q\":").Append(Quat(s.headQ))
                  .Append("},\"left\":");
                Hand(sb, s.left);
                sb.Append(",\"right\":");
                Hand(sb, s.right);
                sb.Append('}');
            }
            return sb.Append("]}").ToString();
        }

        static void Hand(StringBuilder sb, DemoHand h)
        {
            sb.Append("{\"p\":").Append(Vec(h.p)).Append(",\"q\":").Append(Quat(h.q)).Append(",\"grip\":").Append(Num(h.grip))
              .Append(",\"force_n\":").Append(h.forceN >= 0f ? Num(h.forceN) : "null")
              .Append(",\"tracked\":").Append(h.tracked ? "true" : "false").Append('}');
        }

        static string Num(float v) => (float.IsNaN(v) || float.IsInfinity(v) ? 0f : v).ToString("0.####", CultureInfo.InvariantCulture);
        static string Vec(Vector3 v) => $"[{Num(v.x)},{Num(v.y)},{Num(v.z)}]";

        static string Quat(Quaternion q) =>
            "[" + q.x.ToString("0.#####", CultureInfo.InvariantCulture) + "," + q.y.ToString("0.#####", CultureInfo.InvariantCulture) + "," +
            q.z.ToString("0.#####", CultureInfo.InvariantCulture) + "," + q.w.ToString("0.#####", CultureInfo.InvariantCulture) + "]";

        static string Str(string s)
        {
            if (s == null) return "\"\"";
            var sb = new StringBuilder(s.Length + 2).Append('"');
            foreach (char c in s)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c < ' ') sb.Append(' ');
                else sb.Append(c);
            }
            return sb.Append('"').ToString();
        }
    }
}
