using System.Collections.Generic;
using Pathfinder.Agent.Grok;

namespace Pathfinder.Agent
{
    /// The context object sent with every /agent/command and /voice/command (backend docs/api.md §6): measurement (the
    /// active tape: drives the server's fit check), selected_part_id, candidate_ids (so "the first one" resolves),
    /// placed [{part_id, count}] (for "what else do I need?"; counts include array copies), tool, and — for voice and
    /// scene questions — frames [{id, jpg_b64}] (nearest photos first, at most 3). B1/B3 hand-off §1: `site` (the scene
    /// package open, as GET /scenes names it; left out for the built-in scene) and `scale` (the calibration applied,
    /// 1.0 = none). Grok (G1): frame_id, pointer, placed_box, drill_px, frame_jpg_b64 (only for the commands that read
    /// it), location, address, placement, survey_id — see <see cref="GrokContext"/>.
    public static class AgentContext
    {
        /// `text`: the typed command (null for voice: its words aren't known until the server transcribes them).
        public static Dictionary<string, object> Build(IList<Dictionary<string, string>> frames = null, string text = null)
        {
            var ctx = GrokContext.Build(GrokView.Snapshot(frames, text));
            AddCatalog(ctx, Pathfinder.Core.Services.Get<Pathfinder.Parts.CatalogWindow>());   // catalog
            AddAssetMode(ctx, Pathfinder.Core.UserPrefs.Assets);   // settings-assets
            return ctx;
        }

        /// catalog: `catalog` {open, site, environment, category, query, fits, visible_ids} — what the Catalog shows, so "the
        /// second one" and "show me fridges" resolve against it and the agent knows a search needs no tape (`measurement`
        /// is only there when a tape exists; `fits` says whether the person asked to fit it).
        public static void AddCatalog(Dictionary<string, object> ctx, Pathfinder.Parts.CatalogWindow catalog)
        {
            if (ctx == null || catalog == null) return;
            var m = catalog.Model;
            var ids = new List<string>();
            for (int i = 0; i < Pathfinder.Parts.CatalogModel.CardsPerPage; i++) if (m.PageItem(i)?.Id is string id) ids.Add(id);
            var c = new Dictionary<string, object>
            {
                ["open"] = catalog.IsOpen,
                ["site"] = m.Site,
                ["environment"] = m.Data?.environment,
                ["mode"] = m.Mode.ToString().ToLowerInvariant(),
                ["category"] = m.Mode == Pathfinder.Parts.CatalogMode.Browse ? m.CurrentCategory?.id : null,
                ["query"] = m.Query.Length > 0 ? m.Query : null,
                ["fits"] = m.FitsOn,
                ["visible_ids"] = ids,
            };
            ctx["catalog"] = c;
        }

        /// settings-assets: `asset_mode` ("hf" | "llm_scad" | "auto", Settings ▸ 3D models) rides in every context, so the
        /// session's searches (and the replace job) make their models that way (backend docs/api.md "Asset modes"). Pure.
        public static Dictionary<string, object> AddAssetMode(Dictionary<string, object> ctx, Pathfinder.Core.AssetMode mode)
        {
            if (ctx != null) ctx["asset_mode"] = Pathfinder.Core.UserPrefs.Wire(mode);
            return ctx;
        }

        /// site + scale (hand-off §1). The built-in scene has no package name the server knows: no site, no scale.
        public static void AddSite(Dictionary<string, object> ctx, Pathfinder.Scene.SceneRoot root)
        {
            if (root == null || !root.IsRuntimePackage || string.IsNullOrEmpty(root.Site)) return;
            ctx["site"] = root.Site;
            ctx["scale"] = System.Math.Round(root.Calibration, 5);
            // scalemodels: "site_default" | "user" | "none" (SiteScales).
            var source = Pathfinder.Core.Services.TryGet<Pathfinder.Scene.SceneStreamer>(out var s) ? s.ScaleSource : Pathfinder.Scene.ScaleSource.None;
            ctx["scale_source"] = Pathfinder.Scene.SiteScales.Wire(Pathfinder.Scene.SiteScales.Consistent(root.Calibration, source));
        }
    }
}
