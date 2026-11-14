using System;
using UnityEngine;

namespace Pathfinder.UI
{
    /// Accessibility options (persisted per device): high contrast turns every glass surface into ElevatedSolid;
    /// reduced motion removes decorative hover/press scaling and fades, keeping only the state changes.
    /// D2: the unit labels show (imperial by default for the HackGT build; the units chip switches it).
    /// D7 (W1.8): in DemoMode none of these are read from or written to PlayerPrefs, so each judge starts with the
    /// defaults (contrast and motion off, imperial).
    public static class UiSettings
    {
        const string KeyContrast = "pathfinder.ui.highContrast", KeyMotion = "pathfinder.ui.reducedMotion";
        /// D2: the PlayerPrefs key of the unit choice (0 imperial, 1 metric).
        public const string KeyUnits = "pathfinder.ui.units";
        static bool? s_Contrast, s_Motion;
        static Pathfinder.Core.UnitSystem? s_Units;

        public static event Action Changed;

        public static bool HighContrast
        {
            get => s_Contrast ??= Persist && PlayerPrefs.GetInt(KeyContrast, 0) == 1;
            set { if (HighContrast == value) return; s_Contrast = value; if (Persist) PlayerPrefs.SetInt(KeyContrast, value ? 1 : 0); Changed?.Invoke(); }
        }

        public static bool ReducedMotion
        {
            get => s_Motion ??= Persist && PlayerPrefs.GetInt(KeyMotion, 0) == 1;
            set { if (ReducedMotion == value) return; s_Motion = value; if (Persist) PlayerPrefs.SetInt(KeyMotion, value ? 1 : 0); Changed?.Invoke(); }
        }

        // D7 (W1.8)
        static bool Persist => Pathfinder.Core.DemoMode.PersistPrefs;

        /// AppCommands.ResetDemo: both off for the next person (saved values are only touched outside DemoMode).
        public static void ResetForNextPerson()
        {
            HighContrast = false;
            ReducedMotion = false;
            UseUnits(DefaultUnits);   // D2 × D7: the next judge starts in the build's unit
        }

        /// UX decision D2 (SPEC §9): imperial first for the HackGT build (US judges, US kitchen hardware in inches).
        public const Pathfinder.Core.UnitSystem DefaultUnits = Pathfinder.Core.UnitSystem.Imperial;

        /// D2: the one unit every on-screen label shows (Copy's length hooks read it). Persisted per device. Switch it
        /// with UnitsSwitch.Set / Toggle (the units chip does), which also re-labels what's already drawn.
        public static Pathfinder.Core.UnitSystem UnitSystem
        {
            get => s_Units ??= !Persist ? DefaultUnits
                : PlayerPrefs.GetInt(KeyUnits, (int)DefaultUnits) == (int)Pathfinder.Core.UnitSystem.Metric
                    ? Pathfinder.Core.UnitSystem.Metric : Pathfinder.Core.UnitSystem.Imperial;
            set { if (UnitSystem == value) return; s_Units = value; if (Persist) PlayerPrefs.SetInt(KeyUnits, (int)value); Changed?.Invoke(); }
        }

        /// D2: use this unit without saving it (tests, a demo reset): the device's saved choice is left alone, and
        /// PlayerPrefs isn't touched at all.
        public static void UseUnits(Pathfinder.Core.UnitSystem value)
        {
            if (s_Units == value) return;
            s_Units = value;
            Changed?.Invoke();
        }

        /// The tier actually drawn for a requested tier under the current settings.
        public static GlassTier Effective(GlassTier tier) =>
            HighContrast && (tier == GlassTier.GlassRegular || tier == GlassTier.GlassClear) ? GlassTier.ElevatedSolid : tier;

        /// Animation duration under the current settings (reduced motion: instant).
        public static float Duration(float seconds) => ReducedMotion ? 0f : seconds;

        /// Tests: forget cached values (PlayerPrefs stay).
        public static void ResetCache() { s_Contrast = null; s_Motion = null; s_Units = null; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetOnLoad() { Changed = null; ResetCache(); }
    }
}
