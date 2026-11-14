using System;
using System.Collections;
using System.Text;
using Pathfinder.Core;
using Pathfinder.Input;
using Pathfinder.Tools;
using Pathfinder.UI;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
using IsdkHand = Oculus.Interaction.Input.Hand;
using IsdkJoint = Oculus.Interaction.Input.HandJointId;

namespace Pathfinder.Capture
{
    /// Films a demonstration of a chore done for real: the wearer's head and both hands, 30 times a second, with every
    /// finger joint and how tightly each hand is closed.
    ///
    /// Someone asks for a demonstration through the backend (`POST /demos/request`, from the website or the agent).
    /// This polls `GET /demos/control`. When a request arrives it switches the headset to passthrough, so the wearer
    /// sees the room they are in, and shows the task in front of them with a countdown. Recording starts when the
    /// countdown ends: no gesture is needed to begin, so nothing starts by accident and the hands are free for the
    /// task. It ends on the done gesture (B / Y, or a thumb and middle finger pinch), at the request's time limit, or
    /// on `POST /demos/stop` (the website's Stop button). The recording is uploaded and the headset goes back to where
    /// it was.
    ///
    /// While a demonstration is under way no tool is equipped. Creates itself after the scene loads: nothing to wire.
    public class DemoRecorder : MonoBehaviour
    {
        public enum State { Idle, Briefing, Recording, Uploading }

        [Serializable] class Request { public string id, chore, kind, prompt; public float max_seconds; }
        [Serializable] class Control { public Request request; public bool stop; }

        public const float RateHz = 30f;
        public float pollSeconds = 1f;
        [Tooltip("Seconds the task is shown before recording starts.")]
        public float briefingSeconds = 8f;

        public State Current { get; private set; } = State.Idle;
        public string LastResult { get; private set; } = "";

        Request m_Request;
        DemoRecording m_Recording;
        ToolInputHub m_Hub;
        OvrToolInputSource m_Source;
        IsdkHand[] m_Skeletons = Array.Empty<IsdkHand>();
        static readonly int JointCount = Oculus.Interaction.Input.Constants.NUM_HAND_JOINTS;
        ToolKind m_ToolBefore = ToolKind.None;
        AppMode m_ModeBefore = AppMode.Passthrough;
        TextMeshPro m_Hud;
        float m_Started, m_BriefingEnds, m_NextSample, m_NextPoll, m_HudUntil;
        bool m_StopAsked, m_Polling, m_HudPlaced;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (FindFirstObjectByType<DemoRecorder>() != null) return;
            var go = new GameObject("DemoRecorder");
            DontDestroyOnLoad(go);
            go.AddComponent<DemoRecorder>();
        }

        void OnEnable() => Services.Register(this);

        void OnDisable()
        {
            if (m_Hub != null) m_Hub.ButtonDown -= OnButton;
            m_Hub = null;
            Services.Unregister(this);
        }

        void Hook()
        {
            if (m_Hub != null) return;
            m_Hub = Services.Get<ToolInputHub>();
            m_Source = FindFirstObjectByType<OvrToolInputSource>();
            if (m_Hub != null) m_Hub.ButtonDown += OnButton;
        }

        void Update()
        {
            Hook();
            float now = Time.unscaledTime;
            if (!m_Polling && now >= m_NextPoll && Current != State.Uploading)
            {
                m_NextPoll = now + pollSeconds;
                StartCoroutine(Poll());
            }
            FollowHead();
            if (Current == State.Briefing)
            {
                if (m_StopAsked) { Cancel(); return; }
                int left = Mathf.CeilToInt(m_BriefingEnds - now);
                if (left <= 0) Begin();
                else Say($"<b>Show me: {What()}</b>\nDo it for real, on the thing in front of you.\nRecording starts in {left}");
            }
            else if (Current == State.Recording)
            {
                if (now >= m_NextSample)
                {
                    m_NextSample = Mathf.Max(m_NextSample + 1f / RateHz, now - 1f / RateHz);
                    m_Recording.samples.Add(Sample(now - m_Started));
                }
                int t = (int)(now - m_Started), max = (int)m_Request.max_seconds;
                Say($"<color=#FF5A4E>●</color> Recording: {What()}   {t / 60}:{t % 60:00} / {max / 60}:{max % 60:00}\n" +
                    (Squeeze ? "It stops by itself when the time is up" : "Thumb and middle finger pinch when you're done"));
                if (m_StopAsked || now - m_Started >= m_Request.max_seconds) Finish();
            }
            else if (m_Hud != null && m_Hud.gameObject.activeSelf && now >= m_HudUntil) m_Hud.gameObject.SetActive(false);
        }

        string What() => m_Request == null ? "" : string.IsNullOrEmpty(m_Request.prompt) ? m_Request.chore : m_Request.prompt;

