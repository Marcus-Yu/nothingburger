using System;
using System.Collections;
using System.Text;
using Pathfinder.Core;
using Pathfinder.Input;
using Pathfinder.Scene;
using Pathfinder.Tools;
using Pathfinder.UI;
using IsdkHand = Oculus.Interaction.Input.Hand;
using IsdkJoint = Oculus.Interaction.Input.HandJointId;
using UnityEngine;
using UnityEngine.Networking;

namespace Pathfinder.Capture
{
    /// Films a demonstration of a chore: the wearer's head and both hands, 30 times a second, with how tightly each
    /// hand is closed, in the loaded scan's frame.
    ///
    /// Someone asks for a demonstration through the backend (`POST /demos/request`, the agent or a person at the
    /// laptop). This polls `GET /demos/control`, shows the request, and waits for the wearer to mark the thing they
    /// will work on with one pinch or trigger pull: where that ray lands on the scan is the anchor, or the hand's own
    /// position when there is no scan under it. Recording runs until the done gesture (B / Y, or a thumb and middle
    /// finger pinch), the request's time limit, or `POST /demos/stop`, then the recording is uploaded.
    ///
    /// While armed or recording no tool is equipped, so the hands' pinches do the chore instead of measuring or moving.
    /// Creates itself after the scene loads: nothing to wire.
    public class DemoRecorder : MonoBehaviour
    {
        public enum State { Idle, Armed, Recording, Uploading }

        [Serializable] class Request { public string id, chore, kind, prompt; public float max_seconds; }
        [Serializable] class Control { public Request request; public bool stop; }

        public const float RateHz = 30f;
        public float pollSeconds = 1f;
        [Tooltip("Scan metres. A marking ray that lands farther than this from the marking hand is not the target.")]
        public float anchorReach = 1.2f;

        public State Current { get; private set; } = State.Idle;
        public string LastResult { get; private set; } = "";

        Request m_Request;
        DemoRecording m_Recording;
        ToolInputHub m_Hub;
        OvrToolInputSource m_Source;
        IsdkHand[] m_Skeletons = Array.Empty<IsdkHand>();
        static readonly int JointCount = Oculus.Interaction.Input.Constants.NUM_HAND_JOINTS;
        ToolKind m_ToolBefore = ToolKind.None;
        float m_Started, m_NextSample, m_NextPoll;
        bool m_StopAsked, m_Polling;

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
            Unhook();
            Services.Unregister(this);
        }

        void Hook()
        {
            if (m_Hub != null) return;
            m_Hub = Services.Get<ToolInputHub>();
            m_Source = FindFirstObjectByType<OvrToolInputSource>();
            if (m_Hub == null) return;
            m_Hub.PressStart += OnPressStart;
            m_Hub.ButtonDown += OnButton;
        }

        void Unhook()
        {
            if (m_Hub == null) return;
            m_Hub.PressStart -= OnPressStart;
            m_Hub.ButtonDown -= OnButton;
            m_Hub = null;
        }

        void Update()
        {
            Hook();
            float now = Time.unscaledTime;
            if (!m_Polling && now >= m_NextPoll && (Current == State.Idle || Current == State.Recording))
            {
                m_NextPoll = now + pollSeconds;
                StartCoroutine(Poll());
            }
            if (Current != State.Recording) return;
            if (now >= m_NextSample)
            {
                m_NextSample = Mathf.Max(m_NextSample + 1f / RateHz, now - 1f / RateHz);
                m_Recording.samples.Add(Sample(now - m_Started));
            }
            if (m_StopAsked || now - m_Started >= m_Request.max_seconds) Finish();
        }