        IEnumerator Poll()
        {
            m_Polling = true;
            string url = ServerConfig.Current.TrimEnd('/') + "/demos/control";
            if (Current != State.Idle && m_Request != null) url += "?active=" + UnityWebRequest.EscapeURL(m_Request.id);
            using (var req = UnityWebRequest.Get(url))
            {
                req.timeout = 4;
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                {
                    Control c = null;
                    try { c = JsonUtility.FromJson<Control>(req.downloadHandler.text); } catch (Exception) { }
                    if (c != null)
                    {
                        if (Current != State.Idle && c.stop) m_StopAsked = true;
                        if (Current == State.Idle && c.request != null && !string.IsNullOrEmpty(c.request.id)) Brief(c.request);
                    }
                }
            }
            m_Polling = false;
        }

        // ---------------- the flow ----------------

        /// A request arrived: passthrough, hands free, the task and a countdown in front of the wearer.
        void Brief(Request request)
        {
            m_Request = request;
            if (m_Request.max_seconds <= 0f) m_Request.max_seconds = 30f;
            m_ModeBefore = AppState.Mode;
            AppState.Set(AppMode.Passthrough);
            if (Services.TryGet<ToolManager>(out var tools))
            {
                m_ToolBefore = tools.Active;
                tools.Equip(ToolKind.None);
            }
            m_StopAsked = false;
            m_BriefingEnds = Time.unscaledTime + briefingSeconds;
            Current = State.Briefing;
            Log.Info($"DemoRecorder: briefing {request.id} ({request.kind}) \"{request.chore}\"");
        }

        void Begin()
        {
            bool controllers = OVRInput.IsControllerConnected(OVRInput.Controller.RTouch) || OVRInput.IsControllerConnected(OVRInput.Controller.LTouch);
            m_Recording = new DemoRecording
            {
                id = m_Request.id, kind = string.IsNullOrEmpty(m_Request.kind) ? "path" : m_Request.kind, chore = m_Request.chore,
                // Passthrough: the wearer is in their own room, so positions are the room's (the headset's tracking
                // space), not the scan's. No anchor is marked: the processing takes the target from where the work happened.
                site = "", frame = "room", rateHz = RateHz, hand = "", input = controllers ? "controllers" : "hands",
            };
            var rig = FindFirstObjectByType<OVRCameraRig>();
            if (rig != null && rig.trackingSpace != null) m_Recording.floorY = ToFrame(rig.trackingSpace.position).y;
            m_Skeletons = FindObjectsByType<IsdkHand>(FindObjectsSortMode.None);
            m_Recording.jointNames = new string[JointCount];
            for (int j = 0; j < JointCount; j++) m_Recording.jointNames[j] = ((IsdkJoint)j).ToString();
            m_Started = Time.unscaledTime;
            m_NextSample = m_Started;
            StartCoroutine(TellStarted(m_Request.id));   // the laptop's clock at this moment lines the gloves up
            Current = State.Recording;
            Log.Info($"DemoRecorder: recording {m_Request.id} in passthrough, up to {m_Request.max_seconds:0} s");
        }

        bool Squeeze => m_Request != null && m_Request.kind == "squeeze";

        void OnButton(ToolHand hand, ToolButton button)
        {
            // Give the chore two seconds before the done gesture counts. A squeeze has no done gesture: gripping
            // something brings the thumb and middle finger together, which read as "done" three seconds in.
            if (Squeeze) return;
            if (Current == State.Recording && button == ToolButton.Finish && Time.unscaledTime - m_Started > 2f) m_StopAsked = true;
        }

        void Cancel()
        {
            Log.Info($"DemoRecorder: {m_Request.id} cancelled before recording");
            Say("Demonstration cancelled.", 3f);
            Restore();
            m_Request = null;
            Current = State.Idle;
        }

        void Finish()
        {
            Current = State.Uploading;
            Say("Saving the demonstration...", 30f);
            StartCoroutine(Upload(m_Recording));
        }

        void Restore()
        {
            AppState.Set(m_ModeBefore);
            if (Services.TryGet<ToolManager>(out var tools)) tools.Equip(m_ToolBefore == ToolKind.None ? ToolManager.Default : m_ToolBefore);
        }