        IEnumerator Poll()
        {
            m_Polling = true;
            string url = ServerConfig.Current.TrimEnd('/') + "/demos/control";
            if (Current == State.Recording) url += "?active=" + UnityWebRequest.EscapeURL(m_Request.id);
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
                        if (Current == State.Recording && c.stop) m_StopAsked = true;
                        if (Current == State.Idle && c.request != null && !string.IsNullOrEmpty(c.request.id)) Arm(c.request);
                    }
                }
            }
            m_Polling = false;
        }

        void Arm(Request request)
        {
            m_Request = request;
            if (m_Request.max_seconds <= 0f) m_Request.max_seconds = 30f;
            if (Services.TryGet<ToolManager>(out var tools))
            {
                m_ToolBefore = tools.Active;
                tools.Equip(ToolKind.None);
            }
            Current = State.Armed;
            string what = string.IsNullOrEmpty(request.prompt) ? request.chore : request.prompt;
            UiToast.Show($"Show me: {what}. Pinch at the thing you'll work on to start.", ColorRole.Info);
            Log.Info($"DemoRecorder: armed {request.id} ({request.kind}) \"{request.chore}\"");
        }

        void OnPressStart(ToolHand hand, Pose pointer)
        {
            if (Current != State.Armed) return;
            var content = Content();
            m_Recording = new DemoRecording
            {
                id = m_Request.id, kind = string.IsNullOrEmpty(m_Request.kind) ? "path" : m_Request.kind, chore = m_Request.chore,
                site = Services.TryGet<SceneStreamer>(out var streamer) && content != null ? streamer.Site ?? "" : "",
                frame = content != null ? "scene" : "room", rateHz = RateHz,
                hand = hand == ToolHand.Left ? "left" : "right",
                input = OVRInput.IsControllerConnected(OVRInput.Controller.RTouch) || OVRInput.IsControllerConnected(OVRInput.Controller.LTouch)
                    ? "controllers" : "hands",
            };
            // The anchor: where the marking ray lands on the scan, when that is within arm's reach of the marking hand
            // (the wearer is working on something in the scan). A hit across the room means they are marking a real
            // thing in front of them that the scan does not have there: then the anchor is the hand itself.
            Vector3 handAt = m_Hub != null && m_Hub.TryGetGrip(hand, out var marking) ? marking.position : pointer.position;
            if (content != null && AppState.Mode == AppMode.World &&
                SnapService.TryRaySnap(new Ray(pointer.position, pointer.forward), out var hit, 20f, features: false) &&
                Vector3.Distance(hit.point, handAt) <= anchorReach * Mathf.Max(content.lossyScale.x, 1e-6f))
            {
                m_Recording.anchorP = ToFrame(content, hit.point);
                m_Recording.anchorNormal = DemoRecording.ToGltf(content.InverseTransformDirection(hit.normal)).normalized;
                m_Recording.anchorHasNormal = true;
            }
            else
            {
                m_Recording.anchorP = ToFrame(content, handAt);
            }
            m_Recording.hasAnchor = true;
            // Finger joints come from the Interaction SDK's hand skeletons (hands only: a controller has none).
            m_Skeletons = FindObjectsByType<IsdkHand>(FindObjectsSortMode.None);
            m_Recording.jointNames = new string[JointCount];
            for (int j = 0; j < JointCount; j++) m_Recording.jointNames[j] = ((IsdkJoint)j).ToString();
            // The floor the wearer stands on: the tracking origin is at floor level, so the rig's own height is it.
            var rig = FindFirstObjectByType<OVRCameraRig>();
            if (rig != null && rig.trackingSpace != null) m_Recording.floorY = ToFrame(content, rig.trackingSpace.position).y;
            m_Started = Time.unscaledTime;
            m_NextSample = m_Started;
            m_StopAsked = false;
            Current = State.Recording;
            UiToast.Show((m_Recording.anchorHasNormal ? "Target marked on the scan. " : "Target marked at your hand. ") +
                "Recording: thumb and middle finger pinch (or B / Y) when you're done.", ColorRole.Info);
            Log.Info($"DemoRecorder: recording {m_Request.id} in the {m_Recording.frame} frame, anchor {m_Recording.anchorP:F2}");
        }

        void OnButton(ToolHand hand, ToolButton button)
        {
            // Give the chore a second before the done gesture counts: the pinch that started it is still closing.
            if (Current == State.Recording && button == ToolButton.Finish && Time.unscaledTime - m_Started > 1f) m_StopAsked = true;
        }

        void Finish()
        {
            Current = State.Uploading;
            if (Services.TryGet<ToolManager>(out var tools)) tools.Equip(m_ToolBefore == ToolKind.None ? ToolManager.Default : m_ToolBefore);
            StartCoroutine(Upload(m_Recording));
        }

        IEnumerator Upload(DemoRecording recording)
        {
            string summary = $"{recording.Duration:0.0} s, {recording.samples.Count} samples";
            using (var req = new UnityWebRequest(ServerConfig.Current.TrimEnd('/') + "/demos", UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(recording.ToJson())) { contentType = "application/json" },
                downloadHandler = new DownloadHandlerBuffer(),
                timeout = 30,
            })
            {
                yield return req.SendWebRequest();
                bool ok = req.result == UnityWebRequest.Result.Success;
                LastResult = ok ? $"saved {recording.id}: {summary}" : $"upload failed ({req.responseCode} {req.error}): {summary}";
                UiToast.Show(ok ? $"Demonstration saved ({summary})." : "Couldn't upload the demonstration: is the server reachable?",
                    ok ? ColorRole.Info : ColorRole.Danger);
                Log.Info($"DemoRecorder: {LastResult}");
            }
            m_Recording = null;
            m_Request = null;
            Current = State.Idle;
        }

        // ---------------- sampling ----------------

        static Transform Content() =>
            Services.TryGet<SceneRoot>(out var root) && root.IsRuntimePackage && root.StructureSpace != null ? root.StructureSpace : null;

        /// World → the recording's frame: the scan's (when one is loaded) or the room's, right-handed either way.
        static Vector3 ToFrame(Transform content, Vector3 world) =>
            DemoRecording.ToGltf(content != null ? content.InverseTransformPoint(world) : world);

        static Quaternion ToFrame(Transform content, Quaternion world) =>
            DemoRecording.ToGltf(content != null ? Quaternion.Inverse(content.rotation) * world : world);

        DemoSample Sample(float t)
        {
            var content = Content();
            var s = new DemoSample { t = t, headQ = Quaternion.identity };
            var head = Camera.main != null ? Camera.main.transform : null;
            if (head != null)
            {
                s.headP = ToFrame(content, head.position);
                s.headQ = ToFrame(content, head.rotation);
            }
            s.left = Hand(content, ToolHand.Left, OVRInput.Controller.LTouch, m_Source != null ? m_Source.leftHand : null);
            s.right = Hand(content, ToolHand.Right, OVRInput.Controller.RTouch, m_Source != null ? m_Source.rightHand : null);
            return s;
        }

        DemoHand Hand(Transform content, ToolHand hand, OVRInput.Controller controller, OVRHand ovrHand)
        {
            var h = new DemoHand { q = Quaternion.identity, forceN = -1f };
            if (m_Hub == null || !m_Hub.TryGetGrip(hand, out var grip)) return h;
            h.tracked = true;
            h.p = ToFrame(content, grip.position);
            h.q = ToFrame(content, grip.rotation);
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
                h.joints = Joints(content, hand);
            }
            return h;
        }

        /// The tracked skeleton of that hand, joint by joint, in the recording's frame; null when none is tracked.
        Vector3[] Joints(Transform content, ToolHand hand)
        {
            var side = hand == ToolHand.Left ? Oculus.Interaction.Input.Handedness.Left : Oculus.Interaction.Input.Handedness.Right;
            foreach (var skeleton in m_Skeletons)
            {
                if (skeleton == null || !skeleton.isActiveAndEnabled || skeleton.Handedness != side || !skeleton.IsTrackedDataValid) continue;
                var joints = new Vector3[JointCount];
                for (int j = 0; j < JointCount; j++)
                {
                    if (!skeleton.GetJointPose((IsdkJoint)j, out var pose)) return null;
                    joints[j] = ToFrame(content, pose.position);
                }
                return joints;
            }
            return null;
        }
    }
}