        static IEnumerator TellStarted(string id)
        {
            string url = ServerConfig.Current.TrimEnd('/') + "/demos/started?id=" + UnityWebRequest.EscapeURL(id);
            using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST) { downloadHandler = new DownloadHandlerBuffer(), timeout = 3 })
                yield return req.SendWebRequest();
        }

        IEnumerator Upload(DemoRecording recording)
        {
            string summary = $"{recording.Duration:0.0} s";
            using (var req = new UnityWebRequest(ServerConfig.Current.TrimEnd('/') + "/demos", UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(recording.ToJson())) { contentType = "application/json" },
                downloadHandler = new DownloadHandlerBuffer(),
                timeout = 30,
            })
            {
                yield return req.SendWebRequest();
                bool ok = req.result == UnityWebRequest.Result.Success;
                LastResult = ok ? $"saved {recording.id}: {summary}, {recording.samples.Count} samples" : $"upload failed ({req.responseCode} {req.error}): {summary}";
                Say(ok ? $"<b>Saved.</b> {summary} recorded.\nYou can take the headset off." : "Couldn't upload the demonstration.\nIs the laptop reachable?", 6f);
                Log.Info($"DemoRecorder: {LastResult}");
            }
            Restore();
            m_Recording = null;
            m_Request = null;
            Current = State.Idle;
        }

        // ---------------- the text in front of the wearer ----------------

        void Say(string text, float seconds = 1f)
        {
            if (m_Hud == null)
            {
                m_Hud = UiText.Create(transform, "DemoHud", text, TypeRole.Title, 1.1f, ColorRole.TextPrimary,
                    TextAlignmentOptions.Center, width: 0.9f, weight: Weight.Medium);
                m_Hud.outlineWidth = 0.2f;   // readable over a bright room
                m_Hud.outlineColor = new Color32(0, 0, 0, 220);
                m_HudPlaced = false;
            }
            if (!m_Hud.gameObject.activeSelf) { m_Hud.gameObject.SetActive(true); m_HudPlaced = false; }
            if (m_Hud.text != text) m_Hud.text = text;
            m_HudUntil = Time.unscaledTime + seconds;
        }

        /// The text floats ahead of the wearer, a little above eye level so the hands and the task stay in view, and
        /// drifts after the head instead of being glued to it.
        void FollowHead()
        {
            if (m_Hud == null || !m_Hud.gameObject.activeSelf || Camera.main == null) return;
            var head = Camera.main.transform;
            Vector3 flat = Vector3.ProjectOnPlane(head.forward, Vector3.up);
            if (flat.sqrMagnitude < 1e-4f) flat = Vector3.ProjectOnPlane(head.up, Vector3.up);
            Vector3 target = head.position + flat.normalized * 1.1f + Vector3.up * 0.22f;
            var t = m_Hud.transform;
            t.position = m_HudPlaced ? Vector3.Lerp(t.position, target, 1f - Mathf.Exp(-6f * Time.unscaledDeltaTime)) : target;
            m_HudPlaced = true;
            t.rotation = Quaternion.LookRotation(t.position - head.position, Vector3.up);
        }

        // ---------------- sampling ----------------

        /// Tracking space → the recording's right-handed frame.
        static Vector3 ToFrame(Vector3 world) => DemoRecording.ToGltf(world);
        static Quaternion ToFrame(Quaternion world) => DemoRecording.ToGltf(world);

        DemoSample Sample(float t)
        {
            var s = new DemoSample { t = t, headQ = Quaternion.identity };
            var head = Camera.main != null ? Camera.main.transform : null;
            if (head != null)
            {
                s.headP = ToFrame(head.position);
                s.headQ = ToFrame(head.rotation);
            }
            s.left = Hand(ToolHand.Left, OVRInput.Controller.LTouch, m_Source != null ? m_Source.leftHand : null);
            s.right = Hand(ToolHand.Right, OVRInput.Controller.RTouch, m_Source != null ? m_Source.rightHand : null);
            return s;
        }

        DemoHand Hand(ToolHand hand, OVRInput.Controller controller, OVRHand ovrHand)
        {
            var h = new DemoHand { q = Quaternion.identity, forceN = -1f };
            if (m_Hub == null || !m_Hub.TryGetGrip(hand, out var grip)) return h;
            h.tracked = true;
            h.p = ToFrame(grip.position);
            h.q = ToFrame(grip.rotation);
            if (OVRInput.IsControllerConnected(controller))
            {
                h.grip = Mathf.Max(OVRInput.Get(OVRInput.Axis1D.PrimaryIndexTrigger, controller),
                    OVRInput.Get(OVRInput.Axis1D.PrimaryHandTrigger, controller));
            }
            else if (ovrHand != null && ovrHand.IsTracked)
            {
                // A closing hand shows up as its fingers nearing the thumb: the strongest pinch stands in for the grasp.
                float g = 0f;
                for (var f = OVRHand.HandFinger.Index; f <= OVRHand.HandFinger.Pinky; f++) g = Mathf.Max(g, ovrHand.GetFingerPinchStrength(f));
                h.grip = g;
                h.joints = Joints(hand);
            }
            return h;
        }

        /// The tracked skeleton of that hand, joint by joint, in the recording's frame; null when none is tracked.
        Vector3[] Joints(ToolHand hand)
        {
            var side = hand == ToolHand.Left ? Oculus.Interaction.Input.Handedness.Left : Oculus.Interaction.Input.Handedness.Right;
            foreach (var skeleton in m_Skeletons)
            {
                if (skeleton == null || !skeleton.isActiveAndEnabled || skeleton.Handedness != side || !skeleton.IsTrackedDataValid) continue;
                var joints = new Vector3[JointCount];
                for (int j = 0; j < JointCount; j++)
                {
                    if (!skeleton.GetJointPose((IsdkJoint)j, out var pose)) return null;
                    joints[j] = ToFrame(pose.position);
                }
                return joints;
            }
            return null;
        }
    }
}
